"""Refactoring validation engine with lightweight heuristics."""

from __future__ import annotations

import re

from engine.smell_definitions import get_smell_definition


class RefactoringValidator:
    def __init__(self, gemini_model):
        self.model = gemini_model

    def validate(self, session: dict, original_code: str, refactored_code: str) -> dict:
        smell_type = session.get("smell_type", "Unknown")
        definition = get_smell_definition(smell_type) or {"display_name": smell_type}

        original = original_code or session.get("source_code", "")
        refactored = refactored_code or ""

        attempt_number = int(session.get("attempt_count", 0)) + 1
        still_valid_java = self._looks_like_java(refactored)
        changed = self._normalize(original) != self._normalize(refactored)

        smell_resolved = still_valid_java and self._looks_resolved(smell_type, original, refactored)
        correct_technique = smell_resolved or changed

        if smell_resolved:
            score = min(100, 80 + (10 if changed else 0))
            partial_credit = False
            partial_reason = None
            feedback = (
                f"Strong refactor. You reduced the {definition['display_name']} smell and improved code structure."
            )
        elif changed and still_valid_java:
            score = 58
            partial_credit = True
            partial_reason = "Refactor direction is good, but the target smell is still partially present."
            feedback = (
                f"Good attempt. The code changed meaningfully, but the {definition['display_name']} smell still needs refinement."
            )
        else:
            score = 35 if still_valid_java else 20
            partial_credit = False
            partial_reason = None if still_valid_java else "Submitted code is not valid Java yet."
            feedback = (
                "Keep going. Try a smaller, focused refactor and ensure the result remains valid Java."
            )

        stars = 3 if score >= 85 else 2 if score >= 70 else 1 if score >= 55 else 0

        updated_session = dict(session)
        updated_session["attempt_count"] = attempt_number

        return {
            "success": True,
            "attempt_number": attempt_number,
            "score": score,
            "smell_resolved": smell_resolved,
            "correct_technique": correct_technique,
            "still_valid_java": still_valid_java,
            "new_smells_introduced": [],
            "feedback": feedback,
            "partial_credit": partial_credit,
            "partial_reason": partial_reason,
            "stars": stars,
            "updated_session": updated_session,
        }

    def _looks_like_java(self, source: str) -> bool:
        if not source or "class " not in source:
            return False
        return source.count("{") == source.count("}")

    def _looks_resolved(self, smell_type: str, original: str, refactored: str) -> bool:
        if not refactored:
            return False

        # Basic smell-specific heuristics so validation behaves consistently without external analyzers.
        if smell_type == "GodClass":
            return refactored.count("class ") >= 2 or len(refactored.splitlines()) < len(original.splitlines()) * 0.8

        if smell_type == "LongMethod":
            original_methods = len(re.findall(r"\)\s*\{", original))
            refactored_methods = len(re.findall(r"\)\s*\{", refactored))
            return refactored_methods > original_methods

        if smell_type == "LongParameterList":
            params = re.findall(r"\(([^)]*)\)", refactored)
            max_params = 0
            for group in params:
                items = [p.strip() for p in group.split(",") if p.strip()]
                max_params = max(max_params, len(items))
            return max_params <= 5

        if smell_type == "DeadCode":
            return "TODO" not in refactored and "unused" not in refactored.lower()

        # Generic fallback: consider meaningful structural change as resolution signal.
        return self._normalize(original) != self._normalize(refactored)

    def _normalize(self, source: str) -> str:
        lines = [line.strip() for line in source.splitlines() if line.strip()]
        return "\n".join(lines)
