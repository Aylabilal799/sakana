import json
import logging
import os
import random
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger(__name__)


class ConfessionSEOGenerator:
    """Dedicated SEO generator for confession/story YouTube channel.
    Optimized for YouTube Shorts algorithm: retention hooks, searchable keywords,
    emotional CTR, and storytime niche SEO."""

    # High-volume storytime/confession keywords for tags
    CONFESSION_TAGS = [
        "confession", "storytime", "relationship stories", "cheating story",
        "true story", "real story", "drama", "breakup story", "betrayal",
        "secret revealed", "guilt", "marriage problems", "infidelity",
        "trust issues", "shocking story", "emotional story", "sad story",
        "toxic relationship", "narration", "confession shorts",
        "storytime shorts", "real confession", "dark secret",
        "relationship advice", "dating horror story", "couple drama",
        "confession story", "true confession", "hidden truth",
        "secret affair", "caught cheating", "relationship betrayal",
        "heartbreak story", "shocking confession", "personal story",
        "life story", "deep confession", "raw confession",
    ]

    # Strong title templates — emotional + curiosity + specificity
    TITLE_TEMPLATES = [
        "I {verb} For {time} And This Is What Happened",
        "I {verb} For {time}... I Had To Confess",
        "My {relation} Doesn't Know I {secret}",
        "I've Been {verb} For {time} And I Feel {emotion}",
        "I {verb} And I Can't Take It Back",
        "The {secret} I Hid From My {relation} For {time}",
        "I Confess: I {verb} For {time}",
        "My {relation} Thinks I'm {adjective}. They Don't Know The Truth.",
        "I {verb} Behind My {relation}'s Back For {time}",
        "The Truth About My {time} {secret}",
        "I {verb} And The Guilt Is {emotion}",
        "What My {relation} Doesn't Know About The Last {time}",
        "I {verb} For {time} — Here's My Confession",
        "The {secret} That Could Destroy My {relation}",
        "I {verb} And Now I Have To Live With It",
    ]

    # Emotional power words for titles
    VERBS = [
        "cheated", "lied", "hid the truth", "kept a secret", "pretended",
        "lived a double life", "betrayed the one I love", "hurt someone",
        "made a mistake", "ruined everything", "wasted years", "deceived",
        "broke her trust", "destroyed my marriage", "threw it all away",
        "hurt the person I love", "broke my promise", "crossed the line",
    ]
    SECRETS = [
        "double life", "secret", "lie", "truth", "betrayal", "affair",
        "other life", "second phone", "hidden messages", "secret account",
        "hidden truth", "dark secret", "painful truth", "terrible secret",
    ]
    RELATIONS = [
        "wife", "husband", "girlfriend", "boyfriend", "partner", "spouse",
        "family", "parents", "best friend", "fiancé", "the person I love",
    ]
    EMOTIONS = [
        "eating me alive", "destroying me", "unbearable", "killing me inside",
        "too heavy", "unforgivable", "irreversible", "the worst feeling",
        "crushing me", "breaking me", "too much to carry",
    ]
    ADJECTIVES = [
        "loyal", "faithful", "honest", "a good partner", "happy", "fine",
        "okay", "committed", "trustworthy", "devoted", "dedicated",
    ]
    TIMES = [
        "years", "months", "way too long", "longer than I admit",
        "longer than I should have", "a long time", "too long",
    ]

    # Description intros
    DESC_INTROS = [
        "This is a real confession. The names have been changed, but the story is true.",
        "A raw confession about secrets, guilt, and the things we hide from the people closest to us.",
        "Some stories stay buried for years. This is one of them.",
        "A true confession about betrayal, deception, and the weight of hiding the truth.",
        "Not every confession sets you free. Some just make you face what you've done.",
        "A personal story about the secrets we keep and the price we pay for them.",
        "This confession is about the moment the truth becomes too heavy to carry alone.",
    ]

    def __init__(self, output_dir: str = None):
        self.output_dir = Path(output_dir or "/root/sakana/jobs")

    def generate(self, plan: Dict) -> Dict:
        """Generate strong confession SEO metadata from a story plan."""
        script = plan.get("script", "")
        title = self._generate_title(script, plan.get("title", ""))
        description = self._generate_description(script, plan, title)
        tags = self._generate_tags(script, plan)
        hashtags = self._generate_hashtags(tags)

        return {
            "title": title,
            "description": description,
            "tags": tags,
            "hashtags": hashtags,
            "category_id": "24",
            "privacy_status": "private",
            "made_for_kids": False,
            "language": "en",
            "playlist_ids": [],
            "seo_version": "confession_v1",
        }

    def _generate_title(self, script: str, fallback_title: str = "") -> str:
        """Create a high-CTR emotional title from the script content."""
        script_lower = script.lower()

        # Detect core themes
        has_cheating = any(w in script_lower for w in ["cheat", "affair", "other woman", "other women", "behind her back", "behind his back", "seeing other"])
        has_lying = any(w in script_lower for w in ["lie", "lying", "lied", "secret", "hid", "hidden", "doesn't know", "doesnt know"])
        has_time = any(w in script_lower for w in ["years", "months", "for years", "for months", "long time"])
        has_wife = "my wife" in script_lower or " wife" in script_lower
        has_husband = "my husband" in script_lower or " husband" in script_lower

        relation = "wife" if has_wife else "husband" if has_husband else "partner"
        verb = "cheated" if has_cheating else random.choice(self.VERBS)
        time_phrase = "years" if has_time else random.choice(self.TIMES)
        emotion = random.choice(self.EMOTIONS)
        secret = random.choice(self.SECRETS)
        adjective = random.choice(self.ADJECTIVES)

        # Score templates by relevance
        template_scores = []
        if has_cheating and has_time:
            template_scores.extend([
                ("I {verb} For {time} And This Is What Happened", 10),
                ("I {verb} Behind My {relation}'s Back For {time}", 9),
                ("The {secret} I Hid From My {relation} For {time}", 8),
                ("I {verb} For {time} — Here's My Confession", 8),
            ])
        if has_cheating:
            template_scores.extend([
                ("My {relation} Thinks I'm {adjective}. They Don't Know The Truth.", 7),
                ("I {verb} And I Can't Take It Back", 7),
                ("The {secret} That Could Destroy My {relation}", 7),
            ])
        if has_lying and has_time:
            template_scores.extend([
                ("What My {relation} Doesn't Know About The Last {time}", 6),
                ("I Confess: I {verb} For {time}", 6),
            ])

        # Add all generic templates
        for t in self.TITLE_TEMPLATES:
            if t not in [x[0] for x in template_scores]:
                template_scores.append((t, 3))

        template_scores.sort(key=lambda x: x[1], reverse=True)
        template = template_scores[0][0]

        title = template.format(
            verb=verb, time=time_phrase, relation=relation,
            secret=secret, emotion=emotion, adjective=adjective,
        )

        title = title.strip()
        title = re.sub(r'\s+', ' ', title)
        if len(title) > 100:
            title = title[:97] + "..."

        return title

    def _generate_description(self, script: str, plan: Dict, title: str) -> str:
        """Build algorithm-friendly description with hooks and timestamps."""
        intro = random.choice(self.DESC_INTROS)

        # Extract first 2 sentences for hook
        sentences = [s.strip() for s in script.split(".") if s.strip()]
        hook = ". ".join(sentences[:2]) + "." if len(sentences) >= 2 else script[:200]
        if len(hook) > 250:
            hook = hook[:247] + "..."

        # Build scene timestamps
        scenes = plan.get("scenes", [])
        timestamps = []
        current_time = 0
        for i, scene in enumerate(scenes[:5], 1):
            beat = scene.get("beat", "scene").replace("_", " ").title()
            duration = int(scene.get("duration", 8))
            timestamps.append(f"0:{current_time:02d} — {beat}")
            current_time += duration

        timestamp_block = "\n".join(timestamps) if timestamps else "0:00 — The confession begins"

        # Related searches
        related = [
            "confession story",
            "cheating story",
            "relationship secret",
            "true cheating story",
            "i cheated and i regret it",
            "relationship advice",
            "storytime confession",
            "real betrayal story",
            "secret revealed",
            "emotional confession",
        ]
        related_block = "\n".join(f"• {r}" for r in related)

        # CTA blocks
        cta = (
            "This is a real confession story. If you've ever had to face the truth about yourself, "
            "you know how heavy a secret can get.\n\n"
            "What would you have done in this situation? Tell me in the comments. "
            "I read every single one."
        )

        sub_cta = (
            "New confession stories every week. Real people. Real secrets. Real consequences. "
            "Subscribe so you don't miss the next one."
        )

        description = (
            f"{title}\n"
            f"{'=' * min(len(title), 60)}\n\n"
            f"{intro}\n\n"
            f"{hook}\n\n"
            f"{cta}\n\n"
            f"{'─' * 40}\n"
            f"TIMESTAMPS:\n"
            f"{timestamp_block}\n"
            f"{'─' * 40}\n\n"
            f"RELATED STORIES:\n"
            f"{related_block}\n\n"
            f"{sub_cta}\n\n"
            f"#Confession #Storytime #Relationship #Cheating #TrueStory #Shorts"
        )

        if len(description) > 4900:
            description = description[:4897] + "..."

        return description

    def _generate_tags(self, script: str, plan: Dict) -> List[str]:
        """Generate ranked tag list from script content."""
        script_lower = script.lower()
        tags = list(self.CONFESSION_TAGS)

        # Add contextual tags
        if any(w in script_lower for w in ["wife", "married", "marriage", "husband"]):
            tags.extend(["wife", "husband", "marriage", "married life", "spouse"])
        if any(w in script_lower for w in ["cheat", "cheating", "affair", "other woman"]):
            tags.extend(["cheating", "affair", "infidelity", "cheating story", "caught cheating"])
        if any(w in script_lower for w in ["guilt", "regret", "sorry", "apologize"]):
            tags.extend(["guilt", "regret", "remorse", "i regret it"])
        if any(w in script_lower for w in ["secret", "hid", "hidden", "lie", "lying"]):
            tags.extend(["secret revealed", "hidden truth", "caught lying", "exposed"])
        if any(w in script_lower for w in ["years", "long time", "never told"]):
            tags.extend(["years of lies", "long term secret", "finally confessing"])
        if any(w in script_lower for w in ["destroy", "ruin", "broke", "hurt"]):
            tags.extend(["destroyed everything", "broke her heart", "relationship ruined"])

        # Deduplicate and limit
        seen = set()
        final_tags = []
        for t in tags:
            t_clean = t.lower().strip()
            if t_clean not in seen and len(t_clean) <= 30:
                seen.add(t_clean)
                final_tags.append(t_clean)

        return final_tags[:15]

    def _generate_hashtags(self, tags: List[str]) -> List[str]:
        """Convert tags to hashtag format for social platforms."""
        hashtags = []
        for tag in tags[:8]:
            clean = re.sub(r'[^a-zA-Z0-9]', '', tag.title())
            if clean:
                hashtags.append(f"#{clean}")
        return hashtags

    def write_text_file(self, youtube_meta: Dict, output_path: str) -> str:
        """Write confession SEO metadata to a formatted text file."""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        hashtags_str = " ".join(youtube_meta.get("hashtags", []))
        tags_str = ", ".join(youtube_meta.get("tags", []))

        content = (
            f"TITLE:\n{youtube_meta['title']}\n\n"
            f"DESCRIPTION:\n{youtube_meta['description']}\n\n"
            f"TAGS:\n{tags_str}\n\n"
            f"HASHTAGS:\n{hashtags_str}\n\n"
            f"CATEGORY: {youtube_meta.get('category_id', '24')}\n"
            f"PRIVACY: {youtube_meta.get('privacy_status', 'private')}\n"
            f"GENERATED: {datetime.now(timezone.utc).isoformat()}\n"
            f"SEO_TYPE: confession\n"
        )

        path.write_text(content, encoding="utf-8")
        return str(path)


def get_seo_generator(channel: str = "mia", output_dir: str = None):
    """Factory: returns the correct SEO generator for the channel."""
    if channel == "confession":
        return ConfessionSEOGenerator(output_dir)
    try:
        from generator.seo_generator import SEOGenerator
        return SEOGenerator(output_dir)
    except ImportError:
        return ConfessionSEOGenerator(output_dir)
