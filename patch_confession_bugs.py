import re

# ===================== FIX pipeline.py =====================
with open("/root/sakana/generator/pipeline.py", "r") as f:
    content = f.read()

# 1. Ensure re is imported
if "import re\n" not in content:
    content = content.replace("import json\nimport logging", "import json\nimport logging\nimport re")

# 2. Add monologue detection before story planning
old_plan = '            plan = self.story.plan(user_prompt)'
new_plan = '''            if self.is_confession and self._is_monologue(user_prompt):
                plan = self._create_monologue_plan(user_prompt)
            else:
                plan = self.story.plan(user_prompt)'''
content = content.replace(old_plan, new_plan)

# 3. Fix audio fallback to use plan's character voice instead of hardcoded af_nicole
old_fallback = '''        if not lines:
            # Fallback: treat entire script as narration with default voice
            logger.warning("No dialogue lines parsed, using fallback narration")
            output_path = str(self.audio_dir / "confession_narration.wav")
            return self.tts.generate(script, output_path, voice="af_nicole")'''
new_fallback = '''        if not lines:
            # Monologue: single-character narration using assigned voice
            voice = plan.get("characters", [{}])[0].get("voice", "af_nicole") if plan.get("characters") else "af_nicole"
            logger.info("Monologue mode — single voice: %s", voice)
            output_path = str(self.audio_dir / "confession_narration.wav")
            return self.tts.generate(script, output_path, voice=voice)'''
content = content.replace(old_fallback, new_fallback)

# 4. Confession SEO override (separate from Mia)
old_seo = '            youtube = self.seo.generate(plan)'
new_seo = '''            youtube = self.seo.generate(plan)

            # Confession channel: separate SEO metadata from Mia
            if self.is_confession:
                confession_title = plan.get("title", "Confession Story")[:100]
                youtube["title"] = confession_title
                # Strip any Mia/vlog terms, build confession description
                old_desc = youtube.get("description", "")
                if "Mia" in old_desc or "vlog" in old_desc.lower():
                    old_desc = "A real confession story.\\n\\n" + plan.get("script", "")[:400]
                youtube["description"] = old_desc[:5000]
                confession_tags = ["confession", "reddit story", "real story", "relationship", "drama", "storytime", "cheating", "secrets", "betrayal"]
                existing = [t for t in youtube.get("tags", []) if t.lower() not in ["mia", "daily vlog", "vlogger", "influencer"]]
                youtube["tags"] = list(dict.fromkeys(confession_tags + existing))[:15]
                logger.info("Confession SEO generated: title='%s' tags=%s", confession_title, youtube["tags"])'''
content = content.replace(old_seo, new_seo)

# 5. Insert monologue helper methods
monologue_code = '''
    @staticmethod
    def _is_monologue(text: str) -> bool:
        """Detect single-person monologue (no CHARACTERNAME: dialogue lines)."""
        lines = [l.strip() for l in text.strip().split("\\n") if l.strip()]
        dialogue_lines = sum(1 for l in lines if re.match(r"^[A-Z][A-Za-z\\s]{0,20}:", l))
        return dialogue_lines < 2

    def _create_monologue_plan(self, script: str) -> Dict:
        """Build a single-character confession plan with locked visual consistency."""
        clean = script.strip()
        lower = clean.lower()

        # Detect gender from relationship context
        male = sum(lower.count(w) for w in [" my wife", " my girlfriend", " husband", " boyfriend i ", " man ", " guy ", " dad ", " father "])
        female = sum(lower.count(w) for w in [" my husband", " my boyfriend", " wife i ", " woman ", " girl ", " mom ", " mother "])

        if male > female:
            gender, voice = "male", "am_adam"
            appearance = "34-year-old man with short dark brown hair, light stubble, slim build, wearing a dark fitted t-shirt and jeans"
        elif female > male:
            gender, voice = "female", "af_nicole"
            appearance = "32-year-old woman with shoulder-length brown hair, natural makeup, slim build, wearing a neutral blouse"
        else:
            gender, voice = "male", "am_adam"
            appearance = "person in their 30s with short dark hair, casual fitted clothing, slim build"

        locked_char = {
            "name": "Narrator", "gender": gender, "age": "mid-30s",
            "role": "protagonist", "voice": voice, "appearance": appearance,
        }

        title = clean.split(".")[0][:77] + "..." if len(clean.split(".")[0]) > 77 else clean.split(".")[0]
        sentences = [s.strip() for s in clean.split(".") if s.strip()]
        total = max(len(sentences), 1)

        configs = [
            {"beat": "setup", "shot": "medium close-up", "mood": "tense", "expr": "conflicted, avoiding eye contact, voice low", "cam": "subtle push-in", "light": "warm tense"},
            {"beat": "escalation", "shot": "close-up", "mood": "confrontational", "expr": "emotionally raw, jaw tight, eyes glistening", "cam": "gentle handheld drift", "light": "dramatic natural"},
            {"beat": "resolution", "shot": "reaction close-up", "mood": "defeated", "expr": "hollow, resigned, staring past camera", "cam": "slow pull-back", "light": "cool moody"},
        ]

        scenes = []
        for i, cfg in enumerate(configs):
            start, end = int(i * total / 3), int((i + 1) * total / 3)
            chunk = ". ".join(sentences[start:end]) + "." if sentences[start:end] else clean

            # CRITICAL: Lock the SAME character appearance across every scene
            visual = (
                f"Cinematic {cfg['shot']} of the SAME {appearance} delivering an emotional confession. "
                f"He is completely alone in the frame, speaking directly to camera. "
                f"Expression: {cfg['expr']}. Location: dimly lit apartment living room, intimate tense atmosphere. "
                f"Camera: {cfg['cam']}. Lighting: {cfg['light']}. "
                f"ONE PERSON ONLY. No other people. Same face, same hair, same clothing in every frame. "
                f"Photorealistic cinematic movie quality, natural skin texture, vertical 9:16, sharp focus, no black bars."
            )

            scenes.append({
                "index": i + 1,
                "beat": cfg["beat"],
                "follows_from_previous": "opening" if i == 0 else "emotional weight from previous scene",
                "dialogue_segment": chunk,
                "location": "apartment living room",
                "location_change_reason": "same_location",
                "action": "speaker delivering emotional confession directly to camera",
                "shot_type": cfg["shot"],
                "visual_prompt": visual,
                "camera_motion": cfg["cam"],
                "lighting": cfg["light"],
                "expression": cfg["expr"],
                "emotional_state": cfg["mood"],
                "story_event": f"Confessor reveals layer {i+1} of secret",
                "transition": "cut",
            })

        return {
            "title": title or "Confession Story",
            "genre": "confession",
            "tone": "tense",
            "characters": [locked_char],
            "point_a": "Speaker hides a secret double life.",
            "point_b": "Speaker has confessed and accepted the weight of it.",
            "script": clean,
            "opening_hook": clean[:150],
            "final_reveal": clean[-200:] if len(clean) > 200 else clean,
            "scenes": scenes,
            "source_theme": "user_monologue",
            "channel": "confession",
        }

'''

marker = "    def _ensure_reference_image(self) -> None:"
if marker in content and "_is_monologue" not in content:
    content = content.replace(marker, monologue_code + marker)

with open("/root/sakana/generator/pipeline.py", "w") as f:
    f.write(content)
print("✅ Fixed pipeline.py")

# ===================== FIX worker_process.py =====================
with open("/root/sakana/generator/worker_process.py", "r") as f:
    wp = f.read()

old_sched = "scheduled_dt = datetime.fromisoformat(scheduled_time_iso) if scheduled_time_iso else None"
new_sched = '''scheduled_dt = None
        if scheduled_time_iso:
            try:
                scheduled_dt = datetime.fromisoformat(scheduled_time_iso)
                # YouTube API requires UTC; enforce if naive
                if scheduled_dt.tzinfo is None:
                    from datetime import timezone
                    scheduled_dt = scheduled_dt.replace(tzinfo=timezone.utc)
                logger.info("YouTube scheduled time parsed: %s (UTC)", scheduled_dt.isoformat())
            except Exception as e:
                logger.error("Failed to parse scheduled_time '%s': %s", scheduled_time_iso, e)
                scheduled_dt = None'''
wp = wp.replace(old_sched, new_sched)

with open("/root/sakana/generator/worker_process.py", "w") as f:
    f.write(wp)
print("✅ Fixed worker_process.py")
