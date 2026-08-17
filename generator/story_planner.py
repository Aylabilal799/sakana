import json
import logging
import re
from typing import Dict, List, Optional

from generator.agnes_client import AgnesClient

logger = logging.getLogger(__name__)


class StoryPlanner:
    """Turn a user prompt into a coherent first-person Mia vlog with enforced continuity and emotional progression."""

    LOCATION_TRANSITIONS = {
        "leave", "leaves", "left", "exit", "exits", "exited", "walk out", "walked out",
        "step outside", "stepped outside", "go outside", "went outside", "outside",
        "enter", "enters", "entered", "walk in", "walked in", "go in", "went in",
        "arrive", "arrives", "arrived", "head to", "headed to", "go to", "went to",
        "return", "returns", "returned", "back to", "go back", "went back",
        "drive to", "drove to", "run to", "ran to", "approach", "approached",
    }

    EMOTION_PROGRESSION = [
        "calm", "curious", "interested", "uneasy", "concerned",
        "suspicious", "worried", "nervous", "anxious", "shocked",
        "frightened", "scared", "terrified", "determined"
    ]

    def __init__(self, agnes: AgnesClient):
        self.agnes = agnes

    def plan(self, user_prompt: str) -> Dict:
        prompt = user_prompt.strip()
        if not prompt:
            raise ValueError("The Mia prompt cannot be empty")

        instruction = f"""Create one short-form vertical daily-vlog episode starring Mia, a recurring adult female influencer. The user's request is:

{prompt}

Return ONLY valid JSON with this exact shape:
{{
  "title": "short episode title",
  "genre": "daily_vlog|travel|mystery|horror|reaction|story",
  "tone": "warm natural|cool suspense|dark atmospheric",
  "outfit": "one concise continuity outfit description",
  "script": "35-55 second first-person narration spoken by Mia. Natural conversational vlog speech. No awkward fragments.",
  "opening_hook": "the FIRST 1-2 sentences that immediately establish the mystery/premise. Must be attention-grabbing and create curiosity without spoiling the ending.",
  "final_reveal": "the climactic final 2-3 sentences. Must deliver a payoff, unanswered question, or disturbing realization. NOT just 'Mia looks scared.'",
  "key_objects": [
    {{"name": "object_id", "type": "photograph|phone|letter|key|book|document|prop", "description": "visual description", "introduced_scene": 1}}
  ],
  "emotional_arc": ["curious", "uneasy", "shocked"],
  "scenes": [
    {{
      "index": 1,
      "narration": "exact contiguous portion of the script",
      "location": "specific location",
      "location_change_reason": "explicit script justification or 'same_location'",
      "action": "what Mia physically does",
      "shot_type": "selfie medium|handheld medium|POV|establishing|medium close-up|close-up|reaction close-up|third-person wide|object close-up|walking shot|over-the-shoulder",
      "visual_prompt": "specific visual beat",
      "camera_motion": "subtle push-in|slow pull-out|gentle handheld drift|slow pan|subtle tracking",
      "lighting": "cohesive lighting for the episode",
      "expression": "Mia's natural expression",
      "objects_visible": ["object_id"],
      "objects_held": ["object_id"],
      "emotional_state": "curious",
      "story_event": "what narrative event happens in this scene",
      "transition": "cut|crossfade"
    }}
  ]
}}

CRITICAL RULES:

1. OPENING HOOK (MANDATORY): The script MUST start with an attention-grabbing first sentence that immediately communicates the unusual event. Examples:
   - "I found a hidden room in my new apartment."
   - "These photos shouldn't exist."
   - "My mirror is doing something it shouldn't."
   Do NOT start with boring exposition like "I moved in three days ago" or "So I was walking around..."

2. NATURAL SPEECH: Mia should sound like a real person talking to her camera. Use contractions, casual language, natural pauses. Avoid literary exposition or awkward fragments like "Too fine, maybe."

3. FINAL REVEAL (MANDATORY): The ending must deliver a payoff, not just show Mia looking scared. Examples:
   - A photograph shows something impossible
   - A date on an object is in the future
   - Mia realizes she's been watched
   - The object reveals a hidden detail
   End with an unanswered question or disturbing realization.

4. CONTINUITY:
   - Mia stays in the SAME location across consecutive scenes UNLESS the script explicitly describes her moving.
   - Never invent a new location not justified by the narration.
   - Objects persist: if Mia is holding an object, she continues holding it unless the script says she puts it down.
   - Use 4-7 scenes. Each scene must correspond to a clear narrative beat.

5. FIRST SCENE: Must open with Mia already engaged in the premise — NO pure establishing shots without Mia and the hook visible. The first visual must support the opening hook.

6. FINAL SCENE: Must deliver payoff around the central mystery object or revelation. The final visual should be the strongest shot in the video.

7. EMOTIONAL PROGRESSION: Build logically. For mystery/horror: calm → curious → uneasy → suspicious → shocked → frightened.

8. SHOT TYPES: Prefer selfie medium, handheld medium, POV, natural close-up. Avoid extreme close-ups that cause facial distortion.

9. Every scene must have location_change_reason explaining same vs different location.

10. Track key_objects throughout — once introduced, they remain in scenes where appropriate.
"""
        raw = self.agnes.chat(
            instruction,
            max_tokens=4000,
            temperature=0.55,
            system_prompt="You are a strict JSON-only short-form video writer. You write natural conversational vlog scripts with strong hooks and satisfying endings. You enforce physical continuity, object persistence, and emotional progression.",
        )
        data = self._parse_json(raw)
        return self._validate_and_fix(data, prompt)

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

    def _validate_and_fix(self, data: Dict, original_prompt: str) -> Dict:
        script = str(data.get("script") or "").strip()
        scenes = data.get("scenes")
        if not script or not isinstance(scenes, list) or not scenes:
            raise RuntimeError("Story plan is missing script or scenes")

        # Build object registry
        objects = {}
        for obj in data.get("key_objects", []):
            if isinstance(obj, dict) and obj.get("name"):
                objects[obj["name"]] = obj

        # Normalize and enforce continuity
        cleaned = self._enforce_continuity(scenes, script, objects)
        if len(cleaned) < 3:
            cleaned = self._fallback_scenes(script)

        # Rebuild script from scene narrations
        scene_script = " ".join(s["narration"] for s in cleaned if s["narration"]).strip()
        if scene_script:
            script = scene_script

        # Ensure emotional arc
        emotional_arc = data.get("emotional_arc", [])
        if not emotional_arc and cleaned:
            emotional_arc = [s.get("emotional_state", "curious") for s in cleaned]

        # Validate opening hook
        opening_hook = str(data.get("opening_hook") or "").strip()
        if not opening_hook and cleaned:
            opening_hook = cleaned[0]["narration"]
        # Ensure hook is actually attention-grabbing
        hook_lower = opening_hook.lower()
        weak_starts = ["i moved", "so i", "i was", "i am", "i'm just", "today i", "hey guys"]
        if any(hook_lower.startswith(w) for w in weak_starts) and len(cleaned) > 1:
            # Try to find a better hook from the first scene's action/visual
            visual = str(cleaned[0].get("visual_prompt", "")).strip()
            if visual and len(visual) > 20:
                opening_hook = visual[:100]

        # Validate final reveal
        final_reveal = str(data.get("final_reveal") or "").strip()
        if not final_reveal and cleaned:
            final_reveal = cleaned[-1]["narration"]
        # Ensure final reveal isn't generic
        generic_endings = ["mia looks scared", "she looks scared", "mia is frightened", "she is frightened",
                          "mia looks terrified", "she looks terrified", "end", "the end"]
        final_lower = final_reveal.lower()
        if any(g in final_lower for g in generic_endings):
            # Generate a stronger ending from the story context
            logger.warning("Generic ending detected, strengthening final reveal")
            # Use the last scene's story event if available
            last_event = str(cleaned[-1].get("story_event", "")).strip()
            if last_event and len(last_event) > 20:
                final_reveal = last_event[:200]

        return {
            "title": str(data.get("title") or "Mia's Daily Vlog").strip()[:100],
            "genre": str(data.get("genre") or "daily_vlog").strip().lower(),
            "tone": str(data.get("tone") or "warm natural").strip(),
            "outfit": str(data.get("outfit") or "cream fitted top and high-waisted blue jeans").strip(),
            "script": script,
            "opening_hook": opening_hook[:300],
            "final_reveal": final_reveal[:300],
            "emotional_arc": emotional_arc,
            "key_objects": list(objects.values()),
            "scenes": cleaned,
            "source_prompt": original_prompt,
        }

    def _enforce_continuity(self, scenes: List[Dict], script: str, objects: Dict) -> List[Dict]:
        script_lower = script.lower()
        cleaned = []
        prev_location = None
        prev_objects_held = set()
        prev_emotion = "calm"

        for i, scene in enumerate(scenes[:7], 1):
            if not isinstance(scene, dict):
                continue

            narration = str(scene.get("narration") or "").strip()
            location = str(scene.get("location") or prev_location or "the current location").strip()
            change_reason = str(scene.get("location_change_reason") or "").strip()
            shot = str(scene.get("shot_type") or "handheld medium vlog shot").strip().lower()

            # Fix unjustified location jumps
            if prev_location and location != prev_location:
                justified = self._is_location_change_justified(narration, prev_location, location)
                if not justified:
                    logger.warning(
                        "Continuity fix: scene %d changed location '%s' -> '%s' without justification. Reverting.",
                        i, prev_location, location
                    )
                    location = prev_location
                    change_reason = f"same_location (reverted from {location})"

            # Track objects
            objects_visible = set()
            for obj_name in scene.get("objects_visible", []):
                if obj_name in objects:
                    objects_visible.add(obj_name)

            objects_held = set()
            for obj_name in scene.get("objects_held", []):
                if obj_name in objects:
                    objects_held.add(obj_name)

            # Persist held objects unless script says dropped
            for held in prev_objects_held:
                if held not in objects_held:
                    drop_words = ["put", "down", "set", "drop", "placed", "away", "hide", "hid", "leave", "left behind"]
                    narration_lower = narration.lower()
                    if not any(dw in narration_lower for dw in drop_words):
                        objects_visible.add(held)
                        objects_held.add(held)
                        logger.info("Continuity: keeping object '%s' in scene %d", held, i)

            # Fix shot types
            if "extreme" in shot or "macro" in shot:
                shot = "medium close-up"
            if "establishing" in shot and i > 1:
                shot = "handheld medium vlog shot"

            # First scene must show Mia + hook
            if i == 1:
                if "establishing" in shot and "mia" not in str(scene.get("visual_prompt", "")).lower():
                    shot = "selfie medium"

            # Final scene should be reaction/close-up payoff
            if i == len(scenes) and "wide" in shot:
                shot = "reaction close-up"

            # Validate emotional state
            emotional_state = str(scene.get("emotional_state") or prev_emotion).strip()
            if not emotional_state or emotional_state.lower() == "neutral":
                emotional_state = self._derive_emotion(i, len(scenes))

            cleaned.append({
                "index": i,
                "narration": narration,
                "location": location,
                "location_change_reason": change_reason or ("same_location" if location == prev_location else "script transition"),
                "action": str(scene.get("action") or narration or "Mia records her vlog").strip(),
                "shot_type": shot,
                "visual_prompt": str(scene.get("visual_prompt") or scene.get("action") or narration).strip(),
                "camera_motion": str(scene.get("camera_motion") or "subtle handheld push-in").strip(),
                "lighting": str(scene.get("lighting") or self._default_lighting(scene.get("tone"))).strip(),
                "expression": str(scene.get("expression") or "natural and emotionally appropriate").strip(),
                "objects_visible": sorted(objects_visible),
                "objects_held": sorted(objects_held),
                "emotional_state": emotional_state,
                "story_event": str(scene.get("story_event") or narration[:100]).strip(),
                "transition": "cut" if str(scene.get("transition", "")).lower() == "cut" else "crossfade",
            })

            prev_location = location
            prev_objects_held = objects_held
            prev_emotion = emotional_state

        return cleaned

    def _is_location_change_justified(self, narration: str, from_loc: str, to_loc: str) -> bool:
        narration_lower = narration.lower()
        for phrase in self.LOCATION_TRANSITIONS:
            if phrase in narration_lower:
                return True
        to_simple = to_loc.lower().replace("the ", "").replace("a ", "").split()[0]
        if to_simple in narration_lower:
            return True
        return False

    def _derive_emotion(self, scene_index: int, total_scenes: int) -> str:
        if total_scenes <= 1:
            return "curious"
        ratio = (scene_index - 1) / max(total_scenes - 1, 1)
        idx = int(ratio * (len(self.EMOTION_PROGRESSION) - 1))
        return self.EMOTION_PROGRESSION[min(idx, len(self.EMOTION_PROGRESSION) - 1)]

    @staticmethod
    def _default_lighting(tone) -> str:
        tone = str(tone or "").lower()
        if "dark" in tone or "horror" in tone:
            return "dark cinematic practical light with controlled shadows"
        if "cool" in tone or "suspense" in tone:
            return "slightly cool realistic suspense lighting"
        return "natural warm realistic daylight"

    def _fallback_scenes(self, script: str) -> List[Dict]:
        sentences = [self._clean_sentence(s) for s in re.split(r"(?<=[.!?])\s+", script) if s.strip()]
        count = min(6, max(3, len(sentences)))
        groups = [[] for _ in range(count)]
        for i, sentence in enumerate(sentences):
            groups[min(i * count // max(len(sentences), 1), count - 1)].append(sentence)
        shots = ["selfie medium", "handheld medium", "POV", "medium close-up", "reaction close-up", "close-up"]
        emotions = ["curious", "interested", "uneasy", "concerned", "suspicious", "shocked"]
        return [{
            "index": i + 1,
            "narration": " ".join(group),
            "location": "the story's current location",
            "location_change_reason": "same_location" if i == 0 else "script continuation",
            "action": "Mia acts out this story beat while recording her vlog",
            "shot_type": shots[i % len(shots)],
            "visual_prompt": " ".join(group),
            "camera_motion": "subtle handheld push-in",
            "lighting": "natural cohesive cinematic lighting",
            "expression": "natural and emotionally appropriate",
            "objects_visible": [],
            "objects_held": [],
            "emotional_state": emotions[i % len(emotions)],
            "story_event": " ".join(group)[:100],
            "transition": "crossfade" if i else "cut",
        } for i, group in enumerate(groups) if group]

    @staticmethod
    def _clean_sentence(text: str) -> str:
        text = text.strip()
        text = re.sub(r"^\s*[\s,;:\-–—]+", "", text)
        text = re.sub(r"\s+", " ", text)
        return text
