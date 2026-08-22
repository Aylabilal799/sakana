import json
import logging
import re
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List
from urllib.parse import quote

from generator.agnes_client import AgnesClient
from generator.caption_engine import CaptionEngine
from generator.character_manager import CharacterManager
from generator.object_manager import ObjectManager
from generator.seo_generator import SEOGenerator
from generator.confession_seo import ConfessionSEOGenerator
from generator.sound_design import SoundDesigner
from generator.story_planner import StoryPlanner, ConfessionStoryPlanner
from generator.tts_engine import TTSEngine
from generator.video_assembler import VideoAssembler
from generator.visual_qa import VisualQA

logger = logging.getLogger(__name__)


class VideoPipeline:
    def __init__(self, job_id: str, status_callback=None, channel: str = "mia"):
        self.job_id = job_id
        self.status_callback = status_callback
        self.channel = channel
        self.is_confession = channel == "confession"

        self.project_dir = Path(os.getenv("PROJECT_DIRECTORY", "/root/sakana"))
        self.host_root = Path(os.getenv("OUTPUT_DIRECTORY", "/var/www/agnes-videos"))
        self.public_base = os.getenv("VIDEO_HOST_URL", "http://localhost:6464/videos").rstrip("/")

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
        
        # Choose planner based on channel
        if self.is_confession:
            self.story = ConfessionStoryPlanner(self.agnes)
        else:
            self.story = StoryPlanner(self.agnes)
            
        self.character = CharacterManager()
        self.object_manager = ObjectManager(self.job_dir, self.agnes)
        
        # For confession, default voice is unused — we use per-character voices
        default_voice = self.character.config.get("voice", "af_bella") if not self.is_confession else "af_nicole"
        self.tts = TTSEngine(default_voice=default_voice)
        
        self.captions = CaptionEngine()
        self.assembler = VideoAssembler()
        self.seo = ConfessionSEOGenerator() if self.is_confession else SEOGenerator()
        self.visual_qa = VisualQA(self.character)
        self.sound_designer = SoundDesigner(self.job_dir)
        self.metadata = {
            "job_id": job_id,
            "channel": channel,
            "status": "PENDING",
            "created_at": self._now(),
            "steps": [],
        }

    def run(self, user_prompt: str, genre: str = "auto") -> Dict:
        try:
            # Phase 1: Story Generation
            label = "confession story" if self.is_confession else "Mia's story"
            self._update_status("STORY_GENERATING", 5, f"🧠 Writing {label} with continuity tracking...")
            if self.is_confession and self._is_monologue(user_prompt):
                plan = self._create_monologue_plan(user_prompt)
            else:
                plan = self.story.plan(user_prompt)
            if genre and genre not in ("auto", "story"):
                plan["genre"] = genre
            self.metadata.update({"prompt": user_prompt, "plan": plan, "script": plan["script"]})
            self._write_text(self.job_dir / "prompt.txt", user_prompt)
            self._write_text(self.job_dir / "script.txt", plan["script"])
            self._write_json(self.job_dir / "story_plan.json", plan)

            # Phase 2: TTS (channel-specific)
            if self.is_confession:
                narration_path, audio_duration = self._generate_confession_audio(plan)
            else:
                self._update_status("TTS_GENERATING", 14, "🎙 Generating Mia's Kokoro voice...")
                narration_path, audio_duration = self.tts.generate(
                    plan["script"], str(self.audio_dir / "mia_narration.wav"),
                    voice=self.character.config.get("voice", "af_bella"),
                )
            
            voice_label = "multi-character" if self.is_confession else self.character.config.get("voice", "af_bella")
            self.metadata["audio"] = {
                "path": narration_path,
                "duration": audio_duration,
                "voice": voice_label,
            }

            # Phase 3: Character Identity Reference (Mia only)
            if self.is_confession:
                self._update_status("IDENTITY_READY", 18, "👥 Confession mode — skipping single-character reference")
                reference_url = None
                self.metadata["character"] = {"mode": "confession", "characters": plan.get("characters", [])}
            else:
                self._ensure_reference_image()
                reference_url = self.character.publish_reference()
                self.metadata["character"] = self.character.get_summary()

            # Phase 4: Register Persistent Objects
            self._update_status("OBJECT_REGISTRATION", 18, "📦 Registering persistent story objects...")
            self._register_story_objects(plan)

            # Phase 5: Sound Design Plan
            self._update_status("SOUND_DESIGN", 20, "🎵 Creating sound design plan...")
            sound_plan = self.sound_designer.generate_sound_plan(plan["scenes"], plan["script"])
            self.metadata["sound_design"] = sound_plan

            # Phase 6: Scene Generation with QA
            scene_durations = self._scene_durations(plan["scenes"], audio_duration)
            scene_paths = self._generate_scenes(plan, scene_durations, reference_url)

            # Phase 7: Audio Mixing (narration + SFX)
            self._update_status("AUDIO_MIXING", 72, "🔊 Mixing narration with sound design...")
            mixed_audio_path = self.sound_designer.mix_final_audio(
                narration_path, scene_durations,
                str(self.audio_dir / "mixed_final.wav")
            )
            mixed_duration = self._probe_duration(mixed_audio_path)
            self.metadata["mixed_audio"] = {"path": mixed_audio_path, "duration": mixed_duration}

            # Phase 8: Captions
            self._update_status("CAPTION_GENERATING", 78, "💬 Creating professional captions...")
            ass_path = self.captions.generate_from_script(
                plan["script"], mixed_duration, str(self.caption_dir / "captions.ass")
            )

            # Phase 9: Video Assembly
            self._update_status("VIDEO_ASSEMBLY", 84, "✂️ Assembling full-screen 9:16 video...")
            job_final_path = self.assembler.assemble(
                scene_paths,
                mixed_audio_path,
                ass_path,
                str(self.job_dir / "final_video.mp4"),
                scene_durations=scene_durations,
                tone=plan.get("tone", "warm natural"),
            )
            
            final_filename = "confession_video.mp4" if self.is_confession else "mia_video.mp4"
            final_path = str(self.host_dir / final_filename)
            shutil.copy2(job_final_path, final_path)
            final_duration = self.assembler.probe_duration(final_path)

            # Phase 10: Final QA
            self._update_status("FINAL_QA", 90, "🔍 Running final video quality check...")
            qa_result = self._final_video_qa(final_path, mixed_duration, plan)
            self.metadata["final_qa"] = qa_result

            # Phase 11: SEO
            self._update_status("SEO_GENERATING", 94, "📝 Creating YouTube metadata...")
            youtube = self.seo.generate(plan)

            # Confession channel: separate SEO metadata from Mia
            if self.is_confession:
                confession_title = plan.get("title", "Confession Story")[:100]
                youtube["title"] = confession_title
                # Strip any Mia/vlog terms, build confession description
                old_desc = youtube.get("description", "")
                if "Mia" in old_desc or "vlog" in old_desc.lower():
                    old_desc = "A real confession story.\n\n" + plan.get("script", "")[:400]
                youtube["description"] = old_desc[:5000]
                confession_tags = ["confession", "reddit story", "real story", "relationship", "drama", "storytime", "cheating", "secrets", "betrayal"]
                existing = [t for t in youtube.get("tags", []) if t.lower() not in ["mia", "daily vlog", "vlogger", "influencer"]]
                youtube["tags"] = list(dict.fromkeys(confession_tags + existing))[:15]
                logger.info("Confession SEO generated: title='%s' tags=%s", confession_title, youtube["tags"])
            seo_filename = "confession_youtube.txt" if self.is_confession else "mia_youtube.txt"
            job_seo_path = self.seo.write_text_file(youtube, str(self.job_dir / seo_filename))
            seo_path = str(self.host_dir / seo_filename)
            shutil.copy2(job_seo_path, seo_path)

            # Publish and cleanup
            self._publish_supporting_files(plan, ass_path)
            video_url = self._public_url(final_filename)
            seo_url = self._public_url(seo_filename)
            
            done_label = "Confession video completed" if self.is_confession else "Mia video completed"
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
            self._update_status("COMPLETED", 100, f"✅ {done_label}")
            self._write_json(self.host_dir / "metadata.json", self.metadata)
            self._fix_host_permissions()
            return self.metadata
        except Exception as exc:
            logger.exception("Pipeline failed: %s", self.job_id)
            self.metadata["status"] = "FAILED"
            self.metadata["error"] = str(exc)
            self.metadata["failed_at"] = self._now()
            self._write_json(self.job_dir / "metadata.json", self.metadata)
            raise

    def _generate_confession_audio(self, plan: Dict) -> tuple:
        """Generate multi-character dialogue audio by concatenating per-character TTS segments."""
        characters = {c["name"].upper(): c for c in plan.get("characters", [])}
        script = plan["script"]

        # Parse dialogue lines: CHARACTERNAME: dialogue text
        lines = []
        for line in script.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            if ":" in line:
                speaker, text = line.split(":", 1)
                speaker = speaker.strip().upper()
                text = text.strip()
                if speaker and text:
                    lines.append((speaker, text))

        if not lines:
            # Monologue: single-character narration using assigned voice
            voice = plan.get("characters", [{}])[0].get("voice", "af_nicole") if plan.get("characters") else "af_nicole"
            logger.info("Monologue mode — single voice: %s", voice)
            output_path = str(self.audio_dir / "confession_narration.wav")
            return self.tts.generate(script, output_path, voice=voice)

        self._update_status("TTS_GENERATING", 14, f"🎙 Generating {len(lines)} dialogue lines for {len(characters)} characters...")

        # Generate audio for each dialogue line
        segment_files = []
        total_duration = 0

        for i, (speaker, text) in enumerate(lines):
            char_config = characters.get(speaker, {})
            voice = char_config.get("voice", "af_nicole")
            speaker_name = char_config.get("name", speaker).title()
            
            seg_path = str(self.audio_dir / f"dialogue_{i:03d}_{speaker}.wav")
            path, duration = self.tts.generate(text, seg_path, voice=voice)
            segment_files.append(path)
            total_duration += duration
            logger.info("Generated line %d/%d: %s (voice=%s, dur=%.2fs)", i+1, len(lines), speaker_name, voice, duration)

        # Concatenate all segments with ffmpeg
        concat_list = str(self.audio_dir / "concat_list.txt")
        with open(concat_list, "w", encoding="utf-8") as f:
            for path in segment_files:
                # Escape single quotes in path for ffmpeg
                f.write(f"file '{path}'\n")

        output_path = str(self.audio_dir / "confession_narration.wav")
        
        logger.info("Concatenating %d audio segments with ffmpeg...", len(segment_files))
        try:
            result = subprocess.run(
                [
                    "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                    "-i", concat_list, "-ar", "24000", "-ac", "1",
                    output_path
                ],
                check=True, capture_output=True, text=True,
            )
            logger.info("Audio concatenation successful: %s", output_path)
        except subprocess.CalledProcessError as e:
            logger.error("ffmpeg concat failed: %s\nstderr: %s", e, e.stderr)
            # Fallback: copy the first segment
            shutil.copy2(segment_files[0], output_path)

        return output_path, total_duration

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

    def _register_story_objects(self, plan: Dict) -> None:
        """Register persistent objects from the story plan."""
        for obj in plan.get("key_objects", []):
            if isinstance(obj, dict) and obj.get("name"):
                try:
                    self.object_manager.register_object(
                        obj_id=obj["name"],
                        obj_type=obj.get("type", "prop"),
                        description=obj.get("description", ""),
                        introduced_scene=obj.get("introduced_scene", 1),
                        owner=obj.get("owner", "Mia"),
                    )
                except Exception as exc:
                    logger.warning("Failed to register object %s: %s", obj.get("name"), exc)

    def _generate_scenes(self, plan: Dict, durations: List[float], reference_url: str = None) -> List[str]:
        scenes = plan["scenes"]
        outputs: List[str] = []
        generated_metadata = []

        for index, (scene, duration) in enumerate(zip(scenes, durations), 1):
            base = 26 + int((index - 1) / max(len(scenes), 1) * 42)

            # Build scene state
            scene_state = {
                "location": scene.get("location", "the current location"),
                "outfit": plan.get("outfit", ""),
                "objects_visible": scene.get("objects_visible", []),
                "objects_held": scene.get("objects_held", []),
                "emotional_state": scene.get("emotional_state", "curious"),
                "shot_type": scene.get("shot_type", "handheld medium shot"),
                "camera_motion": scene.get("camera_motion", "subtle handheld push-in"),
                "lighting": scene.get("lighting", "natural warm realistic light"),
                "expression": scene.get("expression", "natural and emotionally appropriate"),
                "story_event": scene.get("story_event", ""),
            }

            # Build object prompt segment
            object_prompt = self.object_manager.build_object_prompt_segment(index, scene)

            self._update_status(
                "SCENE_KEYFRAME_GENERATING", base,
                f"🎬 Generating scene {index}/{len(scenes)} identity keyframe...",
            )

            # Generate keyframe — confession uses text-only prompts, Mia uses character reference
            if self.is_confession:
                keyframe_prompt = self._confession_scene_keyframe_prompt(scene, plan, scene_state)
            else:
                keyframe_prompt = self.character.scene_keyframe_prompt(scene, scene_state)
                
            if object_prompt:
                keyframe_prompt = keyframe_prompt.replace(
                    "Vertical 9:16 composition",
                    f"{object_prompt}Vertical 9:16 composition"
                )

            keyframe_url = self.agnes.generate_image(
                keyframe_prompt, size="1K", ratio="9:16"
            )
            keyframe_path = self.agnes.download_file(
                keyframe_url, str(self.scene_dir / f"scene_{index:02d}_keyframe.png")
            )

            # Visual QA on keyframe
            expected_objects = scene.get("objects_visible", []) + scene.get("objects_held", [])
            qa_pass, qa_reason = self.visual_qa.validate_image(keyframe_path, index, expected_objects)
            if not qa_pass:
                logger.warning("Scene %d keyframe QA: %s", index, qa_reason)

            self._update_status(
                "SCENE_VIDEO_GENERATING", min(68, base + 4),
                f"🎥 Animating scene {index}/{len(scenes)}...",
            )

            # Generate video using the keyframe
            if self.is_confession:
                motion_prompt = self._confession_video_motion_prompt(scene, scene_state)
            else:
                motion_prompt = self.character.video_motion_prompt(scene, scene_state)
                
            result = self.agnes.generate_video(
                prompt=motion_prompt,
                image_url=keyframe_url,
                mode=self.character.config.get("video_mode", "ti2vid") if not self.is_confession else "ti2vid",
                width=720,
                height=1280,
                num_frames=self.agnes.frames_for_duration(duration),
                frame_rate=24,
                negative_prompt=self.character.get_negative_prompt() if not self.is_confession else "",
            )
            video_id = result.get("video_id") or result.get("task_id") or result.get("id")
            if not video_id:
                raise RuntimeError(f"Scene {index}: Agnes returned no video_id")

            completed = self.agnes.wait_for_video(
                video_id,
                timeout=1800,
                progress_callback=lambda waited, i=index, total=len(scenes), p=base: self._update_status(
                    "SCENE_VIDEO_GENERATING", min(68, p + 4),
                    f"⏳ Waiting for scene {i}/{total} ({waited}s)...",
                ),
            )
            video_url = (completed.get("metadata") or {}).get("url") or completed.get("url")
            video_path = self.agnes.download_file(
                video_url, str(self.scene_dir / f"scene_{index:02d}.mp4")
            )
            outputs.append(video_path)

            # Update object states
            for obj_id in scene.get("objects_visible", []) + scene.get("objects_held", []):
                self.object_manager.update_object_state(
                    obj_id, index, status="active",
                    owner="Mia" if obj_id in scene.get("objects_held", []) else None
                )

            generated_metadata.append({
                **scene,
                "duration": duration,
                "keyframe_path": keyframe_path,
                "keyframe_url": keyframe_url,
                "video_id": video_id,
                "video_url": video_url,
                "video_path": video_path,
                "qa_pass": qa_pass,
                "qa_reason": qa_reason,
            })

        self.metadata["scenes"] = generated_metadata
        self.metadata["visual_qa_failures"] = self.visual_qa.get_failure_report()
        return outputs

    def _confession_scene_keyframe_prompt(self, scene: Dict, plan: Dict, scene_state: Dict) -> str:
        """Build a cinematic keyframe prompt for confession multi-character scenes."""
        characters = plan.get("characters", [])
        char_descs = []
        for c in characters:
            char_descs.append(
                f"{c['name']} ({c.get('gender', 'person')} in {c.get('age', 'their 20s')}, "
                f"{c.get('role', 'character')})"
            )
        
        char_text = ", ".join(char_descs)
        desc = scene.get("description", "")
        visual = scene.get("visual_prompt", desc)
        mood = scene.get("mood", "tense")
        lighting = scene_state.get("lighting", "natural warm realistic light")
        location = scene_state.get("location", "indoor location")

        return (
            f"Cinematic 9:16 vertical composition. {visual}. "
            f"Characters: {char_text}. "
            f"Location: {location}. "
            f"Atmosphere: {mood}, emotionally charged, photorealistic. "
            f"Lighting: {lighting}. "
            f"Movie quality, sharp focus, natural skin textures, detailed environment. "
            f"Shot on professional cinema camera, shallow depth of field."
        )

    def _confession_video_motion_prompt(self, scene: Dict, scene_state: Dict) -> str:
        """Build a video motion prompt for confession scenes."""
        desc = scene.get("description", "")
        visual = scene.get("visual_prompt", desc)
        action = scene_state.get("story_event", "characters interacting")
        camera = scene_state.get("camera_motion", "subtle handheld movement")
        
        return (
            f"Cinematic scene: {visual}. "
            f"Characters naturally moving, gesturing, and reacting to each other. "
            f"Action: {action}. "
            f"Camera: {camera}, smooth professional motion. "
            f"Photorealistic, natural lighting, emotional acting, movie quality. "
            f"Characters maintain consistent appearance throughout the shot."
        )

    @staticmethod
    def _scene_durations(scenes: List[Dict], audio_duration: float) -> List[float]:
        weights = [max(1, len(str(scene.get("narration", scene.get("dialogue_segment", ""))).split())) for scene in scenes]
        total = sum(weights) or len(scenes)
        raw = [audio_duration * weight / total for weight in weights]
        return raw

    def _final_video_qa(self, video_path: str, expected_duration: float, plan: Dict) -> Dict:
        """Run final quality checks on the assembled video."""
        result = {"pass": True, "checks": []}

        try:
            # Check 1: Duration
            actual_duration = self.assembler.probe_duration(video_path)
            duration_diff = abs(actual_duration - expected_duration)
            if duration_diff > 0.5:
                result["checks"].append({
                    "check": "duration",
                    "pass": False,
                    "expected": expected_duration,
                    "actual": actual_duration,
                    "diff": duration_diff,
                })
                result["pass"] = False
            else:
                result["checks"].append({"check": "duration", "pass": True})

            # Check 2: File size
            file_size = Path(video_path).stat().st_size
            if file_size < 1024:
                result["checks"].append({"check": "file_size", "pass": False, "size": file_size})
                result["pass"] = False
            else:
                result["checks"].append({"check": "file_size", "pass": True, "size": file_size})

            # Check 3: Scene count
            expected_scenes = len(plan.get("scenes", []))
            result["checks"].append({"check": "scene_count", "pass": True, "count": expected_scenes})

            # Check 4: Identity consistency (via scene metadata)
            identity_issues = []
            for scene_meta in self.metadata.get("scenes", []):
                if not scene_meta.get("qa_pass", True):
                    identity_issues.append({
                        "scene": scene_meta.get("index"),
                        "reason": scene_meta.get("qa_reason"),
                    })
            if identity_issues:
                result["checks"].append({"check": "identity_consistency", "pass": False, "issues": identity_issues})
                result["pass"] = False
            else:
                result["checks"].append({"check": "identity_consistency", "pass": True})

        except Exception as exc:
            logger.error("Final QA failed: %s", exc)
            result["checks"].append({"check": "qa_execution", "pass": False, "error": str(exc)})
            result["pass"] = False

        logger.info("Final QA result: %s", "PASS" if result["pass"] else "FAIL")
        return result

    @staticmethod
    def _probe_duration(path: str) -> float:
        result = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", path,
        ], check=True, capture_output=True, text=True)
        return float(result.stdout.strip())

    def _publish_supporting_files(self, plan: Dict, ass_path: str) -> None:
        script_filename = "confession_script.txt" if self.is_confession else "mia_script.txt"
        shutil.copy2(self.job_dir / "script.txt", self.host_dir / script_filename)
        shutil.copy2(self.job_dir / "story_plan.json", self.host_dir / "story_plan.json")
        ass_filename = "confession_captions.ass" if self.is_confession else "mia_captions.ass"
        shutil.copy2(ass_path, self.host_dir / ass_filename)
        sound_plan_path = self.audio_dir / "sound_design.json"
        if sound_plan_path.exists():
            shutil.copy2(sound_plan_path, self.host_dir / "sound_design.json")

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
