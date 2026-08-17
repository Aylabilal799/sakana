import json
import logging
import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional

from generator.agnes_client import AgnesClient

logger = logging.getLogger(__name__)


class ObjectManager:
    """Track persistent story objects and their visual references across scenes."""

    def __init__(self, job_dir: Path, agnes: AgnesClient):
        self.job_dir = Path(job_dir)
        self.objects_dir = self.job_dir / "references" / "objects"
        self.objects_dir.mkdir(parents=True, exist_ok=True)
        self.agnes = agnes
        self.objects: Dict[str, Dict] = {}
        self._load_state()

    def _state_path(self) -> Path:
        return self.job_dir / "object_state.json"

    def _load_state(self):
        if self._state_path().exists():
            with open(self._state_path(), "r", encoding="utf-8") as f:
                self.objects = json.load(f)

    def _save_state(self):
        with open(self._state_path(), "w", encoding="utf-8") as f:
            json.dump(self.objects, f, indent=2, ensure_ascii=False)

    def register_object(self, obj_id: str, obj_type: str, description: str,
                        introduced_scene: int, owner: str = "Mia") -> Dict:
        """Register a new persistent object. Generate its canonical reference image."""
        if obj_id in self.objects:
            logger.info("Object %s already registered, reusing", obj_id)
            return self.objects[obj_id]

        ref_path = str(self.objects_dir / f"{obj_id}.png")

        # Generate canonical reference image for this object
        try:
            prompt = (
                f"A single isolated {obj_type} on a plain neutral background, product-style photograph, "
                f"{description}, centered, soft even lighting, no people, no text, no logos, "
                "photorealistic, highly detailed, 4K quality"
            )
            image_url = self.agnes.generate_image(prompt, size="1K", ratio="1:1")
            downloaded = self.agnes.download_file(image_url, ref_path)
            ref_path = downloaded
        except Exception as exc:
            logger.warning("Failed to generate object reference for %s: %s", obj_id, exc)
            ref_path = None

        obj = {
            "id": obj_id,
            "type": obj_type,
            "description": description,
            "introduced_scene": introduced_scene,
            "owner": owner,
            "reference_path": ref_path,
            "last_seen_scene": introduced_scene,
            "status": "active",
        }
        self.objects[obj_id] = obj
        self._save_state()
        logger.info("Registered object %s (scene %d): %s", obj_id, introduced_scene, description)
        return obj

    def get_object(self, obj_id: str) -> Optional[Dict]:
        return self.objects.get(obj_id)

    def get_visible_objects(self, scene_index: int, scene_data: Dict) -> List[Dict]:
        """Return objects that should be visible in this scene."""
        visible = []
        # From explicit scene data
        for obj_id in scene_data.get("objects_visible", []):
            obj = self.objects.get(obj_id)
            if obj:
                visible.append(obj)
        # Also include objects held by Mia if not explicitly listed
        for obj_id in scene_data.get("objects_held", []):
            obj = self.objects.get(obj_id)
            if obj and obj not in visible:
                visible.append(obj)
        return visible

    def update_object_state(self, obj_id: str, scene_index: int, status: str = "active",
                           owner: Optional[str] = None):
        if obj_id in self.objects:
            self.objects[obj_id]["last_seen_scene"] = scene_index
            self.objects[obj_id]["status"] = status
            if owner:
                self.objects[obj_id]["owner"] = owner
            self._save_state()

    def build_object_prompt_segment(self, scene_index: int, scene_data: Dict) -> str:
        """Build a prompt segment describing visible objects for image generation."""
        visible = self.get_visible_objects(scene_index, scene_data)
        if not visible:
            return ""
        parts = []
        for obj in visible:
            desc = obj["description"]
            if obj["owner"] == "Mia":
                parts.append(f"Mia holding {desc}")
            else:
                parts.append(f"{desc} visible in the scene")
        return "Objects: " + ", ".join(parts) + ". "

    def list_active_objects(self) -> List[Dict]:
        return [obj for obj in self.objects.values() if obj["status"] == "active"]
