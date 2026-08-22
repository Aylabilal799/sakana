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
        """Plan a Mia vlog with action-driven, causally-linked scene descriptions for realistic footage."""

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
            "10. Do NOT skip or visually substitute actions described in the script.\n"
            "11. ONE CONTINUOUS THREAD: Every scene must be a direct consequence of the scene before it. "
            "Never insert a new, unrelated moment (a random check of her phone, an unrelated errand, an unrelated "
            "location) that doesn't continue what the previous scene was about. If you removed the object or event "
            "introduced in an earlier scene, a later scene should stop making sense — that's the test.\n"
            "12. HOOK TIMING: scene 1 must show Mia already mid-action or already reacting to something — never a "
            "static introduction or slow build-up. The first 1-2 sentences of the script must be short enough to be "
            "spoken in under 3 seconds, because that is the window before a viewer swipes away.\n\n"

            "Required JSON structure:\n"
            "{\n"
            '  \"title\": \"catchy Shorts title without Mia prefix, action-driven, curiosity hook\",\n'
            '  \"script\": \"first person vlog narration, natural spoken, 25-40 seconds\",\n'
            '  \"point_a\": \"one sentence: Mia\'s situation before anything in the story happens\",\n'
            '  \"point_b\": \"one sentence: Mia\'s situation at the end, and what concretely changed from point_a\",\n'
            '  \"scenes\": [\n'
            '    {\"description\": \"SPECIFIC visual description: shot type + exact action + location + Mia expression + camera style\", '
            '\"follows_from_previous\": \"short phrase naming exactly what this scene continues from the one before it (opening for scene 1)\", '
            '\"mood\": \"neutral|tense|curious|frightened\"},\n'
            '    {\"description\": \"...\", \"follows_from_previous\": \"...\", \"mood\": \"...\"},\n'
            '    {\"description\": \"...\", \"follows_from_previous\": \"...\", \"mood\": \"...\"},\n'
            '    {\"description\": \"...\", \"follows_from_previous\": \"...\", \"mood\": \"...\"}\n'
            '  ],\n'
            '  \"genre\": \"daily_vlog\"\n'
            "}\n\n"

            "Scene description rules:\n"
            "- MUST specify the shot type: wide shot, medium shot, close-up, over-the-shoulder, POV, handheld vlog selfie, tracking shot.\n"
            "- MUST describe the EXACT action, drawn from what THIS scene's own narration segment says — not from "
            "keywords appearing anywhere else in the script.\n"
            "- MUST include the location and environment: street, apartment building, hallway, room interior.\n"
            "- MUST include Mia's expression and body language: skeptical, confused, shocked, scared.\n"
            "- MUST include camera movement only if it serves the action: 'handheld camera following Mia as she walks', 'close-up tracking shot of the key approaching the lock'.\n"
            "- MUST fill in follows_from_previous with the specific object/action/question carried over from the prior scene. "
            "If you cannot name one, the scene is disconnected and must be rewritten so it continues the story instead.\n"
            "- NEVER use: 'zoom in on Mia', 'slow pan across Mia', 'Mia standing still', 'static shot of Mia', 'Mia at her desk'.\n\n"

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
            "- The opening 1-2 sentences must be short enough to speak in under 3 seconds and must drop the viewer "
            "already into the moment, not into a slow introduction\n"
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
                    "Make sure every scene description shows a SPECIFIC ACTION with a SPECIFIC SHOT TYPE, "
                    "and that every scene's follows_from_previous names something real carried over from the scene "
                    "before it. No zoom-only scenes. No static standing shots. No disconnected scenes."
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

        m = re.search(r'"point_a"\s*:\s*"((?:[^"\\]|\\.)*)"', text, re.DOTALL)
        if m:
            result["point_a"] = m.group(1).replace('\\"', '"').strip()

        m = re.search(r'"point_b"\s*:\s*"((?:[^"\\]|\\.)*)"', text, re.DOTALL)
        if m:
            result["point_b"] = m.group(1).replace('\\"', '"').strip()

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
        """Ensure all required fields exist and scenes are action-driven and causally linked."""

        if "title" not in data or not data["title"]:
            data["title"] = self._generate_title(user_prompt)

        if "script" not in data or not data["script"]:
            raise RuntimeError("Missing required field: script")

        if "scenes" not in data or not isinstance(data["scenes"], list) or len(data["scenes"]) == 0:
            logger.warning("No scenes found, auto-generating from script")
            data["scenes"] = self._generate_scenes_from_script(data["script"])

        if "genre" not in data:
            data["genre"] = "daily_vlog"

        data.setdefault("point_a", "")
        data.setdefault("point_b", "")

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
                "description": "Mia reacting with genuine emotion to what just happened in the previous scene, "
                               "close-up handheld vlog shot, natural lighting",
                "follows_from_previous": "the event from the previous scene",
                "mood": "neutral"
            })

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

        # Split the script into per-scene chunks so a generic scene can be replaced with
        # something derived from ITS OWN narration, not from keywords anywhere else in the
        # script. The previous version matched keywords like "coffee"/"key"/"hallway" against
        # the whole script and swapped in a hardcoded example scene (from one specific test
        # story) whenever they appeared anywhere — which could inject a totally unrelated
        # scene (e.g. a "hallway full of photographs") into an unrelated story just because the
        # word "photo" showed up somewhere in the narration. That bug is removed here.
        script_chunks = self._split_into_chunks(data["script"], len(data["scenes"]))

        for i, scene in enumerate(data["scenes"]):
            desc = str(scene.get("description", ""))
            scene["description"] = self._strip_ai_words(desc)
            scene.setdefault("follows_from_previous", "opening" if i == 0 else "the previous scene's event")
            desc_lower = scene["description"].lower()

            is_generic = any(re.search(p, desc_lower) for p in generic_patterns)
            if is_generic:
                logger.warning("Scene %d description was generic/static, rebuilding from its own narration", i)
                own_chunk = script_chunks[i] if i < len(script_chunks) else data["script"][:150]
                shot_type = ["Wide shot", "Medium handheld shot", "Close-up shot", "Over-the-shoulder shot"][i % 4]
                scene["description"] = self._strip_ai_words(
                    f"{shot_type}: Mia physically acting out — {own_chunk.strip()[:180]} — "
                    "handheld vlog camera, natural continuous movement, expression matching the moment."
                )

        # Final validation: every scene must contain an action verb
        action_verbs = ["walking", "running", "pushing", "opening", "closing", "turning", "looking", "reaching",
                       "picking", "holding", "stepping", "entering", "reacting", "talking", "following",
                       "pulling", "inserting", "examining", "bending", "taking"]
        for i, scene in enumerate(data["scenes"]):
            desc_lower = str(scene.get("description", "")).lower()
            has_action = any(verb in desc_lower for verb in action_verbs)
            if not has_action:
                logger.warning("Scene %d still has no action verb, injecting movement", i)
                scene["description"] = "Handheld tracking shot following Mia as she moves through the scene, " + str(scene.get("description", ""))

    @staticmethod
    def _split_into_chunks(script: str, n: int) -> List[str]:
        """Split a script into n roughly-even sentence chunks, in order, for per-scene grounding."""
        sentences = re.split(r'(?<=[.!?])\s+', script)
        sentences = [s.strip() for s in sentences if s.strip()]
        if not sentences:
            return [script] * max(n, 1)
        n = max(n, 1)
        chunk_size = max(1, len(sentences) // n)
        chunks = []
        for i in range(0, len(sentences), chunk_size):
            chunks.append(" ".join(sentences[i:i + chunk_size]))
        while len(chunks) < n:
            chunks.append(chunks[-1] if chunks else script)
        return chunks[:n]

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
        """Break script into 4 action-driven, causally-ordered visual scenes."""
        chunks = self._split_into_chunks(script, 4)

        shot_types = [
            "Wide establishing shot",
            "Medium handheld vlog shot",
            "Close-up detail shot",
            "Over-the-shoulder reaction shot"
        ]

        scenes = []
        for i, chunk in enumerate(chunks):
            desc = f"{shot_types[i % 4]}: {chunk[:200]}. Natural handheld camera movement following the action."
            scenes.append({
                "description": self._strip_ai_words(desc),
                "follows_from_previous": "opening" if i == 0 else "the event described in the previous scene",
                "mood": "neutral"
            })

        return scenes


# Available Kokoro voices for confession characters
CONFESSION_VOICES = {
    "female": ["af_bella", "af_nicole", "af_sky", "af_sarah"],
    "male": ["am_adam", "am_michael"],
}


class ConfessionStoryPlanner:
    """Plans multi-character confession, breakup, and mystery stories with dialogue."""

    def __init__(self, agnes_client: AgnesClient):
        self.agnes = agnes_client

    def plan(self, user_prompt: str, max_attempts: int = 3) -> Dict:
        """Plan a multi-character confession/mystery/breakup story with dialogue."""

        system_prompt = (
            "You are a cinematic storyboard planner for dramatic short-form videos featuring "
            "2-3 characters in realistic scenes. These are NOT vlogs — they are cinematic story "
            "scenes that feel like clips from a movie or TV show. Real dialogue, real emotions, "
            "real locations. Your ONLY job is to return valid raw JSON. No markdown. No code blocks. "
            "No explanation.\n\n"

            "CRITICAL RULES:\n"
            "1. Create 2-3 distinct characters with clear roles (e.g., protagonist, partner, friend).\n"
            "2. The script must be DIALOGUE between characters, NOT first-person narration.\n"
            "3. Each line of dialogue must start with the character name in ALL CAPS followed by a colon.\n"
            "4. Every scene must show the characters PHYSICALLY INTERACTING — talking, reacting, moving, "
            "gesturing, confronting, embracing, walking away. NEVER a static shot of people just standing.\n"
            "5. Use cinematic shot types: wide shot, medium shot, close-up, over-the-shoulder, two-shot, "
            "tracking shot, handheld dramatic shot.\n"
            "6. The story must feel REAL — like a scene from a relationship drama, mystery, or confession.\n"
            "7. Genres: breakup, confession, mystery, strange discovery, betrayal, confrontation.\n"
            "8. Keep dialogue natural and emotionally charged. People interrupt each other, stumble on words, "
            "get angry, cry, pause in silence.\n"
            "9. The hook (first 2 lines) must be explosive — a secret revealed, a question confronted, "
            "a discovery made. No slow build-up.\n"
            "10. Each scene is a direct consequence of the previous scene's dialogue or action.\n\n"

            "Required JSON structure:\n"
            "{\n"
            '  \"title\": \"short dramatic curiosity-driven title\",\n'
            '  \"genre\": \"breakup|mystery|confession|betrayal|strange_discovery\",\n'
            '  \"characters\": [\n'
            '    {\"name\": \"Alex\", \"gender\": \"male\", \"age\": \"mid-20s\", \"role\": \"protagonist\", \"voice\": \"am_adam\"},\n'
            '    {\"name\": \"Sarah\", \"gender\": \"female\", \"age\": \"early-20s\", \"role\": \"partner\", \"voice\": \"af_nicole\"}\n'
            '  ],\n'
            '  \"script\": \"ALEX: I need to tell you something.\\nSARAH: What is it?\\nALEX: I\'ve been lying to you.\",\n'
            '  \"point_a\": \"one sentence: the relationship/situation before the confrontation\",\n'
            '  \"point_b\": \"one sentence: what has changed irreversibly by the end\",\n'
            '  \"scenes\": [\n'
            '    {\"description\": \"SPECIFIC visual: shot type + exact action + location + character expressions + camera style\", '
            '\"follows_from_previous\": \"opening\", \"mood\": \"tense|confrontational|heartbreaking|shocking\", '
            '\"dialogue_segment\": \"the lines of dialogue that occur during this scene\"},\n'
            '    {\"description\": \"...\", \"follows_from_previous\": \"...\", \"mood\": \"...\", \"dialogue_segment\": \"...\"}\n'
            '  ]\n'
            "}\n\n"

            "Available voices (use EXACTLY these values):\n"
            "- Female: af_bella, af_nicole, af_sky, af_sarah\n"
            "- Male: am_adam, am_michael\n\n"

            "Scene description rules:\n"
            "- MUST specify shot type: wide two-shot, medium close-up, over-the-shoulder, close-up reaction, etc.\n"
            "- MUST describe exact character actions: 'Alex slams the phone on the table', 'Sarah turns away with tears'.\n"
            "- MUST include location: apartment living room, coffee shop booth, car interior, bedroom, hallway.\n"
            "- MUST include character expressions and body language.\n"
            "- MUST include camera movement that serves the drama: 'handheld shake during argument', "
            "'slow push-in on Sarah's face as she realizes', 'tracking shot following Alex walking away'.\n"
            "- NEVER use: 'zoom in', 'slow pan across', 'characters standing still', 'static shot'.\n\n"

            "Title rules:\n"
            "- NO filler words like 'Story of' or 'Journey of'\n"
            "- NO words like 'AI', 'AI-generated', 'AI video', 'virtual' anywhere\n"
            "- Focus on EMOTION, SECRETS, BETRAYAL, MYSTERY\n"
            "- Examples: 'I Found the Messages on His Second Phone', 'She Knew I Was Lying Before I Spoke', "
            "'The Photo Under His Pillow Wasn't of Me', 'Three Years and He Never Told Me'\n\n"

            "Script rules:\n"
            "- Pure dialogue between characters. Each line: CHARACTERNAME: What they say\n"
            "- 30-50 seconds of dialogue when read naturally\n"
            "- Opening 2 lines must hit hard — secret, accusation, discovery, confession\n"
            "- Natural speech with interruptions, pauses, emotional breaks\n"
            "- NO narration, NO 'Mia', NO first-person storytelling\n"
            "- Characters feel like real people in a real moment\n\n"

            "Return ONLY raw JSON. Use double quotes for all strings. No trailing commas."
        )

        for attempt in range(1, max_attempts + 1):
            temp = 0.6 if attempt == 1 else 0.4
            prompt = f"Plan a dramatic multi-character scene about: {user_prompt}"

            if attempt > 1:
                prompt += (
                    "\n\nPrevious attempt failed. Return ONLY valid raw JSON. "
                    "Ensure characters have natural dialogue, scenes show physical interaction, "
                    "and every scene follows directly from the previous one."
                )

            try:
                logger.info("Confession story plan attempt %d/%d (temp=%.1f)", attempt, max_attempts, temp)
                raw = self.agnes.chat(
                    prompt,
                    system_prompt=system_prompt,
                    temperature=temp,
                    max_tokens=4000,
                )
                logger.info("Raw response length: %d chars", len(str(raw)))

                if not raw or not str(raw).strip():
                    raise ValueError("Empty response from API")

                data = self._extract_and_repair_json(str(raw))
                self._validate_and_fix(data, user_prompt)
                logger.info("Confession story plan succeeded on attempt %d", attempt)
                return data

            except Exception as e:
                logger.warning("Confession attempt %d/%d failed: %s", attempt, max_attempts, e)
                if attempt >= max_attempts:
                    raise RuntimeError(f"Confession story planner failed after {max_attempts} attempts: {e}")

    def _extract_and_repair_json(self, raw: str) -> Dict:
        """Extract JSON from messy LLM output with multiple repair strategies."""
        text = str(raw).strip()
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()

        if not text.startswith("{"):
            match = re.search(r"(\{[\s\S]*\})", text)
            if match:
                text = match.group(1).strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        repaired = re.sub(r",(\s*[}\]])", r"\1", text)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            pass

        repaired = text.replace("'", '"')
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            pass

        logger.warning("Confession JSON unparseable, attempting field extraction")
        return self._extract_fields_fallback(text)

    def _extract_fields_fallback(self, text: str) -> Dict:
        """Last resort: extract key fields with regex."""
        result: Dict = {}

        m = re.search(r'"title"\s*:\s*"([^"]+)"', text)
        if m:
            result["title"] = m.group(1)

        m = re.search(r'"genre"\s*:\s*"([^"]+)"', text)
        if m:
            result["genre"] = m.group(1)

        # Extract characters array
        m = re.search(r'"characters"\s*:\s*(\[[\s\S]*?\])', text, re.DOTALL)
        if m:
            chars_text = m.group(1)
            chars_text = re.sub(r",(\s*[}\]])", r"\1", chars_text)
            try:
                result["characters"] = json.loads(chars_text)
            except json.JSONDecodeError:
                result["characters"] = [
                    {"name": "Alex", "gender": "male", "age": "mid-20s", "role": "protagonist", "voice": "am_adam"},
                    {"name": "Sarah", "gender": "female", "age": "early-20s", "role": "partner", "voice": "af_nicole"},
                ]

        m = re.search(r'"script"\s*:\s*"((?:[^"\\]|\\.)*)"', text, re.DOTALL)
        if m:
            result["script"] = m.group(1).replace('\\"', '"').strip()

        m = re.search(r'"scenes"\s*:\s*(\[[\s\S]*?\])', text, re.DOTALL)
        if m:
            scenes_text = m.group(1)
            scenes_text = re.sub(r",(\s*[}\]])", r"\1", scenes_text)
            try:
                result["scenes"] = json.loads(scenes_text)
            except json.JSONDecodeError:
                pass

        result.setdefault("characters", [
            {"name": "Alex", "gender": "male", "age": "mid-20s", "role": "protagonist", "voice": "am_adam"},
            {"name": "Sarah", "gender": "female", "age": "early-20s", "role": "partner", "voice": "af_nicole"},
        ])
        return result

    def _validate_and_fix(self, data: Dict, user_prompt: str) -> None:
        """Ensure confession story has all required fields."""

        if "title" not in data or not data["title"]:
            data["title"] = self._generate_title(user_prompt)

        if "genre" not in data or not data["genre"]:
            data["genre"] = "confession"

        # Ensure characters exist
        if "characters" not in data or not isinstance(data["characters"], list) or len(data["characters"]) < 2:
            logger.warning("No characters found, creating default pair")
            data["characters"] = [
                {"name": "Alex", "gender": "male", "age": "mid-20s", "role": "protagonist", "voice": "am_adam"},
                {"name": "Sarah", "gender": "female", "age": "early-20s", "role": "partner", "voice": "af_nicole"},
            ]

        # Validate and fix character voices
        valid_voices = set(CONFESSION_VOICES["female"] + CONFESSION_VOICES["male"])
        for char in data["characters"]:
            voice = char.get("voice", "")
            if voice not in valid_voices:
                gender = char.get("gender", "female").lower()
                char["voice"] = random.choice(CONFESSION_VOICES.get(gender, CONFESSION_VOICES["female"]))

        if "script" not in data or not data["script"]:
            raise RuntimeError("Missing required field: script")

        if "scenes" not in data or not isinstance(data["scenes"], list) or len(data["scenes"]) == 0:
            logger.warning("No scenes found, auto-generating from script")
            data["scenes"] = self._generate_scenes_from_script(data["script"], data["characters"])

        data.setdefault("point_a", "")
        data.setdefault("point_b", "")

        # Clean title and script
        data["title"] = StoryPlanner._strip_ai_words(str(data["title"]).strip())
        data["script"] = StoryPlanner._strip_ai_words(str(data["script"]).strip())

        # Ensure at least 3 scenes
        while len(data["scenes"]) < 3:
            data["scenes"].append({
                "description": "Medium two-shot of the characters in emotional confrontation, natural lighting, cinematic",
                "follows_from_previous": "the previous scene's dialogue",
                "mood": "tense",
                "dialogue_segment": ""
            })

        # Validate scene descriptions
        for i, scene in enumerate(data["scenes"]):
            desc = str(scene.get("description", ""))
            scene["description"] = StoryPlanner._strip_ai_words(desc)
            scene.setdefault("follows_from_previous", "opening" if i == 0 else "the previous scene")
            scene.setdefault("mood", "tense")
            scene.setdefault("dialogue_segment", "")

            desc_lower = scene["description"].lower()
            if "zoom" in desc_lower or "static" in desc_lower or "standing still" in desc_lower:
                logger.warning("Confession scene %d was generic, rebuilding", i)
                scene["description"] = (
                    f"Cinematic {['wide', 'medium', 'close-up', 'over-the-shoulder'][i % 4]} shot: "
                    f"characters physically reacting to the confrontation — emotional body language, "
                    f"natural dramatic lighting, handheld camera movement."
                )

    def _generate_title(self, prompt: str) -> str:
        prompt = prompt.strip()
        if len(prompt) > 60:
            prompt = prompt[:57] + "..."
        prompt = re.sub(r'^(story|about|scene|video|short)\s*[:,-]\s*', '', prompt, flags=re.IGNORECASE)
        return StoryPlanner._strip_ai_words(prompt[:80] or "Confession")

    def _generate_scenes_from_script(self, script: str, characters: List[Dict]) -> List[Dict]:
        """Break dialogue script into 3-4 cinematic scenes."""
        lines = [l.strip() for l in script.split("\n") if l.strip() and ":" in l]
        chunks = []
        chunk_size = max(1, len(lines) // 3)
        for i in range(0, len(lines), chunk_size):
            chunks.append("\n".join(lines[i:i + chunk_size]))

        shot_types = ["Wide two-shot", "Medium close-up", "Over-the-shoulder", "Close-up reaction"]
        scenes = []
        for i, chunk in enumerate(chunks[:4]):
            char_names = " and ".join([c["name"] for c in characters[:2]])
            desc = f"{shot_types[i % 4]}: {char_names} in intense emotional dialogue. {chunk[:120]}..."
            scenes.append({
                "description": StoryPlanner._strip_ai_words(desc),
                "follows_from_previous": "opening" if i == 0 else "the previous confrontation",
                "mood": ["tense", "confrontational", "heartbreaking"][i % 3],
                "dialogue_segment": chunk
            })
        return scenes
