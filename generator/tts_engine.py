import logging
import os
import random
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import soundfile as sf
from kokoro_onnx import Kokoro

logger = logging.getLogger(__name__)


class TTSEngine:
    """Kokoro TTS engine with expanded voice library for Mia + Confession channels."""

    # Expanded Kokoro voice library — includes all common voices
    # Grade is approximate quality/character rating for reference
    VOICES = [
        # Female American (af_)
        {"id": "af_bella", "name": "Bella", "gender": "female", "grade": "A-"},
        {"id": "af_heart", "name": "Heart", "gender": "female", "grade": "A"},
        {"id": "af_nicole", "name": "Nicole", "gender": "female", "grade": "A-"},
        {"id": "af_sarah", "name": "Sarah", "gender": "female", "grade": "B+"},
        {"id": "af_sky", "name": "Sky", "gender": "female", "grade": "A-"},
        {"id": "af_jessica", "name": "Jessica", "gender": "female", "grade": "B+"},
        {"id": "af_alloy", "name": "Alloy", "gender": "female", "grade": "B+"},
        {"id": "af_aoede", "name": "Aoede", "gender": "female", "grade": "B+"},
        {"id": "af_kore", "name": "Kore", "gender": "female", "grade": "B+"},
        {"id": "af_nova", "name": "Nova", "gender": "female", "grade": "B+"},
        {"id": "af_river", "name": "River", "gender": "female", "grade": "B+"},
        {"id": "af_fenrir", "name": "Fenrir", "gender": "female", "grade": "B"},
        {"id": "af_puck", "name": "Puck", "gender": "female", "grade": "B"},
        # Male American (am_)
        {"id": "am_adam", "name": "Adam", "gender": "male", "grade": "A-"},
        {"id": "am_michael", "name": "Michael", "gender": "male", "grade": "A-"},
        {"id": "am_echo", "name": "Echo", "gender": "male", "grade": "B+"},
        {"id": "am_eric", "name": "Eric", "gender": "male", "grade": "B+"},
        {"id": "am_fenrir", "name": "Fenrir", "gender": "male", "grade": "B"},
        {"id": "am_liam", "name": "Liam", "gender": "male", "grade": "B+"},
        {"id": "am_onyx", "name": "Onyx", "gender": "male", "grade": "B+"},
        {"id": "am_puck", "name": "Puck", "gender": "male", "grade": "B"},
        {"id": "am_santa", "name": "Santa", "gender": "male", "grade": "B"},
        # British female (bf_)
        {"id": "bf_emma", "name": "Emma", "gender": "female", "grade": "B+"},
        # British male (bm_)
        {"id": "bm_george", "name": "George", "gender": "male", "grade": "B+"},
        {"id": "bm_lewis", "name": "Lewis", "gender": "male", "grade": "B+"},
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

        # Validate voice against known list and fallback if unknown
        if not self.is_valid_voice(voice):
            logger.warning(
                "Voice '%s' not in known voice list, falling back to '%s'",
                voice, self.default_voice,
            )
            voice = self.default_voice

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
        """Return all available voice IDs."""
        return [voice["id"] for voice in self.VOICES]

    def get_female_voices(self) -> List[Dict]:
        """Return all female voices."""
        return [v for v in self.VOICES if v.get("gender") == "female"]

    def get_male_voices(self) -> List[Dict]:
        """Return all male voices."""
        return [v for v in self.VOICES if v.get("gender") == "male"]

    def get_voices_by_gender(self, gender: str) -> List[Dict]:
        """Return all voices matching the given gender ('male' or 'female')."""
        gender_lower = gender.lower()
        return [v for v in self.VOICES if v.get("gender") == gender_lower]

    def is_valid_voice(self, voice_id: str) -> bool:
        """Check if a voice ID is in the known voice library."""
        return any(v["id"] == voice_id for v in self.VOICES)

    def get_voice_info(self, voice_id: str) -> Optional[Dict]:
        """Return metadata for a specific voice."""
        for voice in self.VOICES:
            if voice["id"] == voice_id:
                return dict(voice)
        return None

    def get_random_voice(self, gender: Optional[str] = None) -> str:
        """Get a random voice, optionally filtered by gender."""
        pool = self.VOICES
        if gender:
            pool = [v for v in pool if v.get("gender") == gender.lower()]
        if not pool:
            pool = self.VOICES
        return random.choice(pool)["id"]
