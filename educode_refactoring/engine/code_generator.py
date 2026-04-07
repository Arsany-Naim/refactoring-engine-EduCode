"""Puzzle code generation engine for Escape Room mode."""

from __future__ import annotations

import json
import random
import re
import time

from prompts.templates import CODE_GENERATION_PROMPT, DIFFICULTY_LABELS, THEMES
from engine.smell_definitions import get_all_smell_types, get_smell_definition


class CodeGenerator:
    def __init__(self, gemini_model):
        self.model = gemini_model

    def generate(self, smell_type: str | None, difficulty: int = 1, theme: str | None = None) -> dict:
        if not smell_type:
            smell_type = random.choice(get_all_smell_types())

        smell_def = get_smell_definition(smell_type)
        if not smell_def:
            return {"success": False, "error": f"Unknown smell type: {smell_type}"}

        difficulty = max(1, min(int(difficulty or 1), 3))
        theme = theme or random.choice(THEMES)

        payload = self._generate_with_model(smell_type, smell_def, difficulty, theme)
        if not payload:
            payload = self._fallback_payload(smell_type, smell_def, difficulty, theme)

        files = payload.get("files", [])
        metadata = payload.get("metadata", {})
        if not files:
            return {"success": False, "error": "Code generation produced no files"}

        puzzle_id = f"ER-{smell_type}-{int(time.time())}"
        source_code = "\n\n".join(file.get("content", "") for file in files)

        affected_class = metadata.get("affected_class") or self._extract_class_name(source_code)
        affected_method = metadata.get("affected_method")
        smell_location = metadata.get("smell_location", {})
        hint_context = metadata.get("hint_context", {})

        session = {
            "puzzle_id": puzzle_id,
            "smell_type": smell_type,
            "difficulty": difficulty,
            "difficulty_label": DIFFICULTY_LABELS.get(difficulty, "Beginner"),
            "theme": theme,
            "mode": "escape_room",
            "affected_class": affected_class,
            "affected_method": affected_method,
            "smell_location": {
                "class_name": smell_location.get("class_name", affected_class),
                "method_name": smell_location.get("method_name", affected_method),
                "line_hint": str(smell_location.get("line_hint", "")),
            },
            "hint_context": hint_context,
            "current_stage": 0,
            "attempt_count": 0,
            "hints_seen": [],
            "started_at": time.time(),
            "source_code": source_code,
            "file_path": files[0].get("filename", ""),
        }

        return {
            "success": True,
            "puzzle_id": puzzle_id,
            "smell_type": smell_type,
            "display_name": smell_def["display_name"],
            "principle": smell_def["principle"],
            "difficulty": difficulty,
            "difficulty_label": DIFFICULTY_LABELS.get(difficulty, "Beginner"),
            "theme": theme,
            "files": files,
            "session": session,
        }

    def get_available_smells(self) -> list[dict]:
        smells = []
        for smell_type in get_all_smell_types():
            definition = get_smell_definition(smell_type)
            if not definition:
                continue
            smells.append(
                {
                    "smell_type": smell_type,
                    "display_name": definition["display_name"],
                    "principle": definition["principle"],
                    "highlight_type": definition["highlight_type"],
                }
            )
        return smells

    def _generate_with_model(self, smell_type: str, smell_def: dict, difficulty: int, theme: str) -> dict | None:
        if not self.model:
            return None

        prompt = CODE_GENERATION_PROMPT.format(
            smell_type=smell_type,
            display_name=smell_def["display_name"],
            principle=smell_def["principle"],
            difficulty=difficulty,
            theme=theme,
        )

        try:
            response = self.model.generate_content(prompt)
            raw = (response.text or "").strip()
            payload = self._extract_json(raw)
            if not isinstance(payload, dict):
                return None
            if not isinstance(payload.get("files"), list):
                return None
            return payload
        except Exception:
            return None

    def _extract_json(self, text: str) -> dict | None:
        if text.startswith("```"):
            text = text.strip("`")
            text = text.replace("json", "", 1).strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", text)
            if not match:
                return None
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None

    def _fallback_payload(self, smell_type: str, smell_def: dict, difficulty: int, theme: str) -> dict:
        class_name = f"{smell_type}Sample"
        method_name = "processData"

        code = f"""public class {class_name} {{
    private String theme = \"{theme}\";

    public void {method_name}(String input, String extra, String flag, String mode, String user, String token) {{
        String result = input + extra;
        if (flag != null) {{
            if (mode != null) {{
                if (user != null) {{
                    result = result + user + token;
                }}
            }}
        }}
        System.out.println(result + theme);
    }}
}}
"""

        hint_context = {
            "class_name": class_name,
            "method_name": method_name,
            "line_count": len(code.splitlines()),
            "param_count": 6,
            "method_count": 1,
        }

        return {
            "files": [{"filename": f"{class_name}.java", "content": code}],
            "metadata": {
                "primary_smell": smell_type,
                "affected_class": class_name,
                "affected_method": method_name,
                "smell_location": {
                    "class_name": class_name,
                    "method_name": method_name,
                    "line_hint": 4,
                },
                "hint_context": hint_context,
            },
        }

    def _extract_class_name(self, source_code: str) -> str:
        match = re.search(r"\bclass\s+(\w+)", source_code)
        if match:
            return match.group(1)
        return "GeneratedClass"
