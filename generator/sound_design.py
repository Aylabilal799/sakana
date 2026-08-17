import json
import logging
import os
import random
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class SoundDesigner:
    """Generate sound design plans and mix SFX with narration."""

    # Local SFX library paths (user must populate these)
    SFX_BASE = Path(os.getenv("PROJECT_DIRECTORY", "/root/sakana")) / "assets" / "sfx"

    # Fallback: generate descriptions for what SFX should be
    AMBIENCE_MAP = {
        "abandoned hotel": ["abandoned_building_ambience", "room_tone_subtle", "distant_wind"],
        "hotel": ["hotel_ambience", "room_tone"],
        "house": ["house_ambience", "room_tone"],
        "street": ["city_street_ambience", "distant_traffic"],
        "forest": ["forest_ambience", "wind_trees"],
        "basement": ["basement_ambience", "hum_electrical"],
        "room": ["room_tone"],
    }

    EFFECT_MAP = {
        "photo": ["paper_rustle", "photo_handle"],
        "photograph": ["paper_rustle", "photo_handle"],
        "paper": ["paper_rustle"],
        "letter": ["paper_rustle", "envelope_open"],
        "door": ["door_creak_light", "door_handle"],
        "footstep": ["footstep_wood_light"],
        "walk": ["footstep_wood_light"],
        "key": ["keys_jingle"],
        "phone": ["phone_tap_light"],
        "drawer": ["drawer_open"],
        "realize": ["low_impact_subtle"],
        "shock": ["low_impact_subtle", "tension_hit_soft"],
        "discover": ["subtle_reveal_sound"],
        "open": ["door_creak_light", "drawer_open"],
        "close": ["door_close_soft"],
        "gasp": ["subtle_tension_rise"],
    }

    def __init__(self, job_dir: Path):
        self.job_dir = Path(job_dir)
        self.audio_dir = self.job_dir / "audio"
        self.sfx_dir = self.audio_dir / "sfx"
        self.sfx_dir.mkdir(parents=True, exist_ok=True)
        self.design_plan: List[Dict] = []

    def generate_sound_plan(self, scenes: List[Dict], script: str) -> List[Dict]:
        """Generate a sound design plan for each scene based on story content."""
        plan = []
        script_lower = script.lower()

        for scene in scenes:
            scene_plan = {
                "scene_index": scene.get("index", 0),
                "location": scene.get("location", ""),
                "ambience": [],
                "effects": [],
            }

            # Determine ambience from location
            location_lower = str(scene.get("location", "")).lower()
            for loc_key, sounds in self.AMBIENCE_MAP.items():
                if loc_key in location_lower:
                    scene_plan["ambience"].extend(sounds)
                    break
            if not scene_plan["ambience"]:
                scene_plan["ambience"] = ["room_tone_subtle"]

            # Determine effects from objects and actions
            narration_lower = str(scene.get("narration", "")).lower()
            action_lower = str(scene.get("action", "")).lower()
            combined = narration_lower + " " + action_lower

            # Check for object-related sounds
            for keyword, sounds in self.EFFECT_MAP.items():
                if keyword in combined:
                    for sound in sounds:
                        if sound not in [e["type"] for e in scene_plan["effects"]]:
                            scene_plan["effects"].append({
                                "type": sound,
                                "trigger": keyword,
                                "volume": 0.15,
                            })

            # Emotional state sounds
            emotion = str(scene.get("emotional_state", "")).lower()
            if emotion in ("shocked", "frightened", "terrified"):
                scene_plan["effects"].append({
                    "type": "low_impact_subtle",
                    "trigger": "emotional_peak",
                    "volume": 0.20,
                })
            elif emotion in ("suspicious", "uneasy", "nervous"):
                scene_plan["effects"].append({
                    "type": "subtle_tension_rise",
                    "trigger": "emotional_build",
                    "volume": 0.10,
                })

            # Deduplicate effects
            seen = set()
            unique_effects = []
            for eff in scene_plan["effects"]:
                if eff["type"] not in seen:
                    seen.add(eff["type"])
                    unique_effects.append(eff)
            scene_plan["effects"] = unique_effects

            plan.append(scene_plan)

        self.design_plan = plan
        # Save plan
        plan_path = self.audio_dir / "sound_design.json"
        with open(plan_path, "w", encoding="utf-8") as f:
            json.dump(plan, f, indent=2, ensure_ascii=False)
        logger.info("Sound design plan generated: %d scenes", len(plan))
        return plan

    def find_sfx_file(self, sound_type: str) -> Optional[Path]:
        """Find a local SFX file for the given sound type."""
        # Search all sfx subdirectories
        if self.SFX_BASE.exists():
            for subdir in self.SFX_BASE.iterdir():
                if subdir.is_dir():
                    # Look for files containing the sound_type
                    for ext in (".wav", ".mp3", ".ogg", ".flac"):
                        candidate = subdir / f"{sound_type}{ext}"
                        if candidate.exists():
                            return candidate
                        # Also try partial match
                        for f in subdir.glob(f"*{sound_type}*{ext}"):
                            return f
        return None

    def generate_silence(self, duration: float, output_path: str) -> str:
        """Generate a silent WAV file of given duration."""
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
            "-t", str(duration), "-acodec", "pcm_s16le", "-ar", "48000", "-ac", "1",
            output_path,
        ], check=True, capture_output=True)
        return output_path

    def build_scene_ambience_track(self, scene_plan: Dict, duration: float,
                                   output_path: str) -> str:
        """Build an ambience track for a scene."""
        # Start with silence
        silence_path = str(self.sfx_dir / f"scene_{scene_plan['scene_index']:02d}_silence.wav")
        self.generate_silence(duration, silence_path)

        ambience_files = []
        for amb in scene_plan.get("ambience", []):
            sfx = self.find_sfx_file(amb)
            if sfx:
                ambience_files.append(str(sfx))

        if not ambience_files:
            shutil.copy2(silence_path, output_path)
            return output_path

        # Mix ambience files at low volume
        inputs = []
        for f in ambience_files:
            inputs.extend(["-i", f])

        # Create filter complex to loop and mix ambience
        filter_parts = []
        for i in range(len(ambience_files)):
            filter_parts.append(
                f"[{i}:a]aloop=loop=-1:size=10s,atrim=0:{duration},volume=0.08[a{i}]"
            )
        mix_inputs = "".join(f"[a{i}]" for i in range(len(ambience_files)))
        filter_parts.append(f"{mix_inputs}amix=inputs={len(ambience_files)}:duration=longest[outa]")

        subprocess.run([
            "ffmpeg", "-y", *inputs,
            "-filter_complex", ";".join(filter_parts),
            "-map", "[outa]",
            "-t", str(duration),
            "-acodec", "pcm_s16le", "-ar", "48000", "-ac", "1",
            output_path,
        ], check=True, capture_output=True)

        return output_path

    def mix_final_audio(self, narration_path: str, scene_durations: List[float],
                        output_path: str) -> str:
        """Mix narration with scene ambience."""
        if not self.design_plan or not scene_durations:
            # No sound design, just copy narration
            shutil.copy2(narration_path, output_path)
            return output_path

        # Build per-scene ambience tracks and concatenate
        scene_ambiences = []
        for i, (plan, duration) in enumerate(zip(self.design_plan, scene_durations)):
            amb_path = str(self.sfx_dir / f"scene_{i+1:02d}_ambience.wav")
            try:
                self.build_scene_ambience_track(plan, duration, amb_path)
                scene_ambiences.append(amb_path)
            except Exception as exc:
                logger.warning("Failed to build ambience for scene %d: %s", i+1, exc)
                # Use silence
                silence_path = str(self.sfx_dir / f"scene_{i+1:02d}_silence.wav")
                self.generate_silence(duration, silence_path)
                scene_ambiences.append(silence_path)

        # Concatenate all ambience tracks
        concat_list = str(self.sfx_dir / "ambience_concat_list.txt")
        with open(concat_list, "w") as f:
            for amb in scene_ambiences:
                f.write(f"file '{Path(amb).resolve()}'\n")

        full_ambience = str(self.sfx_dir / "full_ambience.wav")
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", concat_list,
            "-acodec", "pcm_s16le", "-ar", "48000", "-ac", "1",
            full_ambience,
        ], check=True, capture_output=True)

        # Mix narration (primary) with ambience (ducked underneath)
        subprocess.run([
            "ffmpeg", "-y",
            "-i", narration_path,
            "-i", full_ambience,
            "-filter_complex",
            "[1:a]volume=0.12[amb];[0:a][amb]amix=inputs=2:duration=first:weights='1 0.3'[outa]",
            "-map", "[outa]",
            "-acodec", "pcm_s16le", "-ar", "48000", "-ac", "1",
            output_path,
        ], check=True, capture_output=True)

        logger.info("Final mixed audio: %s", output_path)
        return output_path
