import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image

logger = logging.getLogger(__name__)


class VisualQA:
    """Basic visual quality checks for generated images before they enter the video."""

    MAX_RETRIES = int(os.getenv("MAX_SCENE_RETRIES", "3"))

    # Minimum image dimensions
    MIN_WIDTH = 512
    MIN_HEIGHT = 768

    def __init__(self, character_manager=None):
        self.character = character_manager
        self.failure_log: List[Dict] = []

    def validate_image(self, image_path: str, scene_index: int,
                       expected_objects: Optional[List[str]] = None) -> Tuple[bool, str]:
        """Run visual QA on a generated scene keyframe. Returns (pass, reason)."""
        path = Path(image_path)
        if not path.exists():
            return False, f"Image file not found: {image_path}"

        try:
            with Image.open(path) as img:
                width, height = img.size
                format_type = img.format
                mode = img.mode
        except Exception as exc:
            return False, f"Cannot open image: {exc}"

        # Check 1: Image dimensions
        if width < self.MIN_WIDTH or height < self.MIN_HEIGHT:
            return False, f"Image too small: {width}x{height}"

        # Check 2: Aspect ratio (must be roughly 9:16 for vertical)
        aspect = width / height
        if aspect < 0.4 or aspect > 0.7:
            return False, f"Incorrect aspect ratio: {aspect:.3f} (expected ~0.5625 for 9:16)"

        # Check 3: File size (corruption check)
        file_size = path.stat().st_size
        if file_size < 1024:
            return False, f"Image file suspiciously small: {file_size} bytes"

        # Check 4: Mode check
        if mode not in ("RGB", "RGBA", "L"):
            return False, f"Unsupported image mode: {mode}"

        # Check 5: Black/blank image detection
        try:
            with Image.open(path) as img:
                img_small = img.resize((50, 50))
                pixels = list(img_small.getdata())
                # Check if image is mostly one color (likely blank/corrupted)
                if len(pixels) > 0:
                    if isinstance(pixels[0], tuple):
                        avg_r = sum(p[0] for p in pixels) / len(pixels)
                        avg_g = sum(p[1] for p in pixels) / len(pixels)
                        avg_b = sum(p[2] for p in pixels) / len(pixels)
                    else:
                        avg_r = avg_g = avg_b = sum(pixels) / len(pixels)
                    # If image is almost pure black or pure white
                    avg_brightness = (avg_r + avg_g + avg_b) / 3
                    if avg_brightness < 8:
                        return False, "Image is almost completely black"
                    if avg_brightness > 247:
                        return False, "Image is almost completely white"
        except Exception as exc:
            logger.warning("Brightness check failed for %s: %s", path, exc)

        logger.info("Visual QA passed for scene %d: %s (%dx%d, %s, %.1fKB)",
                     scene_index, path.name, width, height, format_type, file_size/1024)
        return True, "passed"

    def validate_with_retry(self, generate_fn, image_path: str, scene_index: int,
                           expected_objects: Optional[List[str]] = None) -> str:
        """Validate an image, retry generation if it fails."""
        for attempt in range(1, self.MAX_RETRIES + 1):
            success, reason = self.validate_image(image_path, scene_index, expected_objects)
            if success:
                return image_path

            logger.warning("Visual QA failed for scene %d (attempt %d/%d): %s",
                           scene_index, attempt, self.MAX_RETRIES, reason)
            self.failure_log.append({
                "scene": scene_index,
                "attempt": attempt,
                "path": image_path,
                "reason": reason,
            })

            if attempt < self.MAX_RETRIES:
                logger.info("Regenerating scene %d (attempt %d)...", scene_index, attempt + 1)
                try:
                    image_path = generate_fn()
                except Exception as exc:
                    logger.error("Regeneration failed for scene %d: %s", scene_index, exc)
                    break
            else:
                logger.error("Visual QA failed for scene %d after %d attempts. Using last attempt.",
                             scene_index, self.MAX_RETRIES)

        return image_path

    def get_failure_report(self) -> List[Dict]:
        return list(self.failure_log)
