"""
Open World / GitHub Mode Routes — EduCode
==========================================

POST /world/analyze           — Build teaching plan from report or detector inputs
POST /world/analyze/repo      — Detector sidecar analysis for local Java directory
POST /world/analyze/github    — Detector sidecar analysis for GitHub Java repository
POST /world/analyze/code      — Detector sidecar analysis for Java snippet
POST /world/engage            — Start a hint session from a challenge (GitHub mode)
POST /world/solve             — Open World auto-refactor (returns fixed code + city_diff)
POST /world/advance           — Unlock next challenge after resolution
GET  /world/plan/<plan_id>    — Retrieve stored plan
GET  /world/detector/health   — Check sidecar detector status
"""

import json
from flask import Blueprint, request, jsonify, current_app

from engine.teaching_plan_engine import teaching_plan_engine
from engine.engage_engine import EngageEngine
from engine.refactor_engine import RefactorEngine
from engine.city_diff_generator import city_diff_generator
from engine.progression_tracker import progression_tracker
from engine.smell_definitions import get_smell_definition
from engine.session_store import session_store  # reused for plan TTL
from engine.smell_detector_client import (
    SmellDetectorError,
    analyze_code_to_analysis_report,
    analyze_repo_to_analysis_report,
    analyze_github_to_analysis_report,
    detector_health,
)

world_bp = Blueprint("world", __name__)

# Teaching plans use the same session_store but under a "plan:" namespace
# so they share the same 2-hour TTL and cleanup thread.
PLAN_PREFIX = "plan:"
SEVERITY_TO_LEVEL = {"info": 1, "warning": 2, "error": 3}


def _save_plan(plan_id: str, entry: dict):
    session_store.save(PLAN_PREFIX + plan_id, entry)


def _get_plan(plan_id: str) -> dict:
    return session_store.get(PLAN_PREFIX + plan_id)


def _update_plan(plan_id: str, entry: dict):
    session_store.save(PLAN_PREFIX + plan_id, entry)


def get_engage_engine():
    return EngageEngine(current_app.config["GEMINI_MODEL"])


def get_refactor_engine():
    return RefactorEngine(current_app.config["GEMINI_MODEL"])


def _require_fields(data, *fields):
    for f in fields:
        if f not in data or data[f] is None:
            return False, f"Missing required field: '{f}'"
    return True, ""


def _find_class_in_report(analysis_report: dict, class_name: str) -> dict:
    for cls in (analysis_report or {}).get("classes", []):
        if cls.get("class_name") == class_name:
            return cls
    return {}


def _coerce_analysis_report(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None, "analysis_report must be a JSON object (not an escaped string)"

    if not isinstance(value, dict):
        return None, "analysis_report must be a JSON object"

    value.setdefault("classes", [])
    value.setdefault("relationships", [])
    return value, ""


def _challenge_for_client(challenge: dict, analysis_report: dict | None = None) -> dict:
    output = dict(challenge)

    challenge_id = challenge.get("challenge_id") or challenge.get("id")
    severity_label = challenge.get("severity", "warning")
    hint_context = challenge.get("hint_context", {})

    output["challenge_id"] = challenge_id
    output["id"] = challenge_id
    output["severity_label"] = severity_label
    output["severity"] = SEVERITY_TO_LEVEL.get(severity_label, 2)

    if isinstance(hint_context, dict):
        output["educator_note"] = hint_context.get("enriched_feedback", "")
        output["hint_context"] = json.dumps(hint_context)
    else:
        output["educator_note"] = ""
        output["hint_context"] = str(hint_context)

    # Attach the class source code so Open World can round-trip it back to /world/solve
    # without needing a separate /world/engage call.
    if analysis_report is not None:
        class_data = _find_class_in_report(analysis_report, challenge.get("class_name", ""))
        output["source_code"] = class_data.get("source_code", "")

    return output


def _plan_for_client(plan: dict, student_id: str | None, analysis_report: dict | None = None) -> dict:
    active = [_challenge_for_client(c, analysis_report) for c in plan.get("active_challenges", [])]
    queued = [_challenge_for_client(c, analysis_report) for c in plan.get("queued_challenges", [])]

    return {
        **plan,
        "student_id": student_id,
        "active_challenges": active,
        "queued_challenges": queued,
        "active_challenge_count": len(active),
        "queued_challenge_count": len(queued),
        "total_challenge_count": len(active) + len(queued),
    }


def _build_analysis_report_from_request(data: dict):
    if "analysis_report" in data and data["analysis_report"] is not None:
        report, err = _coerce_analysis_report(data["analysis_report"])
        if err:
            return None, err
        return report, ""

    if data.get("repo_url"):
        report = analyze_github_to_analysis_report(
            repo_url=data["repo_url"],
            max_files=int(data.get("max_files", 100)),
        )
        return report, ""

    if data.get("directory"):
        report = analyze_repo_to_analysis_report(
            directory=data["directory"],
            max_files=int(data.get("max_files", 100)),
        )
        return report, ""

    if data.get("code"):
        report = analyze_code_to_analysis_report(
            code=data["code"],
            filename=data.get("filename", ""),
        )
        return report, ""

    return None, "Provide one of: analysis_report, repo_url, directory, or code"


# ── ANALYZE ───────────────────────────────────────────────────────────────────

@world_bp.route("/analyze", methods=["POST"])
def analyze():
    """
    Converts an AnalysisReport from the HybridAnalysisPipeline into
    a TeachingPlan for Open World or GitHub Mode.

    Request body:
    {
      "analysis_report": { ... },   ← full AnalysisReport from /analyze/repo or /analyze/github
      "student_id":      "uuid",    ← optional, enables adaptive prioritization
      "mode":            "open_world" | "github"
    }

    Response:
    {
      "success": true,
      "plan_id": "PLAN-OW-1234567890",
      "mode":    "open_world",
      "total_classes_analyzed": 12,
      "total_smells_found":     7,
      "active_challenges": [
        {
          "challenge_id":  "OrderProcessor-GodClass",
          "class_name":    "OrderProcessor",
          "smell_type":    "GodClass",
          "display_name":  "God Class",
          "principle":     "Single Responsibility Principle (SRP)",
          "severity":      "error",
          "confidence":    0.91,
          "priority":      1,
          "highlight_type":"error",
          "method_name":   null,
          "line_hint":     null,
          "sources":       ["ML", "PMD"],
          "hint_context":  { ... },
          "status":        "active"
        },
        ...up to 5 active
      ],
      "queued_challenges": [ ... ],
      "clean_classes":     ["UserProfile", "Config"],
      "summary":           "Found 7 issues in your repository..."
    }
    """
    data = request.get_json(silent=True) or {}
    student_id = data.get("student_id")
    mode = data.get("mode")

    if not mode:
        mode = "github" if data.get("repo_url") else "open_world"

    if mode not in ("open_world", "github"):
        return jsonify({
            "success": False,
            "error": "invalid_mode",
            "message": "mode must be 'open_world' or 'github'"
        }), 400

    try:
        analysis_report, err = _build_analysis_report_from_request(data)
        if err:
            return jsonify({
                "success": False,
                "error": "missing_input",
                "message": err,
            }), 400

        plan = teaching_plan_engine.build_plan(
            analysis_report=analysis_report,
            student_id=student_id,
            mode=mode,
        )

        # Store canonical plan server-side (raw shapes for internal use).
        _save_plan(plan["plan_id"], {
            "plan": plan,
            "analysis_report": analysis_report,
            "student_id": student_id,
            "mode": mode,
        })

        client_plan = _plan_for_client(plan, student_id, analysis_report)
        return jsonify({"success": True, **client_plan}), 200
    except SmellDetectorError as exc:
        return jsonify({
            "success": False,
            "error": "detector_unavailable",
            "message": str(exc),
        }), 503


@world_bp.route("/analyze/repo", methods=["POST"])
def analyze_repo():
    data = request.get_json(silent=True) or {}
    ok, err = _require_fields(data, "directory")
    if not ok:
        return jsonify({"error": "missing_field", "message": err}), 400

    try:
        report = analyze_repo_to_analysis_report(
            directory=data["directory"],
            max_files=int(data.get("max_files", 100)),
        )
        return jsonify(report), 200
    except SmellDetectorError as exc:
        return jsonify({"error": "detector_unavailable", "message": str(exc)}), 503


@world_bp.route("/analyze/github", methods=["POST"])
def analyze_github():
    data = request.get_json(silent=True) or {}
    ok, err = _require_fields(data, "repo_url")
    if not ok:
        return jsonify({"error": "missing_field", "message": err}), 400

    try:
        report = analyze_github_to_analysis_report(
            repo_url=data["repo_url"],
            max_files=int(data.get("max_files", 100)),
        )
        return jsonify(report), 200
    except SmellDetectorError as exc:
        return jsonify({"error": "detector_unavailable", "message": str(exc)}), 503


@world_bp.route("/analyze/code", methods=["POST"])
def analyze_code():
    data = request.get_json(silent=True) or {}
    ok, err = _require_fields(data, "code")
    if not ok:
        return jsonify({"error": "missing_field", "message": err}), 400

    try:
        report = analyze_code_to_analysis_report(
            code=data["code"],
            filename=data.get("filename", ""),
        )
        return jsonify(report), 200
    except SmellDetectorError as exc:
        return jsonify({"error": "detector_unavailable", "message": str(exc)}), 503


# ── ENGAGE ────────────────────────────────────────────────────────────────────

@world_bp.route("/engage", methods=["POST"])
def engage():
    """
    Starts a hint session for a specific challenge from a TeachingPlan.
    Called when the student walks up to a damaged building and chooses to engage.

    Request body:
    {
      "plan_id":      "PLAN-OW-...",
      "challenge_id": "OrderProcessor-GodClass"
    }

    Response:
    {
      "success":      true,
      "puzzle_id":    "OW-OrderProcessor-GodClass-1234567890",  ← use for /hint and /validate
      "smell_type":   "GodClass",
      "display_name": "God Class",
      "principle":    "Single Responsibility Principle (SRP)",
      "class_name":   "OrderProcessor",
      "method_name":  null,
      "file_path":    "src/main/java/OrderProcessor.java",
      "mode":         "open_world",
      "severity":     "error",
      "highlight_type":"error",
      "educator_note":"This class manages orders, payments, and notifications...",
      "source_code":  "public class OrderProcessor { ... }"
    }

    After this call, use puzzle_id with the existing:
      POST /edumode/hint
      POST /edumode/hint/replay
      POST /edumode/validate
    """
    data = request.get_json(silent=True) or {}

    challenge_id = data.get("challenge_id") or data.get("id")

    ok, err = _require_fields({**data, "challenge_id": challenge_id}, "plan_id", "challenge_id")
    if not ok:
        return jsonify({"success": False, "error": "missing_field", "message": err}), 400

    plan_id = data["plan_id"]

    # Retrieve stored plan
    plan_entry = _get_plan(plan_id)
    if not plan_entry:
        return jsonify({
            "success": False,
            "error": "plan_not_found",
            "message": f"No teaching plan found for plan_id '{plan_id}'. "
                       f"Call /world/analyze first."
        }), 404

    # Find the challenge in active or queued list
    plan = plan_entry["plan"]
    all_challenges = (
        plan.get("active_challenges", []) +
        plan.get("queued_challenges", [])
    )
    challenge = next(
        (
            c for c in all_challenges
            if c.get("challenge_id") == challenge_id or c.get("id") == challenge_id
        ),
        None
    )

    if not challenge:
        return jsonify({
            "success": False,
            "error": "challenge_not_found",
            "message": f"Challenge '{challenge_id}' not found in plan '{plan_id}'."
        }), 404

    # Prevent engaging with a queued (not yet unlocked) challenge
    if challenge.get("status") == "queued":
        return jsonify({
            "success": False,
            "error": "challenge_locked",
            "message": "This challenge is not yet unlocked. Complete an active challenge first."
        }), 403

    engage_engine = get_engage_engine()
    result = engage_engine.engage(
        challenge=challenge,
        analysis_report=plan_entry["analysis_report"],
        mode=plan_entry["mode"],
        student_id=plan_entry.get("student_id")
    )

    return jsonify(result), 200 if result.get("success") else 422


# ── ADVANCE PLAN ──────────────────────────────────────────────────────────────

@world_bp.route("/advance", methods=["POST"])
def advance_plan():
    """
    Marks a challenge as complete and unlocks the next queued one.
    Call this after /validate confirms smell_resolved = true.

    Request body:
    {
      "plan_id":      "PLAN-OW-...",
      "challenge_id": "OrderProcessor-GodClass"
    }

    Response:
    {
      "success":             true,
      "unlocked_challenge":  { ChallengeItem } | null,
      "remaining_active":    int,
      "remaining_queued":    int,
      "all_complete":        bool
    }
    """
    data = request.get_json(silent=True) or {}

    challenge_id = data.get("challenge_id") or data.get("id")

    ok, err = _require_fields({**data, "challenge_id": challenge_id}, "plan_id", "challenge_id")
    if not ok:
        return jsonify({"success": False, "error": "missing_field", "message": err}), 400

    plan_entry = _get_plan(data["plan_id"])
    if not plan_entry:
        return jsonify({
            "success": False, "error": "plan_not_found",
            "message": f"Plan '{data['plan_id']}' not found."
        }), 404

    plan = plan_entry["plan"]
    updated_plan = teaching_plan_engine.mark_challenge_complete(
        plan, challenge_id
    )
    plan_entry["plan"] = updated_plan
    _update_plan(data["plan_id"], plan_entry)

    active = updated_plan.get("active_challenges", [])
    queued = updated_plan.get("queued_challenges", [])

    # The newly unlocked challenge is the last item added to active
    # (mark_challenge_complete → unlock_next_challenge appends to active)
    newly_unlocked = None
    if active:
        candidate = active[-1]
        if candidate["status"] == "active":
            newly_unlocked = _challenge_for_client(candidate, plan_entry.get("analysis_report"))

    return jsonify({
        "success": True,
        "unlocked_challenge": newly_unlocked,
        "remaining_active": len(active),
        "remaining_queued": len(queued),
        "all_complete": len(active) == 0 and len(queued) == 0
    }), 200


# ── SOLVE (Open World only — auto-refactor) ───────────────────────────────────

@world_bp.route("/solve", methods=["POST"])
def solve_challenge():
    """
    Open World Mode auto-solve.

    Unity sends the Java class carrying the smell; the server returns the
    refactored version and a city_diff so the 3D city rebuilds the affected
    building(s). This replaces the hint + validate + advance flow for
    Open World. GitHub Mode must continue using /world/engage + /edumode/hint +
    /edumode/validate.

    Request body:
    {
      "plan_id":                "PLAN-OW-...",
      "challenge_id":           "OrderProcessor-GodClass",
      "source_code":            "public class OrderProcessor { ... }",
      "original_city_class":    { ...cityData class entry... },   ← optional, needed for rich city_diff
      "original_relationships": [ ... ]                           ← optional
    }

    Response (success):
    {
      "success":          true,
      "smell_type":       "GodClass",
      "display_name":     "God Class",
      "class_name":       "OrderProcessor",
      "refactored_code":  "...",
      "summary":          "Split into OrderProcessor + PaymentService + Notifier.",
      "city_diff":        { ...same schema as /edumode/validate... },
      "unlocked_challenge": { ... } | null,
      "remaining_active": 4,
      "remaining_queued": 2,
      "all_complete":     false
    }
    """
    data = request.get_json(silent=True) or {}

    challenge_id = data.get("challenge_id") or data.get("id")

    ok, err = _require_fields(
        {**data, "challenge_id": challenge_id},
        "plan_id", "challenge_id", "source_code",
    )
    if not ok:
        return jsonify({"success": False, "error": "missing_field", "message": err}), 400

    plan_entry = _get_plan(data["plan_id"])
    if not plan_entry:
        return jsonify({
            "success": False,
            "error": "plan_not_found",
            "message": f"No teaching plan found for plan_id '{data['plan_id']}'. "
                       f"Call /world/analyze first."
        }), 404

    # Open World only — GitHub mode keeps the interactive engage/validate flow.
    if plan_entry.get("mode") != "open_world":
        return jsonify({
            "success": False,
            "error": "mode_not_supported",
            "message": "/world/solve is only available in open_world mode. "
                       "GitHub mode must use /world/engage + /edumode/validate."
        }), 400

    plan = plan_entry["plan"]
    all_challenges = (
        plan.get("active_challenges", []) +
        plan.get("queued_challenges", [])
    )
    challenge = next(
        (
            c for c in all_challenges
            if c.get("challenge_id") == challenge_id or c.get("id") == challenge_id
        ),
        None
    )

    if not challenge:
        return jsonify({
            "success": False,
            "error": "challenge_not_found",
            "message": f"Challenge '{challenge_id}' not found in plan '{data['plan_id']}'."
        }), 404

    if challenge.get("status") == "queued":
        return jsonify({
            "success": False,
            "error": "challenge_locked",
            "message": "This challenge is not yet unlocked. Solve an active challenge first."
        }), 403

    smell_type = challenge.get("smell_type", "")
    class_name = challenge.get("class_name", "")
    smell_def = get_smell_definition(smell_type) or {"display_name": smell_type}

    # 1. Gemini auto-refactor
    refactor_engine = get_refactor_engine()
    refactor_result = refactor_engine.refactor(
        source_code=data["source_code"],
        smell_type=smell_type,
    )

    if not refactor_result.get("success"):
        return jsonify({
            "success": False,
            "error": "refactor_failed",
            "message": refactor_result.get("error", "Gemini refactor failed"),
        }), 502

    refactored_code = refactor_result["refactored_code"]
    summary = refactor_result.get("summary", "")

    # 2. Generate city_diff (same branching as /edumode/validate)
    original_city_class = data.get("original_city_class")
    original_relationships = data.get("original_relationships", [])

    if original_city_class:
        city_diff = city_diff_generator.generate_diff(
            puzzle_id=challenge_id,
            smell_type=smell_type,
            original_city_class=original_city_class,
            refactored_code=refactored_code,
            original_relationships=original_relationships,
        )
    else:
        # Unity didn't pass the cityData entry — return a minimal signal so
        # the client still knows which building to refresh.
        city_diff = {
            "success": True,
            "puzzle_id": challenge_id,
            "smell_type": smell_type,
            "affected_class": class_name,
            "change_type": "modified",
            "city_patch": {
                "updated_classes": [],
                "added_classes": [],
                "removed_classes": [],
                "updated_relationships": [],
                "added_relationships": [],
                "removed_relationships": [],
            },
            "rebuild_targets": [class_name] if class_name else [],
        }

    # 3. Mark challenge complete and unlock next (same as /world/advance)
    updated_plan = teaching_plan_engine.mark_challenge_complete(plan, challenge_id)
    plan_entry["plan"] = updated_plan
    _update_plan(data["plan_id"], plan_entry)

    active = updated_plan.get("active_challenges", [])
    queued = updated_plan.get("queued_challenges", [])

    newly_unlocked = None
    if active:
        candidate = active[-1]
        if candidate.get("status") == "active":
            newly_unlocked = _challenge_for_client(candidate, plan_entry.get("analysis_report"))

    # 4. Progression tracking (mirrors /edumode/validate success path)
    student_id = plan_entry.get("student_id")
    if student_id:
        try:
            from engine.progression_tracker import SMELL_CURRICULUM
            try:
                pos = SMELL_CURRICULUM.index(smell_type)
                inferred_difficulty = (pos // 5) + 1
            except ValueError:
                inferred_difficulty = 1

            progression_tracker.record_completion(
                student_id=student_id,
                puzzle_id=challenge_id,
                smell_type=smell_type,
                score=100,
                stars=3,
                hints_used=0,
                difficulty=inferred_difficulty,
            )
        except Exception as exc:  # progression is best-effort, never blocks /solve
            print(f"[/world/solve] progression record failed: {exc}")

    return jsonify({
        "success": True,
        "smell_type": smell_type,
        "display_name": smell_def.get("display_name", smell_type),
        "class_name": class_name,
        "refactored_code": refactored_code,
        "summary": summary,
        "city_diff": city_diff,
        "unlocked_challenge": newly_unlocked,
        "remaining_active": len(active),
        "remaining_queued": len(queued),
        "all_complete": len(active) == 0 and len(queued) == 0,
    }), 200


# ── GET PLAN ──────────────────────────────────────────────────────────────────

@world_bp.route("/plan/<plan_id>", methods=["GET"])
def get_plan(plan_id):
    """
    Retrieve a stored TeachingPlan by plan_id.
    Useful if Unity needs to re-render the city state after a reconnect.
    """
    plan_entry = _get_plan(plan_id)
    if not plan_entry:
        return jsonify({
            "success": False, "error": "plan_not_found",
            "message": f"Plan '{plan_id}' not found."
        }), 404

    client_plan = _plan_for_client(
        plan_entry["plan"],
        plan_entry.get("student_id"),
        plan_entry.get("analysis_report"),
    )
    return jsonify({"success": True, **client_plan}), 200


@world_bp.route("/detector/health", methods=["GET"])
def world_detector_health():
    try:
        health = detector_health()
        return jsonify({"success": True, **health}), 200
    except SmellDetectorError as exc:
        return jsonify({"success": False, "error": "detector_unavailable", "message": str(exc)}), 503
