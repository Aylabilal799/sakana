import logging
import os
import time
from pathlib import Path
from typing import List, Optional, Tuple

import soundfile as sf
from kokoro_onnx import Kokoro

logger = logging.getLogger(__name__)


class TTSEngine:
    VOICES = [
        {"id": "af_bella", "name": "Bella", "grade": "A-"},
        {"id": "af_heart", "name": "Heart", "grade": "A"},
        {"id": "af_nicole", "name": "Nicole", "grade": "B-"},
        {"id": "af_sarah", "name": "Sarah", "grade": "B-"},
        {"id": "bf_emma", "name": "Emma", "grade": "B-"},
    ]

    def __init__(self, model_path=None, voices_path=None, default_voice=None):
        self.model_path = model_path or os.getenv(
            "KOKORO_MODEL_PATH", "/root/sakana/models/kokoro/kokoro-v1.0.onnx"
        )
        self.voices_path = voices_path or os.getenv(
            "KOKORO_VOICES_PATH", "/root/sakana/models/kokoro/voices-v1.0.bin"
        )
        self.default_voice = default_voice or os.getenv("KOKORO_VOICE", "af_bella")
        self._kokoro: Optional[Kokoro] = None

    def _load(self) -> Kokoro:
        if self._kokoro is None:
            for path in (self.model_path, self.voices_path):
                if not Path(path).is_file():
                    raise FileNotFoundError(f"Kokoro asset not found: {path}")
            logger.info("Loading Kokoro model from %s", self.model_path)
            started = time.time()
            self._kokoro = Kokoro(self.model_path, self.voices_path)
            logger.info("Kokoro loaded in %.2fs", time.time() - started)
        return self._kokoro

    def generate(
        self,
        text: str,
        output_path: Optional[str] = None,
        voice: Optional[str] = None,
        speed: float = 1.0,
    ) -> Tuple[str, float]:
        clean = " ".join(text.split())
        if not clean:
            raise ValueError("Cannot generate narration from an empty script")
        voice = voice or self.default_voice
        output_path = output_path or f"/root/sakana/temp/tts_{int(time.time())}.wav"
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Kokoro TTS: voice=%s chars=%d speed=%.2f", voice, len(clean), speed)
        started = time.time()
        samples, sample_rate = self._load().create(clean, voice=voice, speed=speed, lang="en-us")
        sf.write(str(destination), samples, sample_rate, subtype="PCM_16")
        duration = len(samples) / float(sample_rate)
        if duration <= 0:
            raise RuntimeError("Kokoro generated empty audio")
        logger.info("Kokoro completed in %.2fs (%.3fs)", time.time() - started, duration)
        return str(destination), duration

    def list_voices(self) -> List[str]:
        return [voice["id"] for voice in self.VOICES]

    def get_female_voices(self):
        return list(self.VOICES)
