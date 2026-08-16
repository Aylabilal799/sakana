import re
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class CaptionEngine:
    def generate_from_script(self, script, total_duration, output_path):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        # Split into short phrases (2-4 words)
        words = script.split()
        phrases = []
        i = 0
        while i < len(words):
            chunk_size = min(4, max(2, len(words) - i))
            phrases.append(" ".join(words[i:i+chunk_size]))
            i += chunk_size

        total_phrases = len(phrases) or 1
        phrase_duration = total_duration / total_phrases

        # Build ASS file
        ass_path = str(Path(output_path).with_suffix(".ass"))
        header = """[Script Info]
Title: Agnes Video Captions
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: CapCut,Arial,68,&H0000FF00,&H0000FF00,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,3,0,2,40,40,200,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

        events = []
        for i, phrase in enumerate(phrases):
            start = i * phrase_duration
            end = min((i + 1) * phrase_duration, total_duration)
            start_t = self._fmt(start)
            end_t = self._fmt(end)
            # Escape ASS special chars
            text = phrase.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
            events.append(f"Dialogue: 0,{start_t},{end_t},CapCut,,0,0,0,,{text}")

        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(header + "\n".join(events) + "\n")

        logger.info(f"ASS captions: {ass_path} ({len(phrases)} phrases)")
        return ass_path

    def _fmt(self, seconds):
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        cs = int((seconds % 1) * 100)
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"
