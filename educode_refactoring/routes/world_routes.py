"""
Open World / GitHub Mode Routes — EduCode
==========================================

POST /world/analyze           — Build teaching plan from report or detector inputs
POST /world/analyze/repo      — Detector sidecar analysis for local Java directory
POST /world/analyze/github    — Detector sidecar analysis for GitHub Java repository
POST /world/analyze/code      — Detector sidecar analysis for Java snippet
POST /world/engage            — Start a hint session from a challenge
POST /world/advance           — Unlock next challenge after resolution
GET  /world/plan/<plan_id>    — Retrieve stored plan
GET  /world/detector/health   — Check sidecar detector status
"""

import json
from flask import Blueprint, request, jsonify, current_app

from engine.teaching_plan_engine import teaching_plan_engine
from engine.engage_engine import EngageEngine
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


def _require_fields(data, *fields):
    for f in fields:
        if f not in data or data[f] is None:
            return False, f"Missing required field: '{f}'"
    return True, ""


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


def _challenge_for_client(challenge: dict) -> dict:
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

    return output


def _plan_for_client(plan: dict, student_id: str | None) -> dict:
    active = [_challenge_for_client(c) for c in plan.get("active_challenges", [])]
    queued = [_challenge_for_client(c) for c in plan.get("queued_challenges", [])]

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

        client_plan = _plan_for_client(plan, student_id)
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
            newly_unlocked = _challenge_for_client(candidate)

    return jsonify({
        "success": True,
        "unlocked_challenge": newly_unlocked,
        "remaining_active": len(active),
        "remaining_queued": len(queued),
        "all_complete": len(active) == 0 and len(queued) == 0
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

    client_plan = _plan_for_client(plan_entry["plan"], plan_entry.get("student_id"))
    return jsonify({"success": True, **client_plan}), 200


@world_bp.route("/detector/health", methods=["GET"])
def world_detector_health():
    try:
        health = detector_health()
        return jsonify({"success": True, **health}), 200
    except SmellDetectorError as exc:
        return jsonify({"success": False, "error": "detector_unavailable", "message": str(exc)}), 503
