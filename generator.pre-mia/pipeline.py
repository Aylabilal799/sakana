import json
import logging
import math
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List
from urllib.parse import quote

from generator.agnes_client import AgnesClient
from generator.caption_engine import CaptionEngine
from generator.character_manager import CharacterManager
from generator.seo_generator import SEOGenerator
from generator.story_planner import StoryPlanner
from generator.tts_engine import TTSEngine
from generator.video_assembler import VideoAssembler

logger = logging.getLogger(__name__)


class VideoPipeline:
    """Existing pipeline upgraded into one end-to-end Mia influencer workflow."""

    def __init__(self, job_id: str, status_callback=None):
        self.job_id = job_id
        self.status_callback = status_callback
        self.project_dir = Path(os.getenv("PROJECT_DIRECTORY", "/root/sakana"))
        self.host_root = Path(os.getenv("OUTPUT_DIRECTORY", "/var/www/agnes-videos"))
        self.public_base = os.getenv("VIDEO_HOST_URL", "http://localhost:6464/videos").rstrip("/")

        # Every job owns all intermediate and persistent assets under jobs/JOB_ID.
        self.job_dir = self.project_dir / "jobs" / job_id
        self.scene_dir = self.job_dir / "scenes"
        self.audio_dir = self.job_dir / "audio"
        self.caption_dir = self.job_dir / "captions"
        self.work_dir = self.job_dir / "work"
        self.host_dir = self.host_root / job_id
        for directory in (
            self.job_dir, self.scene_dir, self.audio_dir, self.caption_dir,
            self.work_dir, self.host_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

        self.agnes = AgnesClient()
        self.story = StoryPlanner(self.agnes)
        self.character = CharacterManager()
        self.tts = TTSEngine(default_voice=self.character.config.get("voice", "af_bella"))
        self.captions = CaptionEngine()
        self.assembler = VideoAssembler()
        self.seo = SEOGenerator()
        self.metadata = {
            "job_id": job_id,
            "status": "PENDING",
            "created_at": self._now(),
            "steps": [],
        }

    def run(self, user_prompt: str, genre: str = "auto") -> Dict:
        try:
            self._update_status("STORY_GENERATING", 5, "🧠 Writing Mia's story...")
            plan = self.story.plan(user_prompt)
            if genre and genre not in ("auto", "story"):
                plan["genre"] = genre
            self.metadata.update({"prompt": user_prompt, "plan": plan, "script": plan["script"]})
            self._write_text(self.job_dir / "prompt.txt", user_prompt)
            self._write_text(self.job_dir / "script.txt", plan["script"])
            self._write_json(self.job_dir / "story_plan.json", plan)

            self._update_status("TTS_GENERATING", 14, "🎙 Generating Mia's Kokoro voice...")
            audio_path, audio_duration = self.tts.generate(
                plan["script"], str(self.audio_dir / "mia_narration.wav"),
                voice=self.character.config.get("voice", "af_bella"),
            )
            self.metadata["audio"] = {
                "path": audio_path,
                "duration": audio_duration,
                "voice": self.character.config.get("voice", "af_bella"),
            }

            self._ensure_reference_image()
            reference_url = self.character.publish_reference()
            self.metadata["character"] = self.character.get_summary()

            scene_durations = self._scene_durations(plan["scenes"], audio_duration)
            scene_paths = self._generate_scenes(plan, scene_durations, reference_url)

            self._update_status("CAPTION_GENERATING", 78, "💬 Creating professional captions...")
            ass_path = self.captions.generate_from_script(
                plan["script"], audio_duration, str(self.caption_dir / "mia_captions.ass")
            )

            self._update_status("VIDEO_ASSEMBLY", 84, "✂️ Assembling full-screen 9:16 video...")
            job_final_path = self.assembler.assemble(
                scene_paths,
                audio_path,
                ass_path,
                str(self.job_dir / "final_video.mp4"),
                scene_durations=scene_durations,
                tone=plan.get("tone", "warm natural"),
            )
            final_path = str(self.host_dir / "mia_video.mp4")
            shutil.copy2(job_final_path, final_path)
            final_duration = self.assembler.probe_duration(final_path)

            self._update_status("SEO_GENERATING", 94, "📝 Creating YouTube metadata...")
            youtube = self.seo.generate(plan)
            job_seo_path = self.seo.write_text_file(youtube, str(self.job_dir / "mia_youtube.txt"))
            seo_path = str(self.host_dir / "mia_youtube.txt")
            shutil.copy2(job_seo_path, seo_path)

            self._publish_supporting_files(plan, ass_path)
            video_url = self._public_url("mia_video.mp4")
            seo_url = self._public_url("mia_youtube.txt")
            self.metadata.update({
                "status": "COMPLETED",
                "completed_at": self._now(),
                "youtube": youtube,
                "video": {
                    "path": final_path,
                    "url": video_url,
                    "duration": final_duration,
                    "width": 1080,
                    "height": 1920,
                    "fps": 24,
                    "scenes": len(scene_paths),
                },
                "seo_file": {"path": seo_path, "url": seo_url},
            })
            shutil.rmtree(self.work_dir, ignore_errors=True)
            shutil.rmtree(self.job_dir / ".assembly", ignore_errors=True)
            self._update_status("COMPLETED", 100, "✅ Mia video completed")
            self._write_json(self.host_dir / "metadata.json", self.metadata)
            self._fix_host_permissions()
            return self.metadata
        except Exception as exc:
            logger.exception("Mia pipeline failed: %s", self.job_id)
            self.metadata["status"] = "FAILED"
            self.metadata["error"] = str(exc)
            self.metadata["failed_at"] = self._now()
            self._write_json(self.job_dir / "metadata.json", self.metadata)
            raise

    def _ensure_reference_image(self) -> None:
        if self.character.has_reference_image():
            self._update_status("IDENTITY_READY", 22, "👩 Mia's persistent identity reference is ready")
            return
        self._update_status("REFERENCE_GENERATING", 20, "👩 Creating Mia's permanent identity reference...")
        image_url = self.agnes.generate_image(
            self.character.reference_generation_prompt(), size="1K", ratio="9:16"
        )
        reference_path = self.agnes.download_file(image_url, str(self.work_dir / "mia_reference.png"))
        self.character.set_reference_image(reference_path)

    def _generate_scenes(self, plan: Dict, durations: List[float], reference_url: str) -> List[str]:
        scenes = plan["scenes"]
        outputs: List[str] = []
        generated_metadata = []
        for index, (scene, duration) in enumerate(zip(scenes, durations), 1):
            base = 26 + int((index - 1) / max(len(scenes), 1) * 48)
            self._update_status(
                "SCENE_KEYFRAME_GENERATING", base,
                f"🎬 Generating Mia scene {index}/{len(scenes)} identity keyframe...",
            )
            keyframe_prompt = self.character.scene_keyframe_prompt(scene, plan.get("outfit"))
            keyframe_url = self.agnes.generate_image(
                keyframe_prompt, size="1K", ratio="9:16", image_urls=[reference_url]
            )
            keyframe_path = self.agnes.download_file(
                keyframe_url, str(self.scene_dir / f"scene_{index:02d}_keyframe.png")
            )
            # The Agnes video API must fetch a publicly reachable URL, not a /root local path.
            public_keyframe = self.host_dir / f"scene_{index:02d}_keyframe.png"
            shutil.copy2(keyframe_path, public_keyframe)
            public_keyframe.chmod(0o644)
            public_keyframe_url = self._public_url(public_keyframe.name)

            self._update_status(
                "SCENE_VIDEO_GENERATING", min(73, base + 4),
                f"🎥 Animating Mia scene {index}/{len(scenes)}...",
            )
            result = self.agnes.generate_video(
                prompt=self.character.video_motion_prompt(scene),
                image_url=public_keyframe_url,
                mode=self.character.config.get("video_mode", "ti2vid"),
                width=720,
                height=1280,
                num_frames=self.agnes.frames_for_duration(duration),
                frame_rate=24,
                negative_prompt=self.character.get_negative_prompt(),
            )
            video_id = result.get("video_id") or result.get("task_id") or result.get("id")
            if not video_id:
                raise RuntimeError(f"Scene {index}: Agnes returned no video_id")
            completed = self.agnes.wait_for_video(
                video_id,
                timeout=1800,
                progress_callback=lambda waited, i=index, total=len(scenes), p=base: self._update_status(
                    "SCENE_VIDEO_GENERATING", min(73, p + 4),
                    f"⏳ Waiting for Mia scene {i}/{total} ({waited}s)...",
                ),
            )
            video_url = (completed.get("metadata") or {}).get("url") or completed.get("url")
            video_path = self.agnes.download_file(
                video_url, str(self.scene_dir / f"scene_{index:02d}.mp4")
            )
            outputs.append(video_path)
            public_keyframe.unlink(missing_ok=True)
            generated_metadata.append({
                **scene,
                "duration": duration,
                "keyframe_path": keyframe_path,
                "video_id": video_id,
                "video_url": video_url,
                "video_path": video_path,
            })
        self.metadata["scenes"] = generated_metadata
        return outputs

    @staticmethod
    def _scene_durations(scenes: List[Dict], audio_duration: float) -> List[float]:
        weights = [max(1, len(str(scene.get("narration", "")).split())) for scene in scenes]
        total = sum(weights) or len(scenes)
        raw = [audio_duration * weight / total for weight in weights]
        # Agnes provides discrete approximate clip lengths. Allocation still remains exact for assembly.
        return raw

    def _publish_supporting_files(self, plan: Dict, ass_path: str) -> None:
        shutil.copy2(self.job_dir / "script.txt", self.host_dir / "mia_script.txt")
        shutil.copy2(self.job_dir / "story_plan.json", self.host_dir / "story_plan.json")
        shutil.copy2(ass_path, self.host_dir / "mia_captions.ass")

    def _public_url(self, filename: str) -> str:
        return f"{self.public_base}/{quote(self.job_id)}/{quote(filename)}"

    def _fix_host_permissions(self) -> None:
        self.host_dir.chmod(0o755)
        for path in self.host_dir.rglob("*"):
            path.chmod(0o755 if path.is_dir() else 0o644)

    def _update_status(self, step: str, progress: int, message: str = "") -> None:
        self.metadata["current_step"] = step
        self.metadata["progress"] = max(0, min(100, int(progress)))
        self.metadata["steps"].append({"step": step, "time": self._now(), "message": message})
        self._write_json(self.job_dir / "metadata.json", self.metadata)
        if self.status_callback:
            self.status_callback(step, self.metadata["progress"], message)
        logger.info("[%s] %s (%d%%) %s", self.job_id, step, progress, message)

    @staticmethod
    def _write_text(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    @staticmethod
    def _write_json(path: Path, value: Dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
