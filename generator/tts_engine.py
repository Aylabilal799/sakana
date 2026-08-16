import os, time, logging
from pathlib import Path
from typing import Tuple
import soundfile as sf
from kokoro_onnx import Kokoro

logger = logging.getLogger(__name__)

class TTSEngine:
    def __init__(self, model_path=None, voices_path=None, default_voice=None):
        self.model_path = model_path or os.getenv("KOKORO_MODEL_PATH", "/root/sakana/models/kokoro/kokoro-v1.0.onnx")
        self.voices_path = voices_path or os.getenv("KOKORO_VOICES_PATH", "/root/sakana/models/kokoro/voices-v1.0.bin")
        self.default_voice = default_voice or os.getenv("KOKORO_VOICE", "af_bella")
        logger.info(f"Loading Kokoro from {self.model_path}")
        start = time.time()
        self.kokoro = Kokoro(self.model_path, self.voices_path)
        logger.info(f"Loaded in {time.time()-start:.2f}s")

    def generate(self, text, output_path=None, voice=None, speed=1.0) -> Tuple[str, float]:
        voice = voice or self.default_voice
        output_path = output_path or f"/root/sakana/temp/tts_{int(time.time())}.wav"
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"TTS: voice={voice}, len={len(text)}")
        start = time.time()
        samples, sample_rate = self.kokoro.create(text, voice=voice, speed=speed, lang="en-us")
        sf.write(output_path, samples, sample_rate)
        duration = len(samples) / sample_rate
        logger.info(f"TTS done in {time.time()-start:.2f}s ({duration:.2f}s)")
        return output_path, duration

    def list_voices(self):
        return ["af_bella","af_heart","af_nicole","af_sarah","bf_emma"]

    def get_female_voices(self):
        return [{"id":"af_bella","name":"Bella","grade":"A-"},
                {"id":"af_heart","name":"Heart","grade":"A"},
                {"id":"af_nicole","name":"Nicole","grade":"B-"},
                {"id":"bf_emma","name":"Emma","grade":"B-"}]
