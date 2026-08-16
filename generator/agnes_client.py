import os, time, logging, requests
from typing import Optional, Dict, Any
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)

class AgnesAPIError(Exception):
    pass

class AgnesClient:
    def __init__(self):
        self.api_key = os.getenv("AGNES_API_KEY", "")
        self.base_url = os.getenv("AGNES_BASE_URL", "https://apihub.agnes-ai.com/v1")
        self.headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        self.video_delay = int(os.getenv("AGNES_VIDEO_DELAY", "60"))
        self.image_delay = int(os.getenv("AGNES_IMAGE_DELAY", "3"))
        self._last_video = 0
        self._last_image = 0

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(1, 4, 60))
    def chat(self, prompt, max_tokens=2000, temperature=0.7) -> str:
        url = f"{self.base_url}/chat/completions"
        payload = {"model": "agnes-2.0-flash", "messages": [{"role": "user", "content": prompt}],
                   "max_tokens": max_tokens, "temperature": temperature}
        resp = requests.post(url, headers=self.headers, json=payload, timeout=120)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(1, 4, 60))
    def generate_image(self, prompt, size="1024x1024") -> str:
        self._rl_image()
        url = f"{self.base_url}/images/generations"
        payload = {"model": "agnes-image-2.1-flash", "prompt": prompt, "size": size, "n": 1}
        resp = requests.post(url, headers=self.headers, json=payload, timeout=120)
        resp.raise_for_status()
        return resp.json()["data"][0]["url"]

    @retry(stop=stop_after_attempt(10), wait=wait_exponential(2, 30, 300),
           retry=retry_if_exception_type(AgnesAPIError))
    def generate_video(self, prompt, image_url=None, mode=None, width=768, height=1152, num_frames=241):
        self._rl_video()
        url = f"{self.base_url}/videos"
        payload = {
            "model": "agnes-video-v2.0",
            "prompt": prompt,
            "width": width,
            "height": height,
            "num_frames": num_frames,
            "frame_rate": 24
        }
        if image_url:
            payload["image"] = image_url
        if mode == "keyframes":
            payload["extra_body"] = {"mode": "keyframes", "image": [image_url] if image_url else []}
        elif mode:
            payload["mode"] = mode

        logger.info(f"Video request: model={payload['model']}, prompt_len={len(prompt)}, mode={mode}")
        resp = requests.post(url, headers=self.headers, json=payload, timeout=120)

        if resp.status_code == 503:
            body = resp.json() if resp.text else {}
            if body.get("code") == "video_queue_full":
                logger.warning("Agnes video queue full, retrying...")
                raise AgnesAPIError("video_queue_full")

        if resp.status_code != 200:
            logger.error(f"Video error {resp.status_code}: {resp.text[:500]}")
        resp.raise_for_status()

        data = resp.json()
        logger.info(f"Video task created: video_id={data.get('video_id')}, status={data.get('status')}")
        return data

    def get_video_result(self, video_id):
        url = f"https://apihub.agnes-ai.com/agnesapi?video_id={video_id}"
        resp = requests.get(url, headers=self.headers, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        status = data.get("status")
        logger.info(f"Poll: status={status}")

        if status == "completed":
            # Check for error in completed response
            error = data.get("error")
            if error:
                logger.error(f"Video completed with error: {error}")
                raise RuntimeError(f"Video generation error: {error}")

            # URL can be in metadata.url or top-level url
            video_url = None
            if "metadata" in data and isinstance(data["metadata"], dict):
                video_url = data["metadata"].get("url")
            if not video_url:
                video_url = data.get("url")
            if not video_url:
                logger.error(f"No URL found. Keys: {list(data.keys())}")
                raise RuntimeError("No video URL in completed response")

            logger.info(f"Video ready: {video_url[:80]}...")
            return data
        elif status == "failed":
            raise RuntimeError(f"Video failed: {data.get('error', data)}")
        elif status in ("queued", "in_progress", "processing"):
            return None
        else:
            logger.warning(f"Unknown status '{status}', treating as in-progress")
            return None

    def download_file(self, url, output_path):
        logger.info(f"Downloading: {url[:80]}...")
        resp = requests.get(url, stream=True, timeout=300)
        resp.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        logger.info(f"Saved: {output_path}")
        return output_path

    def _rl_video(self):
        elapsed = time.time() - self._last_video
        if elapsed < self.video_delay:
            time.sleep(self.video_delay - elapsed)
        self._last_video = time.time()

    def _rl_image(self):
        elapsed = time.time() - self._last_image
        if elapsed < self.image_delay:
            time.sleep(self.image_delay - elapsed)
        self._last_image = time.time()
