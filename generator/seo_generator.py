import re, os, logging
from typing import Dict, List

logger = logging.getLogger(__name__)

class SEOGenerator:
    def __init__(self):
        self.channel_name = os.getenv("CHANNEL_NAME", "")
        self.channel_url = os.getenv("CHANNEL_URL", "")

    def generate(self, script: str, character_name: str = "", genre: str = "story") -> Dict:
        clean = script.strip()
        sentences = [s.strip() for s in re.split(r'[.!?]+', clean) if s.strip()]
        return {
            "title": self._title(sentences, character_name, genre),
            "description": self._description(clean, genre),
            "tags": self._tags(clean, genre),
            "hashtags": self._hashtags(genre),
            "filename": self._filename(sentences[0] if sentences else "story")
        }

    def _title(self, sentences, character_name, genre):
        candidates = []
        if character_name: candidates.append(f"The {character_name} Who Changed Everything")
        words = sentences[0].split() if sentences else []
        if len(words) > 3: candidates.append(" ".join(words[:8]))
        templates = {"horror": ["The Nightmare Behind the Door"],
                     "mystery": ["The Secret No One Was Meant to Find"],
                     "fantasy": ["The World Beyond the Mirror"],
                     "story": ["The Story That Will Change Your Perspective"]}
        candidates.extend(templates.get(genre, templates["story"]))
        t = candidates[0]
        return t[:87] + "..." if len(t) > 90 else t

    def _description(self, script, genre):
        sentences = [s.strip() for s in re.split(r'[.!?]+', script) if s.strip()]
        summary = " ".join(sentences[:3])
        lines = [summary, "", "AI-generated short story with video generation.", ""]
        if self.channel_name: lines.extend([f"Subscribe to {self.channel_name} for more {genre} shorts.", ""])
        if self.channel_url: lines.append(f"Follow: {self.channel_url}")
        lines.extend(["", "#Shorts #AI #Story"])
        return "\n".join(lines)

    def _tags(self, script, genre):
        stop = {"the","a","an","and","or","but","in","on","at","to","for","of","with","by","is","was","are","were","be","been","have","had"}
        words = re.findall(r'\b[a-zA-Z]{4,}\b', script.lower())
        freq = {}
        for w in words:
            if w not in stop: freq[w] = freq.get(w, 0) + 1
        tags = [w for w, _ in sorted(freq.items(), key=lambda x: x[1], reverse=True)[:10]]
        tags += [genre, "shorts", "ai generated", "story", "narration"]
        return list(dict.fromkeys(tags))

    def _hashtags(self, genre):
        base = ["#Shorts"]
        g = {"horror": ["#Horror","#ScaryStory"], "mystery": ["#Mystery","#Suspense"],
             "fantasy": ["#Fantasy","#Magic"], "story": ["#StoryTime","#Story"]}
        base += g.get(genre, g["story"])
        return base

    def _filename(self, title):
        k = "-".join(re.sub(r'[^a-zA-Z0-9\s]', '', title).lower().split())
        return f"{k[:60]}.mp4"
