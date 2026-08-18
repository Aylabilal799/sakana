import logging
import subprocess
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


class VideoAssembler:
    def __init__(self, width: int = 1080, height: int = 1920, fps: int = 24):
        self.width = width
        self.height = height
        self.fps = fps

    def assemble(
        self,
        scene_paths: List[str],
        audio_path: str,
        ass_path: str,
        output_path: str,
        scene_durations: Optional[List[float]] = None,
        transition_duration: float = 0.35,
        tone: str = "warm natural",
    ) -> str:
        if not scene_paths:
            raise ValueError("No scene videos were supplied")
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        work_dir = destination.parent / ".assembly"
        work_dir.mkdir(parents=True, exist_ok=True)

        audio_duration = self.probe_duration(audio_path)
        logger.info("Audio duration: %.3fs", audio_duration)

        narration_durations = self._normalize_durations(scene_durations, len(scene_paths), audio_duration)
        logger.info("Scene narration durations: %s", narration_durations)

        normalized: List[str] = []
        for index, (source, duration) in enumerate(zip(scene_paths, narration_durations)):
            path = str(work_dir / f"scene_{index:02d}.mp4")
            src_dur = self.probe_duration(source)
            logger.info("Scene %d source duration: %.3fs, target: %.3fs", index, src_dur, duration)

            drift_x = "(in_w-out_w)/2+((in_w-out_w)/2)*0.18*sin(n/75)"
            drift_y = "(in_h-out_h)/2+((in_h-out_h)/2)*0.12*cos(n/90)"
            grade = self._grade_filter(tone)

            filters = [
                f"scale={self.width + 64}:{self.height + 114}:force_original_aspect_ratio=increase",
                f"crop={self.width}:{self.height}:x='{drift_x}':y='{drift_y}'",
                grade,
                f"fps={self.fps}",
                "setsar=1",
                "format=yuv420p",
            ]

            if src_dur < duration:
                pad_dur = duration - src_dur
                filters.append(f"tpad=stop_mode=clone:stop_duration={pad_dur:.3f}")

            filters.append(f"trim=duration={duration:.3f}")
            filters.append("setpts=PTS-STARTPTS")

            self._run([
                "ffmpeg", "-y", "-i", source,
                "-vf", ",".join(filters),
                "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "21",
                "-r", str(self.fps), "-pix_fmt", "yuv420p", path,
            ], f"normalize scene {index + 1}")

            out_dur = self.probe_duration(path)
            logger.info("Scene %d normalized duration: %.3fs", index, out_dur)
            normalized.append(path)

        # Concat demuxer — bulletproof, no broken xfade chains
        concat_list = work_dir / "concat.txt"
        with open(concat_list, "w") as f:
            for path in normalized:
                escaped = path.replace("\\", "/")
                f.write(f"file '{escaped}'\n")

        visual_path = str(work_dir / "visual.mp4")
        self._run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(concat_list),
            "-c", "copy",
            "-r", str(self.fps),
            visual_path,
        ], "concatenate scenes")

        visual_dur = self.probe_duration(visual_path)
        logger.info("Concatenated visual duration: %.3fs", visual_dur)

        # Safety pad if concat is somehow shorter than audio
        if visual_dur < audio_duration - 0.5:
            logger.warning("Visual (%.3fs) shorter than audio (%.3fs), padding with freeze frame", visual_dur, audio_duration)
            padded_visual = str(work_dir / "visual_padded.mp4")
            self._run([
                "ffmpeg", "-y", "-i", visual_path,
                "-vf", f"tpad=stop_mode=clone:stop_duration={audio_duration - visual_dur:.3f}",
                "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "21",
                "-r", str(self.fps), "-pix_fmt", "yuv420p",
                padded_visual,
            ], "pad visual to match audio")
            visual_path = padded_visual
            visual_dur = self.probe_duration(visual_path)
            logger.info("Padded visual duration: %.3fs", visual_dur)

        escaped_ass = self._escape_filter_path(str(Path(ass_path).resolve()))
        self._run([
            "ffmpeg", "-y", "-i", visual_path, "-i", audio_path,
            "-filter_complex", f"[0:v]ass=filename='{escaped_ass}'[v]",
            "-map", "[v]", "-map", "1:a:0",
            "-shortest",
            "-c:v", "libx264", "-preset", "medium", "-crf", "21",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-r", str(self.fps), "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", "-metadata", "title=Mia Daily Vlog",
            str(destination),
        ], "burn captions and mux narration")

        final_duration = self.probe_duration(str(destination))
        logger.info("Final video duration: %.3fs (audio: %.3fs)", final_duration, audio_duration)

        if abs(final_duration - audio_duration) > 1.0:
            raise RuntimeError(
                f"Audio/video sync validation failed: audio={audio_duration:.3f}s video={final_duration:.3f}s"
            )

        return str(destination)

    def probe_duration(self, path: str) -> float:
        result = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", path,
        ], check=True, capture_output=True, text=True)
        return float(result.stdout.strip())

    @staticmethod
    def _normalize_durations(values, count: int, target: float) -> List[float]:
        if values and len(values) == count and sum(values) > 0:
            durations = [max(0.6, float(value)) for value in values]
        else:
            durations = [target / count] * count
        scale = target / sum(durations)
        return [value * scale for value in durations]

    @staticmethod
    def _grade_filter(tone: str) -> str:
        value = str(tone or "").lower()
        if "dark" in value or "horror" in value:
            return "eq=contrast=1.08:brightness=-0.025:saturation=0.84"
        if "cool" in value or "suspense" in value or "mystery" in value:
            return "eq=contrast=1.05:brightness=-0.008:saturation=0.93"
        return "eq=contrast=1.025:brightness=0.006:saturation=1.035"

    @staticmethod
    def _escape_filter_path(path: str) -> str:
        return path.replace("\\", "/").replace(":", r"\:").replace("'", r"\'")

    @staticmethod
    def _run(command: List[str], stage: str) -> None:
        try:
            result = subprocess.run(command, check=True, capture_output=True, text=True)
            if result.stderr:
                logger.debug("FFmpeg stderr for %s: %s", stage, result.stderr[-500:])
        except subprocess.CalledProcessError as exc:
            logger.error("FFmpeg failed during %s: %s", stage, exc.stderr[-4000:])
            raise RuntimeError(f"FFmpeg failed during {stage}: {exc.stderr[-1000:]}") from exc
