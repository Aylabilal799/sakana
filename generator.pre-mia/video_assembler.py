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
        narration_durations = self._normalize_durations(scene_durations, len(scene_paths), audio_duration)

        # Each non-final clip gets transition_duration extra material. Crossfade overlap then
        # reduces the final visual duration back to exactly the narration duration.
        render_durations = [
            duration + (transition_duration if index < len(scene_paths) - 1 else 0.0)
            for index, duration in enumerate(narration_durations)
        ]

        normalized: List[str] = []
        for index, (source, duration) in enumerate(zip(scene_paths, render_durations)):
            path = str(work_dir / f"scene_{index:02d}.mp4")
            drift_x = "(in_w-out_w)/2+((in_w-out_w)/2)*0.18*sin(n/75)"
            drift_y = "(in_h-out_h)/2+((in_h-out_h)/2)*0.12*cos(n/90)"
            grade = self._grade_filter(tone)
            video_filter = (
                f"scale={self.width + 64}:{self.height + 114}:force_original_aspect_ratio=increase,"
                f"crop={self.width}:{self.height}:x='{drift_x}':y='{drift_y}',"
                f"{grade},fps={self.fps},setsar=1,format=yuv420p,"
                f"tpad=stop_mode=clone:stop_duration={max(0.0, duration):.3f},"
                f"trim=duration={duration:.3f},setpts=PTS-STARTPTS"
            )
            self._run([
                "ffmpeg", "-y", "-i", source,
                "-vf", video_filter,
                "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "21",
                "-r", str(self.fps), "-pix_fmt", "yuv420p", path,
            ], f"normalize scene {index + 1}")
            normalized.append(path)
            logger.info("Normalized full-frame scene %d/%d: %s", index + 1, len(scene_paths), path)

        visual_path = str(work_dir / "visual.mp4")
        if len(normalized) == 1:
            self._run([
                "ffmpeg", "-y", "-i", normalized[0], "-t", f"{audio_duration:.3f}",
                "-an", "-c:v", "copy", visual_path,
            ], "prepare single scene")
        else:
            inputs: List[str] = []
            for path in normalized:
                inputs.extend(["-i", path])
            chains: List[str] = []
            cumulative = render_durations[0]
            previous = "[0:v]"
            for index in range(1, len(normalized)):
                output_label = f"[xf{index}]"
                offset = max(0.0, cumulative - transition_duration)
                chains.append(
                    f"{previous}[{index}:v]xfade=transition=fade:duration={transition_duration:.3f}:"
                    f"offset={offset:.3f}{output_label}"
                )
                previous = output_label
                cumulative += render_durations[index] - transition_duration
            self._run([
                "ffmpeg", "-y", *inputs,
                "-filter_complex", ";".join(chains),
                "-map", previous,
                "-t", f"{audio_duration:.3f}",
                "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "21",
                "-r", str(self.fps), "-pix_fmt", "yuv420p", visual_path,
            ], "crossfade scenes")

        escaped_ass = self._escape_filter_path(str(Path(ass_path).resolve()))
        self._run([
            "ffmpeg", "-y", "-i", visual_path, "-i", audio_path,
            "-filter_complex", f"[0:v]ass=filename='{escaped_ass}'[v]",
            "-map", "[v]", "-map", "1:a:0",
            "-t", f"{audio_duration:.3f}",
            "-c:v", "libx264", "-preset", "medium", "-crf", "21",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-r", str(self.fps), "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", "-metadata", "title=Mia Daily Vlog",
            str(destination),
        ], "burn captions and mux narration")

        final_duration = self.probe_duration(str(destination))
        if abs(final_duration - audio_duration) > 0.15:
            raise RuntimeError(
                f"Audio/video sync validation failed: audio={audio_duration:.3f}s video={final_duration:.3f}s"
            )
        logger.info("Final Mia video: %s (%.3fs; audio %.3fs)", destination, final_duration, audio_duration)
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
            subprocess.run(command, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            logger.error("FFmpeg failed during %s: %s", stage, exc.stderr[-4000:])
            raise RuntimeError(f"FFmpeg failed during {stage}: {exc.stderr[-1000:]}") from exc
