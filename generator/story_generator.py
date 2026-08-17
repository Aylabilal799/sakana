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
    # Daily life / relatable
    "Mia shares a strange coincidence that happened to her today that she cannot explain.",
    "Mia found something unexpected in her apartment that does not belong to her.",
    "Mia noticed her neighbor doing something odd and decided to investigate subtly.",
    "Mia received a message from an unknown number with a photo of herself.",
    "Mia discovered her social media was tagged in a location she has never visited.",
    "Mia woke up to find her front door slightly open even though she locked it.",
    "Mia found a note slipped under her door with her name on it.",
    "Mia's phone started showing photos she never took in her camera roll.",
    "Mia heard a sound coming from inside her closet at 3 AM.",
    "Mia found a delivery package addressed to her with no sender information.",
    # Mystery / suspense
    "Mia explores an abandoned floor in her building that should not exist.",
    "Mia found an old phone in a thrift store that still receives texts.",
    "Mia discovered a room behind a bookshelf in her new apartment.",
    "Mia keeps seeing the same stranger outside her apartment window.",
    "Mia found a journal in a cafe with entries written in her handwriting.",
    "Mia's reflection in the mirror moved independently for a split second.",
    "Mia received a friend request from an account using her exact photos.",
    "Mia found a key taped under her desk with a note saying do not use.",
    "Mia's GPS keeps redirecting her to the same unknown address.",
    "Mia discovered her apartment was previously rented by someone with her exact name.",
    # Emotional / story-driven
    "Mia revisits her childhood home and finds something she left behind years ago.",
    "Mia receives a voice message from a number that no longer exists.",
    "Mia found a hidden compartment in her jewelry box containing an old letter.",
    "Mia's playlist started playing songs she never added in a specific order.",
    "Mia noticed all the clocks in her apartment are set to different times.",
    "Mia found a polaroid of herself sleeping on her nightstand.",
    "Mia's smart speaker answered a question she only thought in her head.",
    "Mia discovered a second WiFi network named after her apartment number.",
    "Mia found her own handwriting on a wall she painted over last month.",
    "Mia received a package with items from a day she has no memory of.",
]

# Genre distribution for variety
GENRES = ["daily_vlog", "mystery", "story", "daily_vlog", "mystery", "horror", "reaction"]


class StoryGenerator:
    """Auto-generates unique Mia vlog scripts using Agnes, with SQLite deduplication."""

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
                    status TEXT DEFAULT 'generated'
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

    def generate_unique_story(self) -> Dict:
        """Generate a unique story that has never been used before."""
        # Get least-used themes first
        theme = self._pick_theme()
        genre = random.choice(GENRES)

        logger.info("Auto-pilot generating story for theme: %s | genre: %s", theme, genre)

        # Build prompt for story planner
        instruction = f"""Create one short-form vertical daily-vlog episode starring Mia, a recurring adult female influencer.

Theme: {theme}
Genre: {genre}

Return ONLY valid JSON with this exact shape:
{{
  "title": "short episode title",
  "genre": "{genre}",
  "tone": "warm natural|cool suspense|dark atmospheric",
  "outfit": "one concise continuity outfit description",
  "script": "35-55 second first-person narration spoken by Mia. Natural conversational vlog speech. No awkward fragments.",
  "opening_hook": "the FIRST 1-2 sentences that immediately establish the mystery/premise",
  "final_reveal": "the climactic final 2-3 sentences with a payoff",
  "key_objects": [
    {{"name": "object_id", "type": "photograph|phone|letter|key|book|document|prop", "description": "visual description", "introduced_scene": 1}}
  ],
  "emotional_arc": ["curious", "uneasy", "shocked"],
  "scenes": [
    {{
      "index": 1,
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
      "story_event": "what narrative event happens in this scene",
      "transition": "cut|crossfade"
    }}
  ]
}}

CRITICAL RULES:
1. OPENING HOOK: Start with an attention-grabbing first sentence. No boring exposition.
2. NATURAL SPEECH: Mia sounds like a real person talking to her camera. Casual, conversational.
3. FINAL REVEAL: Deliver a payoff — unanswered question, disturbing realization, or impossible detail.
4. CONTINUITY: Same location unless script justifies movement. Objects persist.
5. Use 4-6 scenes. Each scene a clear narrative beat.
6. Emotional progression builds logically.
7. One outfit unless script changes time/day.
8. Avoid copyrighted characters, brands, on-screen text.
"""
        raw = self.agnes.chat(
            instruction,
            max_tokens=4000,
            temperature=0.65,
            system_prompt="You are a strict JSON-only short-form video writer. You write natural conversational vlog scripts with strong hooks and satisfying endings. You enforce physical continuity and emotional progression.",
        )
        data = self._parse_json(raw)
        data = self._validate_and_fix(data, theme)

        # Check for duplicates using script hash
        script_hash = self._hash_script(data["script"])
        if self._is_duplicate(script_hash):
            logger.warning("Duplicate script detected (hash: %s...), regenerating...", script_hash[:16])
            return self.generate_unique_story()  # Retry with different theme

        # Store in database
        self._store_story(theme, genre, data, script_hash)
        self._mark_theme_used(theme)

        return data

    def _pick_theme(self) -> str:
        """Pick the least-used theme to ensure variety."""
        with self._connect() as conn:
            # Get usage counts
            rows = conn.execute(
                "SELECT theme, use_count FROM theme_usage"
            ).fetchall()
            usage = {row["theme"]: row["use_count"] for row in rows}

        # Find minimum usage count
        min_count = min((usage.get(t, 0) for t in MIA_THEMES), default=0)

        # Get all themes with minimum usage
        candidates = [t for t in MIA_THEMES if usage.get(t, 0) == min_count]
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

    def _store_story(self, theme: str, genre: str, data: Dict, script_hash: str):
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO generated_stories
                (theme, genre, title, script, script_hash, status)
                VALUES (?, ?, ?, ?, ?, 'generated')
            """, (
                theme, genre, data.get("title", ""), data["script"], script_hash
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
            "total_themes_available": len(MIA_THEMES),
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

    def _validate_and_fix(self, data: Dict, theme: str) -> Dict:
        script = str(data.get("script") or "").strip()
        scenes = data.get("scenes")
        if not script or not isinstance(scenes, list) or not scenes:
            # Fallback: use theme as script
            script = f"Guys, {theme.lower()} I am genuinely confused right now."
            scenes = [{
                "index": 1, "narration": script, "location": "Mia's apartment",
                "location_change_reason": "same_location", "action": "Mia records her vlog",
                "shot_type": "selfie medium", "visual_prompt": script,
                "camera_motion": "subtle handheld push-in",
                "lighting": "natural warm realistic light",
                "expression": "natural and concerned", "objects_visible": [],
                "objects_held": [], "emotional_state": "curious",
                "story_event": script[:100], "transition": "cut",
            }]

        return {
            "title": str(data.get("title") or "Mia's Daily Vlog").strip()[:100],
            "genre": str(data.get("genre") or "daily_vlog").strip().lower(),
            "tone": str(data.get("tone") or "warm natural").strip(),
            "outfit": str(data.get("outfit") or "cream fitted top and high-waisted blue jeans").strip(),
            "script": script,
            "opening_hook": str(data.get("opening_hook") or scenes[0]["narration"]).strip()[:300],
            "final_reveal": str(data.get("final_reveal") or scenes[-1]["narration"]).strip()[:300],
            "emotional_arc": data.get("emotional_arc", []),
            "key_objects": data.get("key_objects", []),
            "scenes": scenes,
            "source_theme": theme,
        }
