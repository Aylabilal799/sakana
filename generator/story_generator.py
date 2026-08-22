import json
import logging
import random
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from generator.agnes_client import AgnesClient

logger = logging.getLogger(__name__)

# Mia influencer daily vlog themes — rotates to avoid repetition
MIA_THEMES = [
    "Mia had a quiet morning alone and realized something important about herself.",
    "Mia spent the whole afternoon cleaning her apartment and found an old memory.",
    "Mia tried to have a normal productive day but everything kept going wrong in small ways.",
    "Mia went for a late evening walk and ended up talking to a stranger who said something unexpected.",
    "Mia stayed up too late and started overthinking her life while staring at the ceiling.",
    "Mia made herself breakfast and suddenly felt extremely lonely for no clear reason.",
    "Mia received a message from someone she used to care about and didn't know how to reply.",
    "Mia spent hours rearranging her room because she felt stuck in her current life.",
    "Mia watched the rain from her window and started remembering a specific day from last year.",
    "Mia almost cancelled all her plans today just to stay in bed, but forced herself to go out.",
    "Mia found something small in her apartment that she has no memory of buying.",
    "Mia noticed the same person appearing in the background of several of her recent photos.",
    "Mia's phone showed a location she doesn't remember visiting last night.",
    "Mia received a delivery she never ordered and the note inside was addressed to her by name.",
    "Mia found a photo of herself on a public wall that she never posed for.",
    "Mia's playlist started playing songs in an order that matched exactly what she was thinking.",
    "Mia locked her door last night but woke up to find it slightly open.",
    "Mia found a handwritten note under her pillow with only today's date on it.",
    "Mia received a message from an unknown number with a photo of herself.",
    "Mia discovered her social media was tagged in a location she has never visited.",
    "Mia went back to a place she used to visit often and everything felt different.",
    "Mia deleted old photos from her phone and stopped at one she couldn't bring herself to erase.",
    "Mia wrote a long message to someone and then deleted it without sending.",
    "Mia spent the day pretending everything was fine while feeling the opposite.",
    "Mia found an old voice note she recorded months ago and barely recognized herself.",
    "Mia revisits her childhood home and finds something she left behind years ago.",
    "Mia found a hidden compartment in her jewelry box containing an old letter.",
    "Mia found a polaroid of herself sleeping on her nightstand.",
]

# Genre distribution for variety
GENRES = ["daily_vlog", "daily_vlog", "soft_mystery", "emotional", "daily_vlog", "soft_mystery"]


# Confession channel themes — multi-character dramatic stories
CONFESSION_THEMES = [
    # Breakup / relationship drama
    "A couple's three-year relationship ends in one conversation after a secret is revealed.",
    "Someone finds messages on their partner's phone that prove they've been lying.",
    "A person confesses to cheating and begs for forgiveness while their partner packs a bag.",
    "Two exes meet for closure and old wounds reopen.",
    "A boyfriend admits he never told her about his child from a previous relationship.",
    "A girlfriend confesses she kissed someone else and watches the relationship crumble in real time.",
    "A husband tries to explain why he was at his ex's apartment last night.",
    "A wife finds a second phone and confronts her husband.",
    # Mystery / strange discovery
    "Someone finds a photo of themselves sleeping on their nightstand and confronts their roommate.",
    "A woman discovers her boyfriend has been stalking her social media from fake accounts.",
    "A man finds a box of letters addressed to his girlfriend from someone in prison.",
    "A couple moves into a new apartment and finds a wall covered in photos of previous tenants.",
    "A girl finds her boyfriend's journal and reads his darkest secrets out loud to him.",
    "Someone receives anonymous messages revealing their partner's lies and confronts them.",
    "A person finds out their best friend and partner were secretly talking behind their back.",
    # Confession / betrayal
    "A best friend confesses they've been in love with their friend's partner for years.",
    "A sibling reveals they know the truth about a family secret that was buried for a decade.",
    "A coworker confesses they sabotaged someone's promotion and begs for mercy.",
    "A daughter confronts her mother about the real reason her father left.",
    "A friend admits they were the one who started the rumor that ruined someone's reputation.",
    "Someone confesses to a crime their partner committed and demands they turn themselves in.",
    "A person tells their family they've been faking their entire identity for three years.",
    # Emotional / dramatic
    "Two estranged brothers reunite at their father's funeral and old grudges surface.",
    "A mother and daughter have a raw conversation about why they stopped speaking.",
    "A man tells his fiancée he doesn't want children on the night before their wedding.",
    "A woman confesses to her best friend that she's leaving town without saying goodbye to anyone else.",
]

CONFESSION_GENRES = ["breakup", "mystery", "confession", "betrayal", "breakup", "mystery", "confession"]


class StoryGenerator:
    """Auto-generates unique Mia vlog scripts using Agnes, with SQLite deduplication."""

    MAX_GENERATION_ATTEMPTS = 5

    def __init__(self, agnes: AgnesClient, db_path: Optional[str] = None):
        self.agnes = agnes
        self.db_path = db_path or "/root/sakana/data/autopilot.db"
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS generated_stories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    theme TEXT NOT NULL,
                    genre TEXT,
                    title TEXT,
                    script TEXT NOT NULL,
                    script_hash TEXT UNIQUE NOT NULL,
                    used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    video_job_id TEXT,
                    youtube_video_id TEXT,
                    status TEXT DEFAULT 'generated',
                    channel TEXT DEFAULT 'mia'
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS theme_usage (
                    theme TEXT PRIMARY KEY,
                    use_count INTEGER DEFAULT 0,
                    last_used TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS autopilot_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scheduled_time TEXT NOT NULL,
                    job_id TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    error_message TEXT
                )
            """)
            conn.commit()

    def generate_unique_story(self, channel: str = "mia") -> Dict:
        """Generate a unique story that has never been used before."""
        last_error: Optional[Exception] = None
        for attempt in range(1, self.MAX_GENERATION_ATTEMPTS + 1):
            try:
                if channel == "confession":
                    data, script_hash = self._generate_confession_candidate()
                else:
                    data, script_hash = self._generate_mia_candidate()
            except Exception as exc:
                last_error = exc
                logger.warning("Story generation attempt %d/%d failed: %s",
                               attempt, self.MAX_GENERATION_ATTEMPTS, exc)
                continue

            if self._is_duplicate(script_hash):
                logger.warning(
                    "Duplicate script detected on attempt %d/%d (hash: %s...), retrying...",
                    attempt, self.MAX_GENERATION_ATTEMPTS, script_hash[:16],
                )
                continue

            self._store_story(data["source_theme"], data.get("genre", ""), data, script_hash, channel)
            self._mark_theme_used(data["source_theme"])
            return data

        raise RuntimeError(
            f"Failed to generate a unique story after {self.MAX_GENERATION_ATTEMPTS} attempts"
        ) from last_error

    def _generate_mia_candidate(self):
        """Generate a single Mia candidate story."""
        theme = self._pick_theme(MIA_THEMES)
        genre = random.choice(GENRES)

        logger.info("Auto-pilot generating Mia story for theme: %s | genre: %s", theme, genre)

        instruction = f"""Create one short-form vertical daily-vlog episode starring Mia, a recurring adult female influencer.

This is a VLOG series, not a horror or suspense series. Even when the theme involves
something strange, it should still feel like a real girl talking to her camera about
her day — curious or a little unsettled at most, never scared, never horror-coded.

Theme: {theme}
Genre: {genre}

THIS MUST BE ONE CONTINUOUS STORY, NOT SEPARATE MOMENTS STRUNG TOGETHER. Every scene must
be a direct continuation of the event/object introduced in the scene before it — never a
new, unrelated moment. If you removed the connecting object or action from a scene, the
following scene should stop making sense. Concretely: define a starting point (point_a —
Mia's situation before anything happens) and an ending point (point_b — what's concretely
different by the end), then write scenes that visibly travel from one to the other without
skipping to disconnected side-moments (no "she found the note" in scene 1 followed by an
unrelated "she's texting a friend" in scene 2 — scene 2 must be about what she does because
of the note).

HOOK TIMING: The opening_hook must be short enough to be spoken in under 3 seconds
(roughly 8-10 words) and scene 1's visual must be an already-in-motion or visually striking
moment — not a static "Mia sitting/standing looking at camera" shot. The first thing the
viewer sees and hears must justify itself before they can swipe away.

Return ONLY valid JSON with this exact shape:
{{
  "title": "short curiosity-driven episode title (no horror-movie phrasing)",
  "genre": "{genre}",
  "tone": "warm natural|soft emotional|light curiosity",
  "outfit": "one concise continuity outfit description",
  "point_a": "one sentence: Mia's situation/understanding at the very start, before anything happens",
  "point_b": "one sentence: Mia's situation/understanding at the very end, and what concretely changed from point_a",
  "script": "30-45 second first-person narration spoken by Mia. Natural, conversational vlog speech, like she's talking to her phone. Small natural fillers are fine (right?, I swear, okay so...). No awkward fragments.",
  "opening_hook": "the FIRST 1-2 short sentences (under 3 seconds spoken) that immediately establish curiosity or emotion — not dread",
  "final_reveal": "the final 2-3 sentences with an emotional realization or open question that matches point_b, not a scare",
  "key_objects": [
    {{"name": "object_id", "type": "photograph|phone|letter|key|book|document|prop", "description": "visual description", "introduced_scene": 1}}
  ],
  "emotional_arc": ["curious", "uneasy", "shocked"],
  "scenes": [
    {{
      "index": 1,
      "beat": "setup|inciting_incident|escalation|turn|resolution",
      "follows_from_previous": "one short phrase naming exactly what carries over from the previous scene (object/action/question) — for scene 1, write 'opening'",
      "narration": "exact contiguous portion of the script",
      "location": "specific location",
      "location_change_reason": "explicit script justification or same_location",
      "action": "what Mia physically does",
      "shot_type": "selfie medium|handheld medium|POV|medium close-up|close-up|reaction close-up|object close-up",
      "visual_prompt": "specific visual beat",
      "camera_motion": "subtle push-in|gentle handheld drift|slow pan",
      "lighting": "cohesive lighting for the episode",
      "expression": "Mia's natural expression",
      "objects_visible": ["object_id"],
      "objects_held": ["object_id"],
      "emotional_state": "curious",
      "story_event": "what narrative event happens in this scene, and how it directly continues the previous scene's event/object",
      "transition": "cut|crossfade"
    }}
  ]
}}

CRITICAL RULES:
1. ONE CONTINUOUS THREAD: Every scene's story_event must be a direct consequence of the
   previous scene's event. No scene may introduce an unrelated moment (a random phone check,
   an unrelated errand, a disconnected feeling) that doesn't continue what came before. Use
   the "follows_from_previous" field on every scene to prove the link before writing it.
2. HOOK LANDS FAST: opening_hook must be short enough to land in under 3 seconds, and
   scene 1 must show Mia already mid-action or reacting to something, not a static
   introduction shot. No slow build-up before the hook.
3. OPENING HOOK: Start with an attention-grabbing first sentence that creates curiosity or emotion — not dread. No boring exposition.
4. NATURAL SPEECH: Mia sounds like a real 20-something talking casually to her camera. Casual, conversational, first-person.
5. FINAL REVEAL: Deliver a payoff — an emotional realization or an open question that makes people want the next video, and that matches point_b. Avoid horror-style scares or "impossible" supernatural details.
6. STAY GROUNDED: If the theme involves something odd, keep it small and real-world (a note, a message, a playlist, a delivery) — not supernatural escalation (secret rooms, doppelgangers, objects moving on their own).
7. CONTINUITY: Same location unless script justifies movement. Objects persist and, once introduced, must be referenced again if they matter to the outcome.
8. Use 4-6 scenes. Each scene a clear, distinct narrative beat — reject filler or scenes that could be deleted without losing story information.
9. Emotional progression builds logically and stays within "curious / uneasy / reflective" — not "terrified."
10. One outfit unless script changes time/day.
11. Avoid copyrighted characters, brands, on-screen text.
"""
        raw = self.agnes.chat(
            instruction,
            max_tokens=4000,
            temperature=0.6,
            system_prompt=(
                "You are a strict JSON-only short-form video writer. You write natural "
                "conversational vlog scripts with strong hooks and satisfying endings. Every "
                "script must travel from a clear starting situation (point_a) to a clear, "
                "changed ending situation (point_b) as ONE continuous thread — every scene "
                "must be a direct consequence of the one before it, never a disconnected new "
                "moment. The hook must land in under 3 seconds. You enforce physical "
                "continuity, one narrative beat per scene, and logical emotional progression."
            ),
        )
        data = self._parse_json(raw)
        data = self._validate_and_fix_mia(data, theme)
        script_hash = self._hash_script(data["script"])
        return data, script_hash

    def _generate_confession_candidate(self):
        """Generate a single confession candidate story with multi-character dialogue."""
        theme = self._pick_theme(CONFESSION_THEMES)
        genre = random.choice(CONFESSION_GENRES)

        logger.info("Auto-pilot generating confession story for theme: %s | genre: %s", theme, genre)

        instruction = f"""Create one short-form vertical cinematic scene featuring 2-3 characters in a dramatic confrontation.

This is a CINEMATIC scene, not a vlog. It should feel like a clip from a relationship
drama, mystery, or confession scene — emotionally raw, realistic, and intense.

Theme: {theme}
Genre: {genre}

Create 2-3 characters with distinct voices and roles. The script must be DIALOGUE ONLY —
no narration. Each line starts with the character name in ALL CAPS followed by a colon.
The dialogue should feel natural, with interruptions, emotional breaks, and realistic pacing.

The scene must have a clear starting situation (point_a) and a changed ending (point_b).
Every scene must directly continue from the previous one — no disconnected moments.

Return ONLY valid JSON with this exact shape:
{{
  "title": "short dramatic curiosity-driven title",
  "genre": "{genre}",
  "tone": "tense|heartbreaking|confrontational|mysterious",
  "characters": [
    {{"name": "Alex", "gender": "male", "age": "mid-20s", "role": "protagonist", "voice": "am_adam"}},
    {{"name": "Sarah", "gender": "female", "age": "early-20s", "role": "partner", "voice": "af_nicole"}}
  ],
  "point_a": "one sentence: the relationship/situation before the confrontation",
  "point_b": "one sentence: what has changed irreversibly by the end",
  "script": "30-50 seconds of dialogue. ALEX: I need to tell you something.\\nSARAH: What is it?\\nALEX: I've been lying.",
  "opening_hook": "the FIRST 2 lines of dialogue that immediately create tension or reveal something",
  "final_reveal": "the final 2-3 lines that deliver the emotional payoff or devastating truth",
  "scenes": [
    {{
      "index": 1,
      "beat": "setup|confrontation|escalation|climax|fallout",
      "follows_from_previous": "opening",
      "dialogue_segment": "the lines of dialogue in this scene",
      "location": "specific location",
      "action": "what the characters physically do",
      "shot_type": "wide two-shot|medium close-up|over-the-shoulder|close-up reaction|tracking shot",
      "visual_prompt": "specific visual beat with character actions and expressions",
      "camera_motion": "handheld drift|push-in|tracking|static cinematic",
      "lighting": "dramatic natural|warm tense|cool moody|harsh overhead",
      "expression": "character expressions",
      "emotional_state": "tense",
      "story_event": "what happens in this scene",
      "transition": "cut"
    }}
  ]
}}

CRITICAL RULES:
1. The hook (first 2 lines) must be explosive — a secret, accusation, or discovery.
2. Every scene must show characters physically interacting and reacting.
3. Dialogue must feel like real people speaking, not scripted lines.
4. The ending must deliver a clear emotional change from point_a to point_b.
5. NO narration, NO first-person storytelling, NO "Mia".
6. Use cinematic shot descriptions with specific camera angles and movement.
7. Keep it grounded and realistic — no supernatural elements.
8. Use 3-5 scenes, each a distinct narrative beat.
9. Avoid copyrighted characters, brands, on-screen text.

Available voices (use EXACTLY these):
- Female: af_bella, af_nicole, af_sky, af_sarah
- Male: am_adam, am_michael
"""
        raw = self.agnes.chat(
            instruction,
            max_tokens=4000,
            temperature=0.7,
            system_prompt=(
                "You are a strict JSON-only cinematic screenwriter. You write intense, "
                "realistic dialogue scenes between 2-3 characters that feel like clips from "
                "a drama series. Every scene shows physical interaction and emotional "
                "reaction. You enforce continuity, cinematic visuals, and powerful hooks."
            ),
        )
        data = self._parse_json(raw)
        data = self._validate_and_fix_confession(data, theme)
        script_hash = self._hash_script(data["script"])
        return data, script_hash

    def _pick_theme(self, theme_list: List[str]) -> str:
        """Pick the least-used theme to ensure variety."""
        with self._connect() as conn:
            rows = conn.execute("SELECT theme, use_count FROM theme_usage").fetchall()
            usage = {row["theme"]: row["use_count"] for row in rows}

        min_count = min((usage.get(t, 0) for t in theme_list), default=0)
        candidates = [t for t in theme_list if usage.get(t, 0) == min_count]
        return random.choice(candidates)

    def _mark_theme_used(self, theme: str):
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO theme_usage (theme, use_count, last_used)
                VALUES (?, 1, CURRENT_TIMESTAMP)
                ON CONFLICT(theme) DO UPDATE SET
                    use_count = use_count + 1,
                    last_used = CURRENT_TIMESTAMP
            """, (theme,))
            conn.commit()

    @staticmethod
    def _hash_script(script: str) -> str:
        import hashlib
        return hashlib.sha256(script.strip().lower().encode()).hexdigest()

    def _is_duplicate(self, script_hash: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM generated_stories WHERE script_hash = ?",
                (script_hash,)
            ).fetchone()
            return row is not None

    def _store_story(self, theme: str, genre: str, data: Dict, script_hash: str, channel: str = "mia"):
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO generated_stories
                (theme, genre, title, script, script_hash, status, channel)
                VALUES (?, ?, ?, ?, ?, 'generated', ?)
            """, (
                theme, genre, data.get("title", ""), data["script"], script_hash, channel
            ))
            conn.commit()

    def update_story_status(self, script_hash: str, job_id: str = None,
                            youtube_video_id: str = None, status: str = None):
        """Update story status after video generation/upload."""
        with self._connect() as conn:
            updates = []
            params = []
            if job_id:
                updates.append("video_job_id = ?")
                params.append(job_id)
            if youtube_video_id:
                updates.append("youtube_video_id = ?")
                params.append(youtube_video_id)
            if status:
                updates.append("status = ?")
                params.append(status)
            if updates:
                params.append(script_hash)
                conn.execute(f"""
                    UPDATE generated_stories
                    SET {', '.join(updates)}
                    WHERE script_hash = ?
                """, params)
                conn.commit()

    def get_stats(self) -> Dict:
        """Get autopilot generation statistics."""
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM generated_stories").fetchone()[0]
            uploaded = conn.execute(
                "SELECT COUNT(*) FROM generated_stories WHERE youtube_video_id IS NOT NULL"
            ).fetchone()[0]
            pending = conn.execute(
                "SELECT COUNT(*) FROM generated_stories WHERE status = 'generated'"
            ).fetchone()[0]
            theme_count = conn.execute("SELECT COUNT(DISTINCT theme) FROM generated_stories").fetchone()[0]
        return {
            "total_stories_generated": total,
            "uploaded_to_youtube": uploaded,
            "pending_generation": pending,
            "unique_themes_used": theme_count,
            "total_themes_available": len(MIA_THEMES) + len(CONFESSION_THEMES),
        }

    @staticmethod
    def _parse_json(raw: str) -> Dict:
        import re
        text = raw.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise RuntimeError("Story generator did not return a JSON object")
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError as exc:
            logger.error("Invalid story JSON: %s", text[:1500])
            raise RuntimeError(f"Story generator returned invalid JSON: {exc}") from exc

    def _validate_and_fix_mia(self, data: Dict, theme: str) -> Dict:
        script = str(data.get("script") or "").strip()
        scenes = data.get("scenes")
        if not script or not isinstance(scenes, list) or not scenes:
            setup_line = f"Okay guys, so {theme.lower()}"
            turn_line = "I need to figure out what's actually going on before I do anything else."
            reveal_line = "I still don't have an answer, and that honestly scares me more than if I did."
            script = f"{setup_line} {turn_line} {reveal_line}"
            scenes = [
                {
                    "index": 1, "beat": "setup", "follows_from_previous": "opening",
                    "narration": setup_line,
                    "location": "Mia's apartment", "location_change_reason": "same_location",
                    "action": "Mia notices something is off and starts filming",
                    "shot_type": "selfie medium", "visual_prompt": setup_line,
                    "camera_motion": "subtle handheld push-in",
                    "lighting": "natural warm realistic light",
                    "expression": "curious and uneasy", "objects_visible": [],
                    "objects_held": [], "emotional_state": "curious",
                    "story_event": "Mia establishes what's out of place.", "transition": "cut",
                },
                {
                    "index": 2, "beat": "escalation",
                    "follows_from_previous": "the thing Mia noticed in scene 1",
                    "narration": turn_line,
                    "location": "Mia's apartment", "location_change_reason": "same_location",
                    "action": "Mia investigates further, visibly more unsettled",
                    "shot_type": "handheld medium", "visual_prompt": turn_line,
                    "camera_motion": "gentle handheld drift",
                    "lighting": "natural warm realistic light",
                    "expression": "worried and focused", "objects_visible": [],
                    "objects_held": [], "emotional_state": "uneasy",
                    "story_event": "Mia commits to getting an answer about the same thing.",
                    "transition": "cut",
                },
                {
                    "index": 3, "beat": "resolution",
                    "follows_from_previous": "what Mia found while investigating in scene 2",
                    "narration": reveal_line,
                    "location": "Mia's apartment", "location_change_reason": "same_location",
                    "action": "Mia looks directly at camera, shaken",
                    "shot_type": "reaction close-up", "visual_prompt": reveal_line,
                    "camera_motion": "subtle push-in",
                    "lighting": "natural warm realistic light",
                    "expression": "shocked and unsettled", "objects_visible": [],
                    "objects_held": [], "emotional_state": "shocked",
                    "story_event": "Mia ends in a worse, changed state than she started in, "
                                   "directly caused by scene 2's investigation.",
                    "transition": "cut",
                },
            ]
            data.setdefault("point_a", setup_line)
            data.setdefault("point_b", reveal_line)

        return {
            "title": str(data.get("title") or "Mia's Daily Vlog").strip()[:100],
            "genre": str(data.get("genre") or "daily_vlog").strip().lower(),
            "tone": str(data.get("tone") or "warm natural").strip(),
            "outfit": str(data.get("outfit") or "cream fitted top and high-waisted blue jeans").strip(),
            "point_a": str(data.get("point_a") or "").strip()[:300],
            "point_b": str(data.get("point_b") or "").strip()[:300],
            "script": script,
            "opening_hook": str(data.get("opening_hook") or scenes[0]["narration"]).strip()[:300],
            "final_reveal": str(data.get("final_reveal") or scenes[-1]["narration"]).strip()[:300],
            "emotional_arc": data.get("emotional_arc", []),
            "key_objects": data.get("key_objects", []),
            "scenes": scenes,
            "source_theme": theme,
            "channel": "mia",
        }

    def _validate_and_fix_confession(self, data: Dict, theme: str) -> Dict:
        """Validate and fix confession multi-character story data."""
        from generator.story_planner import CONFESSION_VOICES

        if "title" not in data or not data["title"]:
            data["title"] = theme[:60] if len(theme) <= 60 else theme[:57] + "..."

        if "genre" not in data or not data["genre"]:
            data["genre"] = "confession"

        # Ensure characters exist with valid voices
        if "characters" not in data or not isinstance(data["characters"], list) or len(data["characters"]) < 2:
            data["characters"] = [
                {"name": "Alex", "gender": "male", "age": "mid-20s", "role": "protagonist", "voice": "am_adam"},
                {"name": "Sarah", "gender": "female", "age": "early-20s", "role": "partner", "voice": "af_nicole"},
            ]

        valid_voices = set(CONFESSION_VOICES["female"] + CONFESSION_VOICES["male"])
        for char in data["characters"]:
            if char.get("voice") not in valid_voices:
                gender = char.get("gender", "female").lower()
                char["voice"] = random.choice(CONFESSION_VOICES.get(gender, CONFESSION_VOICES["female"]))

        if "script" not in data or not data["script"]:
            raise RuntimeError("Missing required field: script")

        if "scenes" not in data or not isinstance(data["scenes"], list) or len(data["scenes"]) == 0:
            data["scenes"] = [
                {
                    "index": 1, "beat": "setup", "follows_from_previous": "opening",
                    "dialogue_segment": data["script"][:150],
                    "location": "apartment living room", "action": "characters confronting each other",
                    "shot_type": "wide two-shot", "visual_prompt": "two characters in tense confrontation",
                    "camera_motion": "handheld drift", "lighting": "warm tense", "expression": "emotional",
                    "emotional_state": "tense", "story_event": "confrontation begins", "transition": "cut",
                },
                {
                    "index": 2, "beat": "climax", "follows_from_previous": "the accusation",
                    "dialogue_segment": data["script"][150:300],
                    "location": "same room", "action": "emotional reaction and revelation",
                    "shot_type": "close-up reaction", "visual_prompt": "character's face showing shock",
                    "camera_motion": "push-in", "lighting": "dramatic", "expression": "devastated",
                    "emotional_state": "heartbreaking", "story_event": "truth revealed", "transition": "cut",
                },
                {
                    "index": 3, "beat": "fallout", "follows_from_previous": "the revelation",
                    "dialogue_segment": data["script"][300:],
                    "location": "same room", "action": "one character leaves or relationship ends",
                    "shot_type": "medium shot", "visual_prompt": "character walking away or sitting in silence",
                    "camera_motion": "tracking", "lighting": "cool moody", "expression": "defeated",
                    "emotional_state": "defeated", "story_event": "relationship irreversibly changed", "transition": "cut",
                },
            ]

        data.setdefault("point_a", "")
        data.setdefault("point_b", "")

        # Clean
        data["title"] = StoryPlanner._strip_ai_words(str(data["title"]).strip())
        data["script"] = StoryPlanner._strip_ai_words(str(data["script"]).strip())

        # Ensure scenes have all required fields
        for i, scene in enumerate(data["scenes"]):
            scene.setdefault("index", i + 1)
            scene.setdefault("beat", "escalation")
            scene.setdefault("follows_from_previous", "opening" if i == 0 else "the previous scene")
            scene.setdefault("dialogue_segment", "")
            scene.setdefault("location", "apartment")
            scene.setdefault("action", "characters talking")
            scene.setdefault("shot_type", "medium close-up")
            scene.setdefault("visual_prompt", scene.get("description", "cinematic scene"))
            scene.setdefault("camera_motion", "handheld drift")
            scene.setdefault("lighting", "warm tense")
            scene.setdefault("expression", "emotional")
            scene.setdefault("emotional_state", "tense")
            scene.setdefault("story_event", "confrontation")
            scene.setdefault("transition", "cut")

        return {
            "title": data["title"][:100],
            "genre": data["genre"].strip().lower(),
            "tone": str(data.get("tone") or "tense").strip(),
            "characters": data["characters"],
            "point_a": str(data.get("point_a", "")).strip()[:300],
            "point_b": str(data.get("point_b", "")).strip()[:300],
            "script": data["script"],
            "opening_hook": str(data.get("opening_hook") or data["script"][:100]).strip()[:300],
            "final_reveal": str(data.get("final_reveal") or data["script"][-200:]).strip()[:300],
            "scenes": data["scenes"],
            "source_theme": theme,
            "channel": "confession",
        }
