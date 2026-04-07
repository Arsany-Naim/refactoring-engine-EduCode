"""Progressive hint engine used by Escape Room and world challenge sessions."""

from __future__ import annotations

from engine.smell_definitions import get_smell_definition, get_highlight_type


MAX_STAGES = 4

_TONE_BY_STAGE = {
    1: "curious",
    2: "educational",
    3: "directional",
    4: "concrete",
}


class HintEngine:
    def __init__(self, gemini_model):
        self.model = gemini_model

    def get_next_hint(self, session: dict) -> dict:
        current_stage = int(session.get("current_stage", 0))
        if current_stage >= MAX_STAGES:
            return {
                "success": False,
                "message": "All hints are already unlocked for this puzzle.",
                "hint_stage": MAX_STAGES,
                "max_stages": MAX_STAGES,
            }

        next_stage = current_stage + 1
        hint = self._build_hint(session, next_stage)

        updated_session = dict(session)
        updated_session["current_stage"] = next_stage

        hints_seen = list(updated_session.get("hints_seen", []))
        if next_stage not in hints_seen:
            hints_seen.append(next_stage)
        updated_session["hints_seen"] = hints_seen

        return {
            **hint,
            "updated_session": updated_session,
        }

    def get_specific_hint(self, session: dict, stage: int) -> dict:
        stage = max(1, min(int(stage), MAX_STAGES))
        current_stage = int(session.get("current_stage", 0))
        if stage > current_stage:
            return {
                "success": False,
                "message": f"Hint stage {stage} is not unlocked yet.",
                "hint_stage": current_stage,
                "max_stages": MAX_STAGES,
            }

        return {
            **self._build_hint(session, stage),
            "updated_session": session,
        }

    def _build_hint(self, session: dict, stage: int) -> dict:
        smell_type = session.get("smell_type", "Unknown")
        definition = get_smell_definition(smell_type) or {
            "display_name": smell_type,
            "principle": "Clean Code",
            "highlight_type": "warning",
        }

        class_name = session.get("affected_class") or session.get("smell_location", {}).get("class_name")
        method_name = session.get("affected_method") or session.get("smell_location", {}).get("method_name")
        context = session.get("hint_context", {}) or {}

        hint_text = self._stage_text(stage, smell_type, definition["principle"], class_name, method_name, context)
        encouragement = self._encouragement(stage)

        return {
            "success": True,
            "hint_stage": stage,
            "max_stages": MAX_STAGES,
            "is_final_hint": stage == MAX_STAGES,
            "smell_type": smell_type,
            "hint_text": hint_text,
            "encouragement": encouragement,
            "tone": _TONE_BY_STAGE.get(stage, "supportive"),
            "highlight": {
                "class_name": class_name,
                "method_name": method_name if stage >= 3 else None,
                "highlight_level": "floor" if method_name and stage >= 3 else "building",
                "highlight_type": get_highlight_type(smell_type),
            },
        }

    def _stage_text(
        self,
        stage: int,
        smell_type: str,
        principle: str,
        class_name: str,
        method_name: str | None,
        context: dict,
    ) -> str:
        class_name = class_name or "this class"
        method_name = method_name or "the busiest method"

        if stage == 1:
            return f"Look closely at {class_name}. Which part feels overloaded or hard to reason about?"
        if stage == 2:
            return f"This challenge is about {principle}. Focus on separating responsibilities and simplifying collaboration points."
        if stage == 3:
            return (
                f"Start in {class_name}, especially around {method_name}. "
                "Refactor by extracting focused behavior into smaller units."
            )

        suggestion = context.get("suggested_method") or "extract a clear helper method"
        target_class = context.get("suggested_class") or "a focused collaborator class"
        return (
            f"Concrete step: in {class_name}, {suggestion}, then move related logic into {target_class}. "
            "Re-run validation once the class has a single clear responsibility."
        )

    def _encouragement(self, stage: int) -> str:
        if stage == 1:
            return "You are building a strong eye for design issues."
        if stage == 2:
            return "Great progress — you are connecting smell patterns to principles."
        if stage == 3:
            return "Nice momentum. You are very close to a clean refactor."
        return "Excellent effort. Apply the concrete step and submit again."
