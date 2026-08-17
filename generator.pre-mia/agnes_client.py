import base64
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


class AgnesAPIError(RuntimeError):
    """Retryable Agnes API error."""


class AgnesClient:
    def __init__(self):
        self.api_key = os.getenv("AGNES_API_KEY", "").strip()
        self.base_url = os.getenv("AGNES_BASE_URL", "https://apihub.agnes-ai.com/v1").rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        self.video_delay = int(os.getenv("AGNES_VIDEO_DELAY", "60"))
        self.image_delay = int(os.getenv("AGNES_IMAGE_DELAY", "3"))
        self._last_video = 0.0
        self._last_image = 0.0
        self.session = requests.Session()

    def _require_key(self) -> None:
        if not self.api_key:
            raise RuntimeError("AGNES_API_KEY is not configured")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        retry=retry_if_exception_type((requests.RequestException, AgnesAPIError)),
        reraise=True,
    )
    def chat(
        self,
        prompt: str,
        max_tokens: int = 2500,
        temperature: float = 0.7,
        system_prompt: Optional[str] = None,
    ) -> str:
        self._require_key()
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": os.getenv("AGNES_CHAT_MODEL", "agnes-2.0-flash"),
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        response = self.session.post(
            f"{self.base_url}/chat/completions",
            headers=self.headers,
            json=payload,
            timeout=180,
        )
        if response.status_code >= 500 or response.status_code == 429:
            raise AgnesAPIError(f"Chat service busy ({response.status_code})")
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=90),
        retry=retry_if_exception_type((requests.RequestException, AgnesAPIError)),
        reraise=True,
    )
    def generate_image(
        self,
        prompt: str,
        size: str = "1K",
        ratio: str = "9:16",
        image_urls: Optional[List[str]] = None,
    ) -> str:
        """Generate or edit an image and return a public URL or data URI."""
        self._require_key()
        self._rl_image()
        extra_body: Dict[str, Any] = {"response_format": "url"}
        if image_urls:
            extra_body["image"] = image_urls
        payload: Dict[str, Any] = {
            "model": os.getenv("AGNES_IMAGE_MODEL", "agnes-image-2.1-flash"),
            "prompt": prompt,
            "size": size,
            "ratio": ratio,
            "extra_body": extra_body,
        }
        response = self.session.post(
            f"{self.base_url}/images/generations",
            headers=self.headers,
            json=payload,
            timeout=360,
        )
        if response.status_code >= 500 or response.status_code == 429:
            raise AgnesAPIError(f"Image service busy ({response.status_code})")
        if response.status_code != 200:
            logger.error("Image error %s: %s", response.status_code, response.text[:800])
        response.raise_for_status()
        item = response.json()["data"][0]
        if item.get("url"):
            return item["url"]
        if item.get("b64_json"):
            return f"data:image/png;base64,{item['b64_json']}"
        raise RuntimeError("Agnes image response contained neither url nor b64_json")

    @retry(
        stop=stop_after_attempt(10),
        wait=wait_exponential(multiplier=2, min=30, max=300),
        retry=retry_if_exception_type((requests.RequestException, AgnesAPIError)),
        reraise=True,
    )
    def generate_video(
        self,
        prompt: str,
        image_url: Optional[str] = None,
        image_urls: Optional[List[str]] = None,
        mode: Optional[str] = None,
        width: int = 720,
        height: int = 1280,
        num_frames: int = 121,
        frame_rate: int = 24,
        negative_prompt: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> Dict[str, Any]:
        self._require_key()
        self._rl_video()
        payload: Dict[str, Any] = {
            "model": os.getenv("AGNES_VIDEO_MODEL", "agnes-video-v2.0"),
            "prompt": prompt,
            "width": width,
            "height": height,
            "num_frames": num_frames,
            "frame_rate": frame_rate,
        }
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt
        if seed is not None:
            payload["seed"] = int(seed)

        images = [u for u in (image_urls or []) if u]
        if image_url and not images:
            images = [image_url]
        if mode == "keyframes" and images:
            payload["extra_body"] = {"mode": "keyframes", "image": images[:2]}
        elif images:
            payload["extra_body"] = {"image": images}

        logger.info(
            "Video request: model=%s prompt_len=%d mode=%s reference=%s frames=%d",
            payload["model"], len(prompt), mode, bool(images), num_frames,
        )
        response = self.session.post(
            f"{self.base_url}/videos",
            headers=self.headers,
            json=payload,
            timeout=180,
        )
        if response.status_code in (429, 500, 502, 503, 520):
            body = response.text[:500]
            logger.warning("Agnes video service busy (%s): %s", response.status_code, body)
            raise AgnesAPIError(f"Video service busy ({response.status_code})")
        if response.status_code != 200:
            logger.error("Video error %s: %s", response.status_code, response.text[:800])
        response.raise_for_status()
        data = response.json()
        logger.info(
            "Video task created: video_id=%s status=%s size=%s seconds=%s",
            data.get("video_id"), data.get("status"), data.get("size"), data.get("seconds"),
        )
        return data

    def get_video_result(self, video_id: str) -> Optional[Dict[str, Any]]:
        self._require_key()
        response = self.session.get(
            "https://apihub.agnes-ai.com/agnesapi",
            params={"video_id": video_id, "model_name": "agnes-video-v2.0"},
            headers=self.headers,
            timeout=90,
        )
        response.raise_for_status()
        data = response.json()
        status = str(data.get("status", "")).lower()
        logger.info("Poll %s: status=%s progress=%s", video_id, status, data.get("progress"))
        if status == "completed":
            if data.get("error"):
                raise RuntimeError(f"Video generation error: {data['error']}")
            url = (data.get("metadata") or {}).get("url") or data.get("url")
            if not url:
                raise RuntimeError("No video URL in completed Agnes response")
            return data
        if status == "failed":
            raise RuntimeError(f"Video failed: {data.get('error', data)}")
        if status in ("queued", "pending", "in_progress", "processing", "running"):
            return None
        logger.warning("Unknown video status %r; treating as in progress", status)
        return None

    def wait_for_video(
        self,
        video_id: str,
        timeout: int = 1200,
        poll_interval: int = 15,
        progress_callback=None,
    ) -> Dict[str, Any]:
        started = time.monotonic()
        while time.monotonic() - started < timeout:
            result = self.get_video_result(video_id)
            if result:
                return result
            waited = int(time.monotonic() - started)
            if progress_callback:
                progress_callback(waited)
            time.sleep(poll_interval)
        raise TimeoutError(f"Agnes video task {video_id} timed out after {timeout}s")

    def download_file(self, url: str, output_path: str) -> str:
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if url.startswith("data:"):
            _, encoded = url.split(",", 1)
            destination.write_bytes(base64.b64decode(encoded))
            return str(destination)

        logger.info("Downloading: %s", url[:100])
        with self.session.get(url, stream=True, timeout=600) as response:
            response.raise_for_status()
            with destination.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)
        logger.info("Saved: %s", destination)
        return str(destination)

    @staticmethod
    def frames_for_duration(seconds: float) -> int:
        if seconds <= 4.8:
            return 121
        if seconds <= 9.5:
            return 241
        return 441

    def _rl_video(self) -> None:
        elapsed = time.time() - self._last_video
        if elapsed < self.video_delay:
            time.sleep(self.video_delay - elapsed)
        self._last_video = time.time()

    def _rl_image(self) -> None:
        elapsed = time.time() - self._last_image
        if elapsed < self.image_delay:
            time.sleep(self.image_delay - elapsed)
        self._last_image = time.time()
