"""
Refactor Engine — EduCode Open World Mode (auto-solve)
=======================================================
Takes a Java class containing a specific code smell and returns the
refactored version via Gemini. Used by POST /world/solve.

This replaces the hint + validate loop for Open World mode only.
GitHub mode and Escape Room mode continue to use the interactive flow.
"""

import json

from engine.smell_definitions import get_smell_definition
from prompts.templates import REFACTOR_PROMPT


class RefactorEngine:

    def __init__(self, gemini_model):
        self.model = gemini_model

    def refactor(self, source_code: str, smell_type: str) -> dict:
        """
        Auto-refactor the given Java source to resolve `smell_type`.

        Returns:
          { "success": True, "refactored_code": str, "summary": str }
          or
          { "success": False, "error": str }
        """
        if not source_code or not source_code.strip():
            return {"success": False, "error": "source_code is empty"}

        smell_def = get_smell_definition(smell_type)
        if not smell_def:
            return {"success": False, "error": f"Unknown smell type: {smell_type}"}

        try:
            prompt = REFACTOR_PROMPT.format(
                smell_type=smell_type,
                display_name=smell_def["display_name"],
                principle=smell_def["principle"],
                original_code=source_code,
            )

            response = self.model.generate_content(prompt)
            raw = (response.text or "").strip()

            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip()

            parsed = json.loads(raw)

            refactored_code = (parsed.get("refactored_code") or "").strip()
            summary = (parsed.get("summary") or "").strip()

            if not refactored_code:
                return {"success": False, "error": "Gemini returned empty refactored_code"}

            return {
                "success": True,
                "refactored_code": refactored_code,
                "summary": summary,
            }

        except json.JSONDecodeError as e:
            return {"success": False, "error": f"Gemini returned invalid JSON: {e}"}
        except Exception as e:
            return {"success": False, "error": f"Refactor failed: {e}"}
