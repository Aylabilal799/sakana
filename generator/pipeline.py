import re
import os, json, logging, shutil, time
from pathlib import Path
from datetime import datetime
from typing import Dict
from generator.agnes_client import AgnesClient
from generator.tts_engine import TTSEngine
from generator.character_manager import CharacterManager
from generator.seo_generator import SEOGenerator
from generator.caption_engine import CaptionEngine
from generator.video_assembler import VideoAssembler

logger = logging.getLogger(__name__)

class VideoPipeline:
    def __init__(self, job_id: str, status_callback=None):
        self.job_id = job_id
        self.status_callback = status_callback
        self.agnes = AgnesClient()
        self.tts = TTSEngine()
        self.character = CharacterManager()
        self.seo = SEOGenerator()
        self.captions = CaptionEngine()
        self.assembler = VideoAssembler()
        self.job_dir = Path(f"/root/sakana/jobs/{job_id}")
        self.temp_dir = Path(f"/root/sakana/temp/{job_id}")
        self.output_dir = Path(f"/root/sakana/output/{job_id}")
        for d in [self.job_dir, self.temp_dir, self.output_dir]:
            d.mkdir(parents=True, exist_ok=True)
        self.metadata = {"job_id": job_id, "steps": [], "created_at": datetime.utcnow().isoformat()}

    def _update_status(self, step: str, progress: int, message: str = ""):
        self.metadata["current_step"] = step
        self.metadata["progress"] = progress
        self.metadata["steps"].append({"step": step, "time": datetime.utcnow().isoformat(), "message": message})
        if self.status_callback:
            self.status_callback(step, progress, message)
        with open(self.job_dir / "metadata.json", "w") as f:
            json.dump(self.metadata, f, indent=2)
        logger.info(f"[{self.job_id}] {step} ({progress}%) {message}")

    def run(self, script: str, genre: str = "story") -> Dict:
        try:
            self._update_status("SCRIPT_PROCESSING", 5, "Processing script...")
            self.metadata["script"] = script

            self._update_status("TTS_GENERATING", 10, "Generating narration...")
            audio_path, audio_duration = self.tts.generate(script, str(self.job_dir / "audio.wav"))
            self.metadata["audio"] = {"path": audio_path, "duration": audio_duration}

            ref_image_url = None
            if not self.character.has_reference_image():
                self._update_status("REF_IMAGE_GENERATING", 20, "Generating character reference...")
                ref_prompt = self.character.get_character_prompt("standing portrait, facing camera")
                ref_image_url = self.agnes.generate_image(ref_prompt, size="1024x1024")
                ref_path = self.agnes.download_file(ref_image_url, str(self.temp_dir / "ref.png"))
                self.character.set_reference_image(ref_path)

            self._update_status("SCENE_GENERATING", 30, "Generating scenes...")
            scenes = self._generate_scenes(script, audio_duration, ref_image_url)
            self.metadata["scenes"] = scenes

            scene_paths = []
            for i, scene in enumerate(scenes):
                self._update_status("SCENE_GENERATING", 30 + (i * 10), f"Downloading scene {i+1}/{len(scenes)}...")
                sp = self.temp_dir / f"scene_{i+1:02d}.mp4"
                self.agnes.download_file(scene["video_url"], str(sp))
                scene_paths.append(str(sp))

            self._update_status("CAPTION_GENERATING", 80, "Generating CapCut-style captions...")
            ass_path = self.captions.generate_from_script(script, audio_duration, str(self.job_dir / "captions.ass"))

            self._update_status("VIDEO_ASSEMBLY", 85, "Assembling final video...")
            final_path = self.assembler.assemble(scene_paths, audio_path, ass_path, str(self.output_dir / "video.mp4"))
            self.metadata["video"] = {"path": final_path}

            self._update_status("SEO_GENERATING", 95, "Generating YouTube metadata...")
            self.metadata["youtube"] = self.seo.generate(script, self.character.config.get("name", ""), genre)

            self.metadata["status"] = "completed"
            self.metadata["completed_at"] = datetime.utcnow().isoformat()
            with open(self.job_dir / "metadata.json", "w") as f:
                json.dump(self.metadata, f, indent=2)
            with open(self.job_dir / "script.txt", "w") as f:
                f.write(script)

            shutil.rmtree(self.temp_dir, ignore_errors=True)
            self._update_status("COMPLETED", 100, "Done!")
            return self.metadata

        except Exception as e:
            logger.exception(f"Pipeline failed: {self.job_id}")
            self.metadata["status"] = "failed"
            self.metadata["error"] = str(e)
            with open(self.job_dir / "metadata.json", "w") as f:
                json.dump(self.metadata, f, indent=2)
            raise

    def _generate_scenes(self, script: str, target_duration: float, ref_image_url=None) -> list:
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', script) if s.strip()]

        # Dynamic scene count: more scenes for longer scripts
        # Aim for ~5-8 seconds of video per scene
        words = len(script.split())
        estimated_tts_seconds = words * 0.35  # rough estimate: 0.35s per word
        num_scenes = min(max(int(estimated_tts_seconds / 5), 3), 8)  # 3 to 8 scenes

        spc = max(1, len(sentences) // num_scenes)
        scenes = []

        for i in range(num_scenes):
            start = i * spc
            end = start + spc if i < num_scenes - 1 else len(sentences)
            text = " ".join(sentences[start:end])
            self._update_status("SCENE_GENERATING", 30 + (i * 5), f"Scene {i+1}/{num_scenes}...")
            prompt = self.character.get_character_prompt(text)

            if i == 0 and ref_image_url:
                result = self.agnes.generate_video(
                    prompt=prompt, image_url=ref_image_url,
                    width=768, height=1152, num_frames=241
                )
            else:
                result = self.agnes.generate_video(
                    prompt=prompt, width=768, height=1152, num_frames=241
                )

            vid = result.get("video_id") or result.get("task_id") or result.get("id")
            if not vid:
                logger.error(f"Unexpected response: {result}")
                raise RuntimeError("No video_id in response")

            waited, max_wait, res = 0, 600, None
            while waited < max_wait:
                res = self.agnes.get_video_result(vid)
                if res: break
                self._update_status("SCENE_GENERATING", 30 + (i * 5), f"Waiting scene {i+1}... ({waited}s)")
                time.sleep(15); waited += 15

            if not res:
                raise TimeoutError(f"Scene {i+1} timed out")

            video_url = res.get("metadata", {}).get("url") or res.get("url")
            scenes.append({"index": i+1, "text": text, "prompt": prompt,
                           "video_id": vid, "video_url": video_url})
        return scenes
