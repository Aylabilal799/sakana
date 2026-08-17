import logging
import re
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger(__name__)


class SEOGenerator:
    def generate(self, plan: Dict) -> Dict:
        script = plan.get("script", "").strip()
        title = self._title(plan)
        genre = plan.get("genre", "daily_vlog")
        hashtags = self._hashtags(genre)
        tags = self._tags(script, genre)
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

    @staticmethod
    def _tags(script: str, genre: str) -> List[str]:
        stop = {"this", "that", "with", "from", "have", "what", "when", "then", "were", "your", "about", "into", "there"}
        words = re.findall(r"\b[a-zA-Z]{4,}\b", script.lower())
        frequency = {}
        for word in words:
            if word not in stop:
                frequency[word] = frequency.get(word, 0) + 1
        topical = [word for word, _ in sorted(frequency.items(), key=lambda item: (-item[1], item[0]))[:10]]
        base = ["mia ai", "mia vlog", "ai influencer", "daily vlog", "youtube shorts", genre.replace("_", " ")]
        return list(dict.fromkeys(base + topical))[:20]

    @staticmethod
    def _hashtags(genre: str) -> List[str]:
        mapping = {
            "horror": ["#MiaVlog", "#Horror", "#ScaryStory", "#Shorts"],
            "mystery": ["#MiaVlog", "#Mystery", "#Suspense", "#Shorts"],
            "travel": ["#MiaVlog", "#TravelVlog", "#AIInfluencer", "#Shorts"],
            "reaction": ["#MiaVlog", "#Reaction", "#AIInfluencer", "#Shorts"],
        }
        return mapping.get(genre, ["#MiaVlog", "#DailyVlog", "#AIInfluencer", "#Shorts"])
