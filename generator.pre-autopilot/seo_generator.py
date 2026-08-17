import logging
import re
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger(__name__)


class SEOGenerator:
    GENRE_TAGS = {
        "horror": [
            "horror short", "scary story", "creepy abandoned places",
            "abandoned horror", "horror vlog", "creepy short",
            "ai horror story", "unsettling story", "dark mystery",
        ],
        "mystery": [
            "mystery vlog", "unsolved mystery", "creepy mystery",
            "abandoned mystery", "mysterious discovery", "investigation vlog",
            "ai mystery story", "suspense short", "intrigue story",
        ],
        "travel": [
            "travel vlog", "exploration vlog", "adventure vlog",
            "ai travel story", "discovering places", "travel shorts",
        ],
        "reaction": [
            "reaction vlog", "ai reaction", "story reaction",
            "mystery reaction", "creepy reaction", "reaction shorts",
        ],
        "daily_vlog": [
            "daily vlog", "ai daily life", "ai influencer",
            "mia ai", "mia vlog", "ai creator",
        ],
        "story": [
            "ai story", "story short", "narrative short",
            "ai generated story", "storytelling", "ai narrative",
        ],
    }

    STORY_TAGS = {
        r"abandoned\s+(hotel|house|building|place|room|hall|lobby)": "abandoned hotel exploration",
        r"(hotel|house|building)\s+(abandoned|empty|deserted)": "abandoned places",
        r"(photograph|photo|picture|image)\s+(of\s+myself|of\s+me|that\s+looks\s+like\s+me)": "found photo mystery",
        r"(found|discover|see)\s+(a\s+)?(photo|photograph|picture)": "mysterious discovery",
        r"(myself|me|my\s+face|i\s+am|that's\s+me)": "identity mystery",
        r"(creepy|scary|terrifying|unsettling|weird|strange)": "creepy story",
        r"(ghost|spirit|haunted|haunting)": "haunted places",
        r"(basement|cellar|underground|tunnel)": "underground exploration",
        r"(mirror|reflection|reflect)": "mirror mystery",
        r"(door|room|hallway|corridor)\s+(open|close|creak|slam)": "creepy hallway",
        r"(dust|dusty|decay|rotten|broken|cracked)": "decay aesthetic",
        r"(footstep|footsteps|walking|running|chase)": "suspense chase",
        r"(whisper|whispers|voice|hear|heard|sound)": "creepy sounds",
        r"(alone|by\s+myself|no\s+one|empty)": "alone horror",
    }

    def generate(self, plan: Dict) -> Dict:
        script = plan.get("script", "").strip()
        title = self._title(plan)
        genre = plan.get("genre", "daily_vlog")
        hashtags = self._hashtags(genre, script)
        tags = self._semantic_tags(script, genre, title, plan)
        first_sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", script) if s.strip()]
        short = " ".join(first_sentences[:2])[:280]
        description = (
            f"{short}\n\n"
            "Follow Mia's AI daily-vlog series for new adventures, mysteries and reactions.\n\n"
            + " ".join(hashtags)
        )
        return {
            "title": title,
            "description": description,
            "hashtags": hashtags,
            "tags": tags,
            "short_description": short,
            "pinned_comment": "What would you have done in Mia's place? Tell me below 👇",
        }

    def write_text_file(self, metadata: Dict, output_path: str) -> str:
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        content = (
            f"Title:\n{metadata.get('title', '')}\n\n"
            f"Description:\n{metadata.get('description', '')}\n\n"
            f"Hashtags:\n{' '.join(metadata.get('hashtags', []))}\n\n"
            f"Tags:\n{', '.join(metadata.get('tags', []))}\n\n"
            f"Short Description:\n{metadata.get('short_description', '')}\n\n"
            f"Suggested Pinned Comment:\n{metadata.get('pinned_comment', '')}\n"
        )
        destination.write_text(content, encoding="utf-8")
        destination.chmod(0o644)
        logger.info("YouTube SEO file: %s", destination)
        return str(destination)

    @staticmethod
    def _title(plan: Dict) -> str:
        title = str(plan.get("title") or "Mia's Daily Vlog").strip()
        if not title.lower().startswith("mia"):
            title = f"Mia: {title}"
        return title[:100]

    def _semantic_tags(self, script: str, genre: str, title: str, plan: Dict) -> List[str]:
        script_lower = script.lower()
        title_lower = title.lower()
        tags = []

        # Core Mia tags (always present)
        core = ["mia ai influencer", "mia ai vlog", "ai daily vlog", "ai generated story", "youtube shorts"]
        tags.extend(core)

        # Genre-specific tags
        genre_tags = self.GENRE_TAGS.get(genre, self.GENRE_TAGS["story"])
        tags.extend(genre_tags)

        # Story element detection
        for pattern, tag in self.STORY_TAGS.items():
            if re.search(pattern, script_lower) or re.search(pattern, title_lower):
                tags.append(tag)

        # Scene-based location tags
        scenes = plan.get("scenes", [])
        locations = set()
        for scene in scenes:
            loc = str(scene.get("location", "")).lower()
            if loc:
                loc_clean = re.sub(r"^(the\s+|a\s+|an\s+)", "", loc)
                locations.add(loc_clean)
        for loc in locations:
            if "hotel" in loc:
                tags.extend(["abandoned hotel", "hotel exploration", "creepy hotel"])
            elif "house" in loc:
                tags.extend(["abandoned house", "creepy house"])
            elif "street" in loc or "city" in loc:
                tags.extend(["urban exploration", "city mystery"])
            elif "forest" in loc or "woods" in loc:
                tags.extend(["forest mystery", "woods horror"])

        # Object-based tags
        objects = plan.get("key_objects", [])
        for obj in objects:
            obj_name = str(obj.get("name", "")).lower()
            obj_desc = str(obj.get("description", "")).lower()
            if "photo" in obj_name or "photo" in obj_desc:
                tags.extend(["found photo mystery", "photograph mystery", "creepy photo"])
            if "mirror" in obj_name or "mirror" in obj_desc:
                tags.extend(["mirror horror", "reflection mystery"])
            if "door" in obj_name or "door" in obj_desc:
                tags.extend(["mysterious door", "creepy door"])

        # Deduplicate and limit
        seen = set()
        result = []
        for tag in tags:
            tag = tag.lower().strip()
            if tag and tag not in seen:
                seen.add(tag)
                result.append(tag)
        return result[:20]

    @staticmethod
    def _hashtags(genre: str, script: str = "") -> List[str]:
        script_lower = script.lower()
        base = ["#MiaVlog", "#Shorts"]

        genre_map = {
            "horror": ["#Horror", "#ScaryStory", "#Creepy"],
            "mystery": ["#Mystery", "#Suspense", "#Unsolved"],
            "travel": ["#TravelVlog", "#Exploration", "#Adventure"],
            "reaction": ["#Reaction", "#StoryReaction"],
            "daily_vlog": ["#DailyVlog", "#AIInfluencer"],
            "story": ["#AIStory", "#StoryShort"],
        }
        base.extend(genre_map.get(genre, ["#AIStory"]))

        if "abandoned" in script_lower:
            base.extend(["#Abandoned", "#AbandonedPlaces"])
        if any(w in script_lower for w in ["photo", "photograph", "picture"]):
            base.extend(["#FoundPhoto", "#PhotoMystery"])
        if any(w in script_lower for w in ["hotel", "motel"]):
            base.append("#AbandonedHotel")
        if any(w in script_lower for w in ["creepy", "scary", "terrifying"]):
            base.append("#Creepy")

        seen = set()
        result = []
        for h in base:
            if h not in seen:
                seen.add(h)
                result.append(h)
        return result
