import logging
import re
import textwrap
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


class CaptionEngine:
    ACCENT_WORDS = {
        "wait", "look", "never", "strange", "secret", "found", "heard", "wrong",
        "creepy", "terrified", "impossible", "today", "finally", "mia", "watch",
    }

    def generate_from_script(self, script: str, total_duration: float, output_path: str) -> str:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        phrases = self._phrases(script)
        weights = [max(1.0, len(re.findall(r"\w+", phrase))) for phrase in phrases]
        total_weight = sum(weights) or 1.0
        cursor = 0.0

        header = r'''[Script Info]
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

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
        events: List[str] = []
        for index, (phrase, weight) in enumerate(zip(phrases, weights)):
            duration = total_duration * weight / total_weight
            start = cursor
            end = total_duration if index == len(phrases) - 1 else min(total_duration, cursor + duration)
            cursor = end
            wrapped = self._wrap(phrase)
            styled = self._emphasize(self._escape(wrapped))
            events.append(
                f"Dialogue: 0,{self._fmt(start)},{self._fmt(end)},MiaCaption,,0,0,0,,"
                r"{\fad(90,90)\blur0.35}" + styled
            )

        ass_path = str(Path(output_path).with_suffix(".ass"))
        Path(ass_path).write_text(header + "\n".join(events) + "\n", encoding="utf-8")
        logger.info("Professional ASS captions: %s (%d phrases)", ass_path, len(phrases))
        return ass_path

    def _phrases(self, script: str) -> List[str]:
        tokens = re.findall(r"\S+", script.strip())
        phrases: List[str] = []
        current: List[str] = []
        for token in tokens:
            current.append(token)
            terminal = bool(re.search(r"[.!?,;:]$", token))
            if len(current) >= 7 or (len(current) >= 3 and terminal):
                phrases.append(" ".join(current))
                current = []
        if current:
            if phrases and len(current) < 2:
                phrases[-1] += " " + " ".join(current)
            else:
                phrases.append(" ".join(current))
        return phrases or [""]

    @staticmethod
    def _wrap(text: str) -> str:
        lines = textwrap.wrap(text, width=28, break_long_words=False, break_on_hyphens=False)
        if len(lines) > 2:
            midpoint = max(1, len(text.split()) // 2)
            words = text.split()
            lines = [" ".join(words[:midpoint]), " ".join(words[midpoint:])]
        return r"\N".join(lines[:2])

    @staticmethod
    def _escape(text: str) -> str:
        marker = "__ASS_NEWLINE__"
        text = text.replace(r"\N", marker)
        text = text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")
        return text.replace(marker, r"\N")

    def _emphasize(self, text: str) -> str:
        words = re.split(r"(\s+|\\N)", text)
        used = False
        for i, word in enumerate(words):
            clean = re.sub(r"[^A-Za-z]", "", word).lower()
            if not used and clean in self.ACCENT_WORDS:
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
