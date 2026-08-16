import os, json, logging, shutil
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

class CharacterManager:
    def __init__(self, character_dir=None):
        self.character_dir = character_dir or os.getenv("CHARACTER_DIRECTORY", "/root/sakana/characters/default")
        self.config_path = Path(self.character_dir) / "config.json"
        self.reference_image_path = Path(self.character_dir) / "reference_image.png"
        self.config = self._load_config()

    def _load_config(self):
        if self.config_path.exists():
            with open(self.config_path, "r") as f:
                return json.load(f)
        return self._default_config()

    def _default_config(self):
        return {"name": "Elara",
                "description": "A young woman with long auburn hair, green eyes, wearing a dark blue cloak.",
                "prompt_prefix": "A young woman with long auburn hair and green eyes",
                "style": "cinematic realistic",
                "negative_prompt": "multiple people, different person, changed face, inconsistent appearance",
                "video_mode": "ti2vid", "chaining_mode": "keyframes",
                "reference_image": str(self.reference_image_path)}

    def save_config(self):
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w") as f:
            json.dump(self.config, f, indent=2)

    def get_character_prompt(self, scene_description=""):
        prefix, style = self.config.get("prompt_prefix", ""), self.config.get("style", "")
        if scene_description:
            return f"{prefix}, {scene_description}, {style}, consistent character appearance, same face"
        return f"{prefix}, {style}, consistent character appearance"

    def get_negative_prompt(self): return self.config.get("negative_prompt", "")
    def has_reference_image(self): return self.reference_image_path.exists()
    def get_reference_image_path(self): return str(self.reference_image_path) if self.has_reference_image() else None

    def set_reference_image(self, image_path):
        shutil.copy(image_path, self.reference_image_path)
        self.config["reference_image"] = str(self.reference_image_path)
        self.save_config()

    def update_character(self, name=None, description=None, prompt_prefix=None, style=None):
        if name: self.config["name"] = name
        if description: self.config["description"] = description
        if prompt_prefix: self.config["prompt_prefix"] = prompt_prefix
        if style: self.config["style"] = style
        self.save_config()

    def get_summary(self):
        return {"name": self.config.get("name", "Unknown"),
                "has_reference_image": self.has_reference_image(),
                "style": self.config.get("style", ""),
                "video_mode": self.config.get("video_mode", "ti2vid")}
