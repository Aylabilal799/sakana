import json
import logging
import os
import shutil
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import quote

logger = logging.getLogger(__name__)


DEFAULT_MIA_CONFIG = {
    "name": "Mia",
    "role": "AI female influencer and daily vlogger",
    "age_appearance": "24-year-old adult woman",
    "identity": (
        "oval face with softly defined cheekbones, warm hazel almond-shaped eyes, "
        "straight petite nose, naturally full lips, light warm olive skin with subtle freckles, "
        "long dark-chestnut wavy hair parted slightly left"
    ),
    "body": "slim natural build with realistic adult proportions",
    "default_outfit": (
        "cream fitted ribbed top, high-waisted blue jeans, small gold hoop earrings, "
        "delicate gold pendant necklace"
    ),
    "prompt_prefix": (
        "Mia, the exact same 24-year-old adult woman, "
        "oval face, softly defined cheekbones, warm hazel almond-shaped eyes, straight petite nose, "
        "naturally full lips, light warm olive skin with subtle freckles, long dark-chestnut wavy hair "
        "parted slightly left, slim natural build"
    ),
    "style": (
        "photorealistic modern social-media creator aesthetic, authentic phone-camera detail, "
        "natural skin texture, realistic anatomy, cinematic but believable"
    ),
    "negative_prompt": (
        "different woman, changed identity, changed face, changed ethnicity, changed age, altered eye color, "
        "altered hair color, face morphing, duplicate person, twins, multiple Mia characters, plastic skin, "
        "deformed hands, extra fingers, distorted face, text, watermark, logo, black bars, letterbox"
    ),
    "voice": "af_bella",
    "reference_image": "/root/sakana/characters/mia/reference_image.png",
    "video_mode": "ti2vid",
    "scene_image_strategy": "text_identity",
}


class CharacterManager:
    def __init__(self, character_dir: Optional[str] = None):
        project_dir = Path(os.getenv("PROJECT_DIRECTORY", "/root/sakana"))
        self.character_dir = Path(
            character_dir
            or os.getenv("MIA_CHARACTER_DIRECTORY", str(project_dir / "characters" / "mia"))
        )
        self.config_path = self.character_dir / "config.json"
        self.reference_image_path = self.character_dir / "reference_image.png"
        self.hosted_root = Path(os.getenv("OUTPUT_DIRECTORY", "/var/www/agnes-videos"))
        self.public_base = os.getenv("VIDEO_HOST_URL", "http://localhost:6464/videos").rstrip("/")
        self.config = self._load_config()

    def _load_config(self) -> Dict:
        if self.config_path.exists():
            with self.config_path.open("r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            merged = dict(DEFAULT_MIA_CONFIG)
            merged.update(loaded)
            return merged
        self.character_dir.mkdir(parents=True, exist_ok=True)
        self.save_config(DEFAULT_MIA_CONFIG)
        return dict(DEFAULT_MIA_CONFIG)

    def save_config(self, config: Optional[Dict] = None) -> None:
        if config is not None:
            self.config = dict(config)
        self.character_dir.mkdir(parents=True, exist_ok=True)
        self.config["name"] = "Mia"
        self.config["reference_image"] = str(self.reference_image_path)
        with self.config_path.open("w", encoding="utf-8") as handle:
            json.dump(self.config, handle, indent=2, ensure_ascii=False)

    def has_reference_image(self) -> bool:
        return self.reference_image_path.is_file() and self.reference_image_path.stat().st_size > 0

    def get_reference_image_path(self) -> Optional[str]:
        return str(self.reference_image_path) if self.has_reference_image() else None

    def set_reference_image(self, image_path: str) -> str:
        source = Path(image_path)
        self.character_dir.mkdir(parents=True, exist_ok=True)
        if source.resolve() != self.reference_image_path.resolve():
            shutil.copy2(source, self.reference_image_path)
        self.config["reference_image"] = str(self.reference_image_path)
        self.save_config()
        self.publish_reference()
        return str(self.reference_image_path)

    def publish_reference(self) -> str:
        if not self.has_reference_image():
            raise FileNotFoundError("Mia reference image has not been created")
        public_dir = self.hosted_root / "characters" / "mia"
        public_dir.mkdir(parents=True, exist_ok=True)
        public_path = public_dir / "reference_image.png"
        shutil.copy2(self.reference_image_path, public_path)
        public_dir.chmod(0o755)
        public_path.chmod(0o644)
        return self.get_reference_image_url()

    def get_reference_image_url(self) -> str:
        return f"{self.public_base}/characters/mia/{quote('reference_image.png')}"

    def reference_generation_prompt(self) -> str:
        return (
            f"Create the canonical identity reference portrait for {self.config['prompt_prefix']}. "
            f"She wears {self.config['default_outfit']}. Waist-up portrait, directly facing camera, "
            "neutral friendly expression, both eyes clearly visible, soft daylight, plain warm-gray studio "
            f"background, no props, no other people. {self.config['style']}. This image defines her permanent identity."
        )

    def scene_keyframe_prompt(self, scene: Dict, scene_state: Optional[Dict] = None) -> str:
        outfit = self.config.get("default_outfit", "")
        if scene_state:
            outfit = scene_state.get("outfit") or outfit

        shot = scene.get("shot_type", "handheld medium vlog shot")
        lighting = scene.get("lighting", "natural warm realistic light")
        visual = scene.get("visual_prompt") or scene.get("narration", "Mia records her daily vlog")
        expression = scene.get("expression", "natural emotionally appropriate expression")
        location = scene.get("location", "the current location")
        emotional_state = scene.get("emotional_state", "curious")

        # Build object description
        objects_desc = ""
        objects_visible = scene.get("objects_visible", [])
        objects_held = scene.get("objects_held", [])
        if objects_visible or objects_held:
            obj_parts = []
            for obj_name in objects_visible:
                obj_parts.append(f"{obj_name} visible in the scene")
            for obj_name in objects_held:
                obj_parts.append(f"Mia holding {obj_name}")
            if obj_parts:
                objects_desc = "Objects: " + ", ".join(obj_parts) + ". "

        # Prefer medium shots over extreme close-ups
        if "extreme" in shot.lower() or "macro" in shot.lower():
            shot = "medium close-up"

        # Full identity description repeated in every scene prompt
        return (
            f"{self.config['prompt_prefix']}. "
            f"She wears {outfit}. "
            f"Scene: {visual}. Location: {location}. "
            f"Shot type: {shot}. Expression: {expression}. Emotional state: {emotional_state}. "
            f"{objects_desc}"
            f"Lighting: {lighting}. {self.config['style']}. "
            "Vertical 9:16 composition, fill the entire frame, no borders, no black bars, one Mia only. "
            "Maintain exact same face, eyes, nose, lips, freckles, skin tone, hair color and age across every scene. "
            "Do not redesign, beautify, age, or replace her face. "
            "Do not change her ethnicity, eye color, or hair color. "
            "Do not introduce additional women or duplicate Mias."
        )

    def video_motion_prompt(self, scene: Dict, scene_state: Optional[Dict] = None) -> str:
        motion = scene.get("camera_motion", "subtle handheld push-in")
        action = scene.get("action") or scene.get("visual_prompt") or scene.get("narration", "")
        location = scene.get("location", "the current location")
        emotional_state = scene.get("emotional_state", "curious")

        objects_desc = ""
        objects_held = scene.get("objects_held", [])
        if objects_held:
            objects_desc = f"Mia is holding: {', '.join(objects_held)}. "

        return (
            f"Animate this exact image of Mia at {location}. {action}. {objects_desc}"
            f"Camera movement: {motion}. Emotional state: {emotional_state}. "
            "Natural blinking, breathing, subtle hair and clothing movement, realistic influencer vlog behavior. "
            "Keep Mia's face, body, outfit and identity stable in every frame. Avoid face morphing, sudden pose changes, "
            "rubber motion or new people entering. Photorealistic vertical social video, full-frame 9:16."
        )

    def get_character_prompt(self, scene_description: str = "") -> str:
        return (
            f"{self.config['prompt_prefix']}, {scene_description}, {self.config['style']}, "
            "same exact Mia identity, one adult woman only"
        )

    def get_negative_prompt(self) -> str:
        return self.config.get("negative_prompt", DEFAULT_MIA_CONFIG["negative_prompt"])

    def get_summary(self) -> Dict:
        return {
            "name": "Mia",
            "has_reference_image": self.has_reference_image(),
            "reference_url": self.get_reference_image_url() if self.has_reference_image() else None,
            "voice": self.config.get("voice", "af_bella"),
            "style": self.config.get("style", ""),
        }
