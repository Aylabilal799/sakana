import subprocess, logging
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)

class VideoAssembler:
    def assemble(self, scene_paths: List[str], audio_path: str, ass_path: str, output_path: str) -> str:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        work_dir = Path(output_path).parent

        # Step 1: Normalize all scenes to same format (1080x1920, 24fps, h264)
        normalized = []
        for i, path in enumerate(scene_paths):
            norm_path = str(work_dir / f"norm_{i:02d}.mp4")
            subprocess.run([
                "ffmpeg", "-y", "-i", path,
                "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black",
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-r", "24", "-pix_fmt", "yuv420p", "-an", "-threads", "0",
                norm_path
            ], check=True, capture_output=True)
            normalized.append(norm_path)
            logger.info(f"Normalized scene {i+1}: {norm_path}")

        # Step 2: Build concat filter
        filter_parts = []
        for i in range(len(normalized)):
            filter_parts.append(f"[{i}:v]")
        filter_str = "".join(filter_parts) + f"concat=n={len(normalized)}:v=1:a=0[outv]"

        # Step 3: Concatenate with filter (re-encodes, so formats don't matter)
        inputs = []
        for path in normalized:
            inputs.extend(["-i", path])

        concat_out = str(work_dir / "concat.mp4")
        subprocess.run([
            "ffmpeg", "-y", *inputs,
            "-filter_complex", filter_str,
            "-map", "[outv]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "23",
            "-r", "24", "-pix_fmt", "yuv420p", "-an",
            concat_out
        ], check=True, capture_output=True)
        logger.info(f"Concatenated: {concat_out}")

        # Step 4: Add audio + ASS captions
        subprocess.run([
            "ffmpeg", "-y", "-i", concat_out, "-i", audio_path,
            "-vf", f"ass={ass_path}",
            "-c:v", "libx264", "-preset", "medium", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-r", "24", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-shortest", output_path
        ], check=True, capture_output=True)

        # Cleanup
        for p in normalized:
            Path(p).unlink(missing_ok=True)
        Path(concat_out).unlink(missing_ok=True)

        logger.info(f"Final video: {output_path}")
        return output_path
