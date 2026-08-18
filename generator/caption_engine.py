import logging
import re
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


class CaptionEngine:
    """Generate ASS captions timed proportionally by word count for perfect TTS sync."""

    def generate_from_script(self, script: str, total_duration: float, output_path: str) -> str:
        if not script or not str(script).strip():
            raise ValueError("Empty script provided for captions")

        script = str(script).strip()
        # Strip any leaked narrator prefix
        script = re.sub(r'^(Mia:\s*)+', '', script, flags=re.IGNORECASE)

        phrases = self._split_phrases(script)
        phrases = [self._clean_phrase(p) for p in phrases if p.strip()]
        if not phrases:
            phrases = [script]

        word_counts = [len(p.split()) for p in phrases]
        total_words = sum(word_counts) or len(phrases)
        time_per_word = total_duration / total_words

        ass_path = Path(output_path)
        ass_path.parent.mkdir(parents=True, exist_ok=True)

        ass_header = self._ass_header()
        events = self._build_events(phrases, word_counts, time_per_word, total_duration)

        ass_path.write_text(ass_header + "\n".join(events), encoding="utf-8")
        logger.info("Professional ASS captions: %s (%d phrases)", ass_path, len(phrases))
        return str(ass_path)

    def _split_phrases(self, text: str) -> List[str]:
        """Split by sentence endings, then by commas if segments are too long."""
        sentences = re.split(r'(?<=[.!?])\s+', text)
        phrases: List[str] = []
        for sent in sentences:
            sent = sent.strip()
            if not sent:
                continue
            if len(sent.split()) > 10:
                parts = re.split(r'(?<=,)\s+', sent)
                buf = ""
                for part in parts:
                    part = part.strip()
                    if not part:
                        continue
                    if buf and len((buf + " " + part).split()) > 10:
                        phrases.append(buf.strip())
                        buf = part
                    else:
                        buf = (buf + " " + part).strip() if buf else part
                if buf:
                    phrases.append(buf.strip())
            else:
                phrases.append(sent)
        return phrases

    def _clean_phrase(self, phrase: str) -> str:
        phrase = phrase.strip()
        phrase = re.sub(r'^[,;:\-\s]+', '', phrase)
        if not phrase:
            return ""
        if phrase[-1] not in ".!?":
            if phrase[-1] == ",":
                phrase = phrase[:-1] + "."
            else:
                phrase += "."
        return phrase

    def _ass_header(self) -> str:
        # 1080x1920 Shorts. Large font, bottom safe area, readable outline.
        return """[Script Info]
Title: Mia Shorts Captions
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,64,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3.5,0,2,40,40,150,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    def _build_events(self, phrases: List[str], word_counts: List[int], time_per_word: float, total_duration: float) -> List[str]:
        events: List[str] = []
        current = 0.0

        for phrase, wc in zip(phrases, word_counts):
            duration = max(wc * time_per_word, 1.0)
            if current + duration > total_duration:
                duration = max(total_duration - current, 0.1)
                if duration <= 0:
                    break

            start = self._fmt(current)
            end = self._fmt(current + duration)

            text = phrase.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
            events.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")
            current += duration

        # Extend last caption to cover any rounding gap
        if events and current < total_duration:
            parts = events[-1].split(",", 3)
            events[-1] = f"{parts[0]},{parts[1]},{self._fmt(total_duration)},{parts[3]}"

        return events

    def _fmt(self, seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = seconds % 60
        return f"{h}:{m:02d}:{s:05.2f}"
