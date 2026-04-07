"""
Engage Engine — EduCode Open World / GitHub Mode
==================================================
Initializes a hint session from a ChallengeItem in a TeachingPlan.
This is the entry point when a student walks up to a damaged building
and chooses to engage with it — as opposed to Escape Room where the
puzzle is pre-generated.

The session it produces is identical in schema to the one produced
by CodeGenerator, so the HintEngine and RefactoringValidator work
without any changes.
"""

import time
from engine.smell_definitions import get_smell_definition
from engine.session_store import session_store
from prompts.templates import ENGAGE_CONTEXT_PROMPT
import json


class EngageEngine:

    def __init__(self, gemini_model):
        self.model = gemini_model

    def engage(
        self,
        challenge: dict,
        analysis_report: dict,
        mode: str = "open_world",
        student_id: str = None
    ) -> dict:
        """
        Creates a hint session from a ChallengeItem.

        Args:
            challenge:       A ChallengeItem from the TeachingPlan
            analysis_report: The full AnalysisReport from the pipeline
            mode:            "open_world" | "github"
            student_id:      Optional student ID for progression tracking

        Returns:
        {
          "success":    true,
          "puzzle_id":  str,   ← store this, same as Escape Room
          "smell_type": str,
          "display_name": str,
          "principle":  str,
          "class_name": str,
          "method_name": str | null,
          "mode":       str,
          "educator_note": str,
          "file_path":  str,
          "source_code": str   ← the actual class code from the repo
        }
        """
        smell_type = challenge.get("smell_type")
        class_name = challenge.get("class_name")
        challenge_id = challenge.get("challenge_id")

        smell_def = get_smell_definition(smell_type)
        if not smell_def:
            return self._error(f"Unknown smell type: {smell_type}")

        # Pull the class data from the analysis report
        class_data = self._find_class(analysis_report, class_name)
        if not class_data:
            return self._error(f"Class '{class_name}' not found in analysis report")

        metrics = class_data.get("metrics", {})
        source_code = class_data.get("source_code", "")
        existing_feedback = class_data.get("feedback", "")

        # Enrich hint_context via Gemini
        base_context = challenge.get("hint_context", {})
        enriched_context = self._enrich_context(
            smell_type=smell_type,
            display_name=smell_def["display_name"],
            class_name=class_name,
            method_name=challenge.get("method_name"),
            metrics=metrics,
            sources=challenge.get("sources", []),
            existing_feedback=existing_feedback,
            mode=mode,
            base_context=base_context
        )

        # Build session — identical schema to CodeGenerator output
        puzzle_id = f"{mode[:2].upper()}-{challenge_id}-{int(time.time())}"

        session = {
            "puzzle_id": puzzle_id,
            "smell_type": smell_type,
            "difficulty": self._infer_difficulty(challenge, student_id),
            "difficulty_label": "Contextual",
            "theme": mode,
            "mode": mode,
            "affected_class": class_name,
            "affected_method": challenge.get("method_name"),
            "smell_location": {
                "class_name": class_name,
                "method_name": challenge.get("method_name"),
                "line_hint": str(challenge.get("line_hint", ""))
            },
            "hint_context": {**base_context, **enriched_context},
            "current_stage": 0,
            "attempt_count": 0,
            "hints_seen": [],
            "started_at": time.time(),
            "student_id": student_id,
            "challenge_id": challenge_id,
            "source_code": source_code,
            "file_path": challenge.get("file_path", "")
        }

        session_store.save(puzzle_id, session)

        return {
            "success": True,
            "puzzle_id": puzzle_id,
            "smell_type": smell_type,
            "display_name": smell_def["display_name"],
            "principle": smell_def["principle"],
            "class_name": class_name,
            "method_name": challenge.get("method_name"),
            "file_path": challenge.get("file_path", ""),
            "mode": mode,
            "severity": challenge.get("severity", "warning"),
            "highlight_type": challenge.get("highlight_type", "warning"),
            "educator_note": enriched_context.get("enriched_feedback", ""),
            "source_code": source_code
        }

    # ── GEMINI ENRICHMENT ─────────────────────────────────────────────────────

    def _enrich_context(
        self,
        smell_type: str,
        display_name: str,
        class_name: str,
        method_name,
        metrics: dict,
        sources: list,
        existing_feedback: str,
        mode: str,
        base_context: dict
    ) -> dict:
        """
        Calls Gemini to fill in richer hint context from real metrics.
        Falls back to base_context on any error.
        """
        try:
            prompt = ENGAGE_CONTEXT_PROMPT.format(
                smell_type=smell_type,
                display_name=display_name,
                class_name=class_name,
                method_name=method_name or "N/A",
                loc=metrics.get("loc", "unknown"),
                nom=metrics.get("nom", "unknown"),
                wmc=metrics.get("wmc", "unknown"),
                cbo=metrics.get("cbo", "unknown"),
                sources=", ".join(sources),
                existing_feedback=existing_feedback or "None",
                mode=mode
            )

            response = self.model.generate_content(prompt)
            raw = response.text.strip()

            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip()

            enriched = json.loads(raw)
            # Merge: enriched overrides base only where non-null
            result = {}
            for key, val in enriched.items():
                if val is not None:
                    result[key] = val
            return result

        except Exception as e:
            print(f"[EngageEngine] Gemini enrichment failed: {e}")
            return {}

    # ── HELPERS ───────────────────────────────────────────────────────────────

    def _find_class(self, analysis_report: dict, class_name: str) -> dict:
        for cls in analysis_report.get("classes", []):
            if cls.get("class_name") == class_name:
                return cls
        return {}

    def _infer_difficulty(self, challenge: dict, student_id: str) -> int:
        """
        GitHub mode: no difficulty — real code is always contextual.
        Open World: infer from curriculum tier.
        """
        # GitHub sessions carry no difficulty — the challenge comes from
        # the student's real repo, not a generated puzzle at a set level.
        # We store 0 to signal "real-world / no difficulty" throughout the system.
        if challenge.get("mode") == "github":
            return 0

        from engine.progression_tracker import SMELL_CURRICULUM
        smell_type = challenge.get("smell_type")
        try:
            pos = SMELL_CURRICULUM.index(smell_type)
            return (pos // 5) + 1   # 1, 2, or 3
        except ValueError:
            return 1

    def _error(self, message: str) -> dict:
        return {"success": False, "error": message}
