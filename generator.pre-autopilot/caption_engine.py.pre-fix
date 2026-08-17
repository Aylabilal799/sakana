import logging
import re
import textwrap
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


class CaptionEngine:
    # High-impact words that deserve emphasis (story beats, emotions, reveals)
    EMPHASIS_WORDS = {
        "wait", "look", "never", "found", "discovered", "suddenly", "realized",
        "remember", "forgot", "secret", "truth", "lie", "proof", "evidence",
        "scared", "terrified", "shocked", "confused", "worried", "nervous",
        "creepy", "unsettling", "impossible", "unbelievable", "insane",
        "myself", "me", "my", "mine", "that", "same", "identical", "exactly",
        "today", "finally", "again", "before", "always", "never",
        "mia", "watch", "listen", "guys", "you",
    }

    # Phrases that are full-line emphasis worthy (revelations, climaxes)
    CLIMAX_PATTERNS = [
        r"that's\s+me",
        r"i'?ve\s+never\s+seen\s+this",
        r"this\s+is\s+impossible",
        r"this\s+can'?t\s+be\s+real",
        r"i\s+don'?t\s+believe\s+this",
        r"oh\s+my\s+god",
        r"what\s+the\s+hell",
        r"no\s+way",
        r"it\s+can'?t\s+be",
        r"this\s+is\s+wrong",
        r"something\s+isn'?t\s+right",
        r"i\s+need\s+to\s+get\s+out",
        r"i\s+have\s+to\s+leave",
    ]

    def generate_from_script(self, script: str, total_duration: float, output_path: str) -> str:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        phrases = self._phrases(script)
        weights = [max(1.0, len(re.findall(r"\w+", phrase))) for phrase in phrases]
        total_weight = sum(weights) or 1.0
        cursor = 0.0

        header = """[Script Info]
Title: Mia Professional Shorts Captions
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: MiaCaption,DejaVu Sans,68,&H00FFFFFF,&H0000D7FF,&H00101010,&H78000000,-1,0,0,0,100,100,0,0,1,5,2,2,72,72,255,1
Style: MiaCaptionEmphasis,DejaVu Sans,72,&H0000D7FF,&H00FFFFFF,&H00101010,&H78000000,-1,0,0,0,100,100,0,0,1,6,2,2,72,72,255,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        events: List[str] = []
        for index, (phrase, weight) in enumerate(zip(phrases, weights)):
            duration = total_duration * weight / total_weight
            start = cursor
            end = total_duration if index == len(phrases) - 1 else min(total_duration, cursor + duration)
            cursor = end
            wrapped = self._wrap(phrase)
            is_climax = self._is_climax_phrase(phrase)
            styled = self._emphasize(self._escape(wrapped), force_emphasis=is_climax)
            style_name = "MiaCaptionEmphasis" if is_climax else "MiaCaption"
            fade = r"{\fad(120,120)\blur0.4}" if is_climax else r"{\fad(90,90)\blur0.35}"
            events.append(
                f"Dialogue: 0,{self._fmt(start)},{self._fmt(end)},{style_name},,0,0,0,,,"
                + fade + styled
            )

        ass_path = str(Path(output_path).with_suffix(".ass"))
        Path(ass_path).write_text(header + "\n".join(events) + "\n", encoding="utf-8")
        logger.info("Professional ASS captions: %s (%d phrases, %d emphasis)",
                     ass_path, len(phrases), sum(1 for e in events if "Emphasis" in e))
        return ass_path

    def _phrases(self, script: str) -> List[str]:
        """Split script into clean subtitle phrases, fixing stray punctuation."""
        # Step 1: Split on sentence boundaries, preserving the punctuation with the sentence
        raw_sentences = re.split(r"(?<=[.!?])\s+", script.strip())
        sentences = [self._clean_phrase(s) for s in raw_sentences if s.strip()]

        phrases: List[str] = []
        current: List[str] = []

        for sentence in sentences:
            words = sentence.split()
            current.extend(words)
            # Break at sentence end or when phrase gets long enough
            if len(current) >= 8:
                phrases.append(self._clean_phrase(" ".join(current)))
                current = []
            elif len(current) >= 4 and re.search(r"[.!?,;:]$", sentence):
                phrases.append(self._clean_phrase(" ".join(current)))
                current = []

        if current:
            if phrases and len(current) < 3:
                # Append to previous phrase instead of tiny orphan
                phrases[-1] = self._clean_phrase(phrases[-1] + " " + " ".join(current))
            else:
                phrases.append(self._clean_phrase(" ".join(current)))

        return phrases or [""]

    @staticmethod
    def _clean_phrase(text: str) -> str:
        """Remove stray leading/trailing punctuation and whitespace from a phrase."""
        text = text.strip()
        # Remove leading punctuation that shouldn't start a caption
        # e.g., ", I moved..." -> "I moved..."
        # e.g., " ,I..." -> "I..."
        # But preserve internal punctuation like "Wait, look..."
        text = re.sub(r"^[\s,;:\-–—]+", "", text)
        text = re.sub(r"[\s,;:\-–—]+$", "", text)
        # Fix cases where punctuation got detached: "Too fine , maybe" -> "Too fine, maybe"
        text = re.sub(r"\s+([,;:!?.])", r"\1", text)
        # Fix multiple spaces
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    @staticmethod
    def _wrap(text: str) -> str:
        lines = textwrap.wrap(text, width=26, break_long_words=False, break_on_hyphens=False)
        if len(lines) > 2:
            words = text.split()
            midpoint = max(1, len(words) // 2)
            lines = [" ".join(words[:midpoint]), " ".join(words[midpoint:])]
        return r"\N".join(lines[:2])

    @staticmethod
    def _escape(text: str) -> str:
        marker = "__ASS_NEWLINE__"
        text = text.replace(r"\N", marker)
        text = text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")
        return text.replace(marker, r"\N")

    def _is_climax_phrase(self, phrase: str) -> bool:
        phrase_lower = phrase.lower()
        for pattern in self.CLIMAX_PATTERNS:
            if re.search(pattern, phrase_lower):
                return True
        return False

    def _emphasize(self, text: str, force_emphasis: bool = False) -> str:
        """Selective emphasis: one word per phrase, or full phrase for climaxes."""
        if force_emphasis:
            return r"{\c&H00D7FF&\b1}" + text + r"{\c&HFFFFFF&\b0}"

        words = re.split(r"(\s+|\\N)", text)
        used = False
        for i, word in enumerate(words):
            if not word.strip() or word == r"\N":
                continue
            clean = re.sub(r"[^A-Za-z']", "", word).lower().rstrip("'")
            if not used and clean in self.EMPHASIS_WORDS:
                words[i] = r"{\c&H00D7FF&}" + word + r"{\c&HFFFFFF&}"
                used = True
        return "".join(words)

    @staticmethod
    def _fmt(seconds: float) -> str:
        seconds = max(0.0, seconds)
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        cs = int(round((seconds - int(seconds)) * 100))
        if cs == 100:
            s += 1
            cs = 0
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"
