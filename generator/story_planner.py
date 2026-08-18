import json
import logging
import re
from typing import Dict, List

from generator.agnes_client import AgnesClient

logger = logging.getLogger(__name__)


class StoryPlanner:
    def __init__(self, agnes_client: AgnesClient):
        self.agnes = agnes_client

    def plan(self, user_prompt: str, max_attempts: int = 3) -> Dict:
        """Plan a Mia vlog with action-driven scene descriptions for realistic footage."""

        system_prompt = (
            "You are a cinematic storyboard planner for Mia, a female daily vlogger and storyteller. "
            "Your ONLY job is to return valid raw JSON. No markdown. No code blocks. No explanation.\n\n"

            "CRITICAL VIDEO GENERATION RULES — READ FIRST:\n"
            "1. ACTION > CAMERA EFFECTS. Every scene must show Mia PHYSICALLY DOING something from the script. "
            "NEVER describe a scene as just 'Mia standing' or 'Mia looking at camera with zoom effect'.\n"
            "2. When Mia changes location → create a NEW scene showing her IN that new location.\n"
            "3. When Mia performs an action → SHOW her physically performing it: walking, entering, picking up, opening, reacting, talking.\n"
            "4. Use a mixture of shots: wide shots, medium shots, close-ups, over-the-shoulder, handheld vlog style.\n"
            "5. Use normal cinematic cuts between scenes. NO continuous zoom in/out. NO keeping Mia in the same position.\n"
            "6. Mia must naturally walk, move, interact with objects, use her hands, look around, react emotionally.\n"
            "7. Keep Mia's face, hairstyle, clothing, body proportions consistent across every scene.\n"
            "8. The viewer should feel they are watching REAL FOOTAGE of Mia living through the story, not one image being zoomed.\n"
            "9. Read the script first. Identify EVERY action and location change. Create a SEPARATE visual shot for EACH story beat.\n"
            "10. Do NOT skip or visually substitute actions described in the script.\n\n"

            "Required JSON structure:\n"
            "{\n"
            '  \"title\": \"catchy Shorts title without Mia prefix, action-driven, curiosity hook\",\n'
            '  \"script\": \"first person vlog narration, natural spoken, 25-40 seconds\",\n'
            '  \"scenes\": [\n'
            '    {\"description\": \"SPECIFIC visual description: shot type + exact action + location + Mia expression + camera style\", \"mood\": \"neutral|tense|curious|frightened\"},\n'
            '    {\"description\": \"...\", \"mood\": \"...\"},\n'
            '    {\"description\": \"...\", \"mood\": \"...\"},\n'
            '    {\"description\": \"...\", \"mood\": \"...\"}\n'
            '  ],\n'
            '  \"genre\": \"daily_vlog\"\n'
            "}\n\n"

            "Scene description rules:\n"
            "- MUST specify the shot type: wide shot, medium shot, close-up, over-the-shoulder, POV, handheld vlog selfie, tracking shot.\n"
            "- MUST describe the EXACT action: 'Mia walking out of a coffee shop pushing the door open', 'Mia bending down to take a silver key from a small girl's hand', 'Mia inserting a key into a door lock, her hand trembling slightly'.\n"
            "- MUST include the location and environment: street, apartment building, hallway, room interior.\n"
            "- MUST include Mia's expression and body language: skeptical, confused, shocked, scared.\n"
            "- MUST include camera movement only if it serves the action: 'handheld camera following Mia as she walks', 'close-up tracking shot of the key approaching the lock'.\n"
            "- NEVER use: 'zoom in on Mia', 'slow pan across Mia', 'Mia standing still', 'static shot of Mia', 'Mia at her desk'.\n"
            "- If the script mentions a coffee shop → scene 1 shows Mia EXITING the coffee shop, pushing the door, stepping onto the sidewalk.\n"
            "- If a little girl stops her → scene 2 shows the girl tugging Mia's sleeve, looking up, holding out the key.\n"
            "- If Mia looks at an apartment building → scene 3 shows Mia looking UP at the building, then WALKING toward the entrance.\n"
            "- If Mia opens a door → scene 4 shows her hand turning the key, door creaking open, her face reacting to what's inside.\n\n"

            "Title rules:\n"
            "- NO 'Mia:' prefix\n"
            "- NO filler words like 'Exploring' or 'Journey'\n"
            "- NO words like 'AI', 'AI-generated', 'AI video', 'AI character', 'AI influencer' in the title, script, or anywhere\n"
            "- Focus on STORY, MYSTERY, EMOTION and EVENTS\n"
            "- Action-driven, curiosity hook, sounds like a real Shorts creator wrote it\n"
            "- Examples: 'A Little Girl Handed Me a Key With My Name On It', 'I Opened the Door and Froze', 'Every Photo in This Hallway Was of Me'\n\n"

            "Script rules:\n"
            "- First person, spoken naturally, like Mia is telling the story directly to her phone camera\n"
            "- Include verbal fillers: 'right?', 'okay?', 'I swear', 'no joke'\n"
            "- 25-40 seconds when read at natural speaking pace\n"
            "- NO mention of being AI, generated, virtual, or artificial anywhere in the script\n"
            "- Mia is a real character in a fictional daily-vlog series\n\n"

            "Return ONLY raw JSON. Use double quotes for all strings. No trailing commas."
        )

        for attempt in range(1, max_attempts + 1):
            temp = 0.5 if attempt == 1 else 0.3
            prompt = f"Plan a Mia vlog about: {user_prompt}"

            if attempt > 1:
                prompt += (
                    "\n\nPrevious attempt failed. Return ONLY valid raw JSON. "
                    "Make sure every scene description shows a SPECIFIC ACTION with a SPECIFIC SHOT TYPE. "
                    "No zoom-only scenes. No static standing shots."
                )

            try:
                logger.info("Story plan attempt %d/%d (temp=%.1f)", attempt, max_attempts, temp)
                raw = self.agnes.chat(
                    prompt,
                    system_prompt=system_prompt,
                    temperature=temp,
                    max_tokens=4000,
                )
                logger.info("Raw response length: %d chars", len(str(raw)))
                logger.debug("Raw response (first 1200 chars): %s", str(raw)[:1200])

                if not raw or not str(raw).strip():
                    raise ValueError("Empty response from API")

                data = self._extract_and_repair_json(str(raw))
                self._validate_and_fix(data, user_prompt)
                logger.info("Story plan succeeded on attempt %d", attempt)
                return data

            except Exception as e:
                logger.warning("Attempt %d/%d failed: %s", attempt, max_attempts, e)
                if attempt >= max_attempts:
                    raise RuntimeError(f"Story planner failed after {max_attempts} attempts: {e}")

    def _extract_and_repair_json(self, raw: str) -> Dict:
        """Extract JSON from messy LLM output with multiple repair strategies."""
        text = str(raw).strip()

        # Remove markdown code blocks
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()

        # If response has explanatory text before JSON, extract the JSON object
        if not text.startswith("{"):
            match = re.search(r"(\{[\s\S]*\})", text)
            if match:
                text = match.group(1).strip()

        # Strategy 1: Parse as-is
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Strategy 2: Fix trailing commas before } or ]
        repaired = re.sub(r",(\s*[}\]])", r"\1", text)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            pass

        # Strategy 3: Fix single quotes to double quotes
        repaired = text.replace("'", '"')
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            pass

        # Strategy 4: Extract fields with regex fallback
        logger.warning("JSON unparseable, attempting field extraction. Raw: %s", text[:800])
        return self._extract_fields_fallback(text)

    def _extract_fields_fallback(self, text: str) -> Dict:
        """Last resort: extract key fields with regex."""
        result: Dict = {}

        m = re.search(r'"title"\s*:\s*"([^"]+)"', text)
        if m:
            result["title"] = m.group(1)

        m = re.search(r'"script"\s*:\s*"((?:[^"\\]|\\.)*)"', text, re.DOTALL)
        if m:
            result["script"] = m.group(1).replace('\\"', '"').replace("\n", " ").strip()

        m = re.search(r'"scenes"\s*:\s*(\[[\s\S]*?\])', text, re.DOTALL)
        if m:
            scenes_text = m.group(1)
            scenes_text = re.sub(r",(\s*[}\]])", r"\1", scenes_text)
            try:
                result["scenes"] = json.loads(scenes_text)
            except json.JSONDecodeError:
                pass

        result["genre"] = "daily_vlog"
        return result

    def _validate_and_fix(self, data: Dict, user_prompt: str) -> None:
        """Ensure all required fields exist and scenes are action-driven."""

        if "title" not in data or not data["title"]:
            data["title"] = self._generate_title(user_prompt)

        if "script" not in data or not data["script"]:
            raise RuntimeError("Missing required field: script")

        if "scenes" not in data or not isinstance(data["scenes"], list) or len(data["scenes"]) == 0:
            logger.warning("No scenes found, auto-generating from script")
            data["scenes"] = self._generate_scenes_from_script(data["script"])

        if "genre" not in data:
            data["genre"] = "daily_vlog"

        # Clean title
        title = str(data["title"]).strip()
        if title.lower().startswith("mia:"):
            title = title[4:].strip()
        # Strip AI-related words from title
        title = self._strip_ai_words(title)
        data["title"] = title

        # Clean script
        script = str(data["script"]).strip()
        script = re.sub(r'^(Mia:\s*)+', '', script, flags=re.IGNORECASE)
        script = self._strip_ai_words(script)
        data["script"] = script

        # Ensure at least 4 scenes for a dynamic story
        while len(data["scenes"]) < 4:
            data["scenes"].append({
                "description": "Mia reacting with genuine emotion to the story events, close-up handheld vlog shot, natural lighting",
                "mood": "neutral"
            })

        # Detect and fix generic/zoom-only scene descriptions
        script_lower = data["script"].lower()
        has_specific = any(x in script_lower for x in [
            "coffee", "girl", "key", "apartment", "street", "phone", "door",
            "restaurant", "car", "building", "found", "handed", "walked", "opened",
            "hallway", "photo", "footstep", "ran", "looked", "turned"
        ])

        generic_patterns = [
            r"zoom\s+(in|out)",
            r"slow\s+(pan|zoom)",
            r"static\s+shot",
            r"Mia\s+standing\s+(still|in)",
            r"Mia\s+at\s+her\s+desk",
            r"Mia\s+sitting\s+at",
            r"desk\s+lamp",
            r"whiteboard",
            r"just\s+looking\s+at\s+camera",
        ]

        for i, scene in enumerate(data["scenes"]):
            desc = str(scene.get("description", ""))
            # Strip AI words from scene descriptions too
            scene["description"] = self._strip_ai_words(desc)
            desc_lower = desc.lower()

            is_generic = any(re.search(p, desc_lower) for p in generic_patterns)

            if is_generic and has_specific and i < 4:
                logger.warning("Replacing generic/zoom scene %d with action-driven visual", i)
                if "coffee" in script_lower and i == 0:
                    scene["description"] = "Wide shot: Mia pushing open a coffee shop door and stepping out onto a busy sidewalk, afternoon sunlight, she checks her phone, handheld vlog camera following her movement"
                elif "girl" in script_lower and i == 1:
                    scene["description"] = "Medium shot: A young girl in a hoodie tugging Mia's sleeve on the sidewalk, looking up at her with wide eyes, holding out a small silver key in her open palm, city street background"
                elif "key" in script_lower and i == 2:
                    scene["description"] = "Close-up tracking shot: Mia's hand reaching out to take the silver key, then turning it over in her fingers, examining it with a confused expression, shallow depth of field"
                elif "apartment" in script_lower or "building" in script_lower:
                    scene["description"] = "Low angle wide shot: Mia looking up at an apartment building facade, then walking toward the entrance with hesitant steps, handheld camera following from behind"
                elif "door" in script_lower:
                    scene["description"] = "Over-the-shoulder close-up: Mia's hand inserting the silver key into a door lock, turning it, the door slowly creaking open, her face partially visible showing shock"
                elif "hallway" in script_lower or "photo" in script_lower:
                    scene["description"] = "Wide interior shot: Mia stepping into a narrow hallway, walls covered floor-to-ceiling with photographs, she freezes mid-step, her mouth slightly open in disbelief, warm yellow lighting"
                elif "footstep" in script_lower:
                    scene["description"] = "Close-up on Mia's face: her eyes widening in fear as she hears footsteps, she slowly turns her head toward the sound, dark hallway behind her"
                else:
                    scene["description"] = f"Dynamic action shot showing the key moment from this part of the story: {data['script'][:120]}..., handheld vlog style, natural movement"

        # Final validation: every scene must contain an action verb
        action_verbs = ["walking", "running", "pushing", "opening", "closing", "turning", "looking", "reaching",
                       "picking", "holding", "stepping", "entering", "reacting", "talking", "following",
                       "pulling", "inserting", "examining", "walking", "stepping", "bending", "taking"]
        for i, scene in enumerate(data["scenes"]):
            desc_lower = str(scene.get("description", "")).lower()
            has_action = any(verb in desc_lower for verb in action_verbs)
            if not has_action:
                logger.warning("Scene %d still has no action verb, injecting movement", i)
                scene["description"] = "Handheld tracking shot following Mia as she moves through the scene, " + str(scene.get("description", ""))

    @staticmethod
    def _strip_ai_words(text: str) -> str:
        """Remove AI-related words from text while preserving natural flow."""
        # List of AI-related words/phrases to strip
        ai_patterns = [
            r'\bAI[- ]?generated?\b',
            r'\bAI[- ]?influencer?\b',
            r'\bAI[- ]?character?\b',
            r'\bAI[- ]?video?\b',
            r'\bAI[- ]?vlog?\b',
            r'\bAI[- ]?story?\b',
            r'\bartificial intelligence\b',
            r'\bvirtual influencer\b',
            r'\bvirtual character\b',
            r'\bgenerated by AI\b',
            r'\bcreated by AI\b',
            r'\bAI[- ]?created\b',
            r'\bAI[- ]?based\b',
            r'\bnot a real person\b',
            r'\bdigital creator\b',
            r'\bvirtual creator\b',
        ]
        cleaned = text
        for pattern in ai_patterns:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
        # Clean up double spaces and stray punctuation from removals
        cleaned = re.sub(r'\s+', ' ', cleaned)
        cleaned = re.sub(r'\s+([.,!?])', r'\1', cleaned)
        return cleaned.strip()

    def _generate_title(self, prompt: str) -> str:
        prompt = prompt.strip()
        if len(prompt) > 60:
            prompt = prompt[:57] + "..."
        prompt = re.sub(r'^(Mia|story|about|vlog|video|short)\s*[:,-]\s*', '', prompt, flags=re.IGNORECASE)
        title = prompt[:80] or "Mia's Story"
        return self._strip_ai_words(title)

    def _generate_scenes_from_script(self, script: str) -> List[Dict]:
        """Break script into 4 action-driven visual scenes."""
        sentences = re.split(r'(?<=[.!?])\s+', script)
        sentences = [s.strip() for s in sentences if s.strip()]
        scenes = []
        chunk_size = max(1, len(sentences) // 4)

        shot_types = [
            "Wide establishing shot",
            "Medium handheld vlog shot",
            "Close-up detail shot",
            "Over-the-shoulder reaction shot"
        ]

        for i in range(0, min(len(sentences), 4 * chunk_size), chunk_size):
            chunk = " ".join(sentences[i:i + chunk_size])
            desc = f"{shot_types[len(scenes) % 4]}: {chunk[:200]}. Natural handheld camera movement following the action."
            scenes.append({
                "description": self._strip_ai_words(desc),
                "mood": "neutral"
            })

        while len(scenes) < 4:
            scenes.append({
                "description": f"{shot_types[len(scenes) % 4]}: Mia reacting emotionally to the story, natural movement, handheld vlog style",
                "mood": "neutral"
            })

        return scenes
