import json
import logging
import re
from typing import Dict, List

from generator.agnes_client import AgnesClient

logger = logging.getLogger(__name__)


class StoryPlanner:
    """Turn a short request or supplied script into a coherent first-person Mia vlog plan."""

    def __init__(self, agnes: AgnesClient):
        self.agnes = agnes

    def plan(self, user_prompt: str) -> Dict:
        prompt = user_prompt.strip()
        if not prompt:
            raise ValueError("The Mia prompt cannot be empty")
        instruction = f"""
Create one short-form vertical daily-vlog episode starring Mia, the same recurring adult female influencer.
The user's request is:

{prompt}

Return ONLY valid JSON with this shape:
{{
  "title": "short episode title",
  "genre": "daily_vlog|travel|mystery|horror|reaction|story",
  "tone": "warm natural|cool suspense|dark atmospheric",
  "outfit": "one concise continuity outfit description",
  "script": "35-55 second first-person narration/dialogue spoken by Mia",
  "scenes": [
    {{
      "narration": "exact contiguous portion of the script used in this scene",
      "location": "specific location",
      "action": "what Mia physically does",
      "shot_type": "selfie|handheld medium|POV|establishing|close-up|third-person",
      "visual_prompt": "specific visual beat featuring Mia when appropriate",
      "camera_motion": "subtle push-in|slow pull-out|gentle handheld drift|slow pan",
      "lighting": "cohesive lighting for the episode",
      "expression": "Mia's natural expression",
      "transition": "crossfade|cut"
    }}
  ]
}}

Rules:
- Mia is the protagonist, not a generic narrator.
- Write natural first-person creator speech, not literary exposition.
- Use 4-7 logical scenes based on actions, locations, camera changes, emotional beats and reveals—not character count.
- Mix selfie, POV, environment and third-person shots, but keep Mia recognizable whenever she is visible.
- Keep one outfit unless the story explicitly and logically changes time/day.
- Make every scene visually actionable and preserve story continuity.
- The concatenation of scene narration must cover the complete script in order.
- Avoid copyrighted characters, brands, on-screen text and extra lookalike women.
"""
        raw = self.agnes.chat(
            instruction,
            max_tokens=3500,
            temperature=0.75,
            system_prompt="You are a JSON-only short-form video writer and shot-list director.",
        )
        data = self._parse_json(raw)
        return self._validate(data, prompt)

    @staticmethod
    def _parse_json(raw: str) -> Dict:
        text = raw.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise RuntimeError("Story planner did not return a JSON object")
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError as exc:
            logger.error("Invalid story JSON: %s", text[:1500])
            raise RuntimeError(f"Story planner returned invalid JSON: {exc}") from exc

    def _validate(self, data: Dict, original_prompt: str) -> Dict:
        script = str(data.get("script") or "").strip()
        scenes = data.get("scenes")
        if not script or not isinstance(scenes, list) or not scenes:
            raise RuntimeError("Story plan is missing script or scenes")
        scenes = scenes[:7]
        if len(scenes) < 3:
            scenes = self._fallback_scenes(script)

        cleaned: List[Dict] = []
        for index, scene in enumerate(scenes, 1):
            if not isinstance(scene, dict):
                continue
            narration = str(scene.get("narration") or "").strip()
            cleaned.append({
                "index": index,
                "narration": narration,
                "location": str(scene.get("location") or "the current vlog location").strip(),
                "action": str(scene.get("action") or narration or "Mia records herself").strip(),
                "shot_type": str(scene.get("shot_type") or "handheld medium vlog shot").strip(),
                "visual_prompt": str(scene.get("visual_prompt") or scene.get("action") or narration).strip(),
                "camera_motion": str(scene.get("camera_motion") or "subtle handheld push-in").strip(),
                "lighting": str(scene.get("lighting") or self._default_lighting(data.get("tone"))).strip(),
                "expression": str(scene.get("expression") or "natural and emotionally appropriate").strip(),
                "transition": "cut" if str(scene.get("transition", "")).lower() == "cut" else "crossfade",
            })
        if not cleaned:
            cleaned = self._fallback_scenes(script)
        if not any(s["narration"] for s in cleaned):
            cleaned = self._fallback_scenes(script)
        scene_script = " ".join(scene["narration"] for scene in cleaned if scene["narration"]).strip()
        if scene_script:
            script = scene_script

        return {
            "title": str(data.get("title") or "Mia's Daily Vlog").strip()[:100],
            "genre": str(data.get("genre") or "daily_vlog").strip().lower(),
            "tone": str(data.get("tone") or "warm natural").strip(),
            "outfit": str(data.get("outfit") or "cream fitted top and high-waisted blue jeans").strip(),
            "script": script,
            "scenes": cleaned,
            "source_prompt": original_prompt,
        }

    @staticmethod
    def _default_lighting(tone) -> str:
        tone = str(tone or "").lower()
        if "dark" in tone or "horror" in tone:
            return "dark cinematic practical light with controlled shadows"
        if "cool" in tone or "suspense" in tone:
            return "slightly cool realistic suspense lighting"
        return "natural warm realistic daylight"

    def _fallback_scenes(self, script: str) -> List[Dict]:
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", script) if s.strip()]
        count = min(6, max(3, len(sentences)))
        groups = [[] for _ in range(count)]
        for i, sentence in enumerate(sentences):
            groups[min(i * count // max(len(sentences), 1), count - 1)].append(sentence)
        shots = ["selfie close-up", "establishing shot", "handheld medium shot", "POV shot", "reaction close-up", "third-person wide shot"]
        return [{
            "index": i + 1,
            "narration": " ".join(group),
            "location": "the story's current location",
            "action": "Mia acts out this story beat while recording her vlog",
            "shot_type": shots[i % len(shots)],
            "visual_prompt": " ".join(group),
            "camera_motion": "subtle handheld push-in",
            "lighting": "natural cohesive cinematic lighting",
            "expression": "natural and emotionally appropriate",
            "transition": "crossfade" if i else "cut",
        } for i, group in enumerate(groups) if group]
