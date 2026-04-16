"""
Routes — EduCode Refactoring Game Endpoints
============================================
All sessions are stored server-side. Unity only passes puzzle_id.

Changes:
  - /validate now returns city_diff so Unity rebuilds affected buildings
  - difficulty is ignored / stripped for github mode sessions
"""

from flask import Blueprint, request, jsonify, current_app
from engine.code_generator import CodeGenerator
from engine.hint_engine import HintEngine
from engine.validator import RefactoringValidator
from engine.city_diff_generator import city_diff_generator
from engine.session_store import session_store
from engine.progression_tracker import progression_tracker

edumode_bp = Blueprint("edumode", __name__)


def get_engines():
    gemini_model = current_app.config["GEMINI_MODEL"]
    return (
        CodeGenerator(gemini_model),
        HintEngine(gemini_model),
        RefactoringValidator(gemini_model)
    )


def _require_fields(data, *fields):
    for f in fields:
        if f not in data or data[f] is None:
            return False, f"Missing required field: '{f}'"
    return True, ""


def _get_session(puzzle_id):
    session = session_store.get(puzzle_id)
    if not session:
        return None, (jsonify({
            "success": False,
            "error": "session_not_found",
            "message": f"No active session for puzzle_id '{puzzle_id}'. Sessions expire after 2 hours."
        }), 404)
    return session, None


def _is_github_mode(session: dict) -> bool:
    return session.get("mode") == "github"


# ── GENERATE ─────────────────────────────────────────────────────────────────

@edumode_bp.route("/generate", methods=["POST"])
def generate_puzzle():
    """
    Escape Room mode only.
    difficulty is respected here (1/2/3) — Escape Room is curriculum-driven.
    """
    generator, _, _ = get_engines()
    data = request.get_json(silent=True) or {}

    smell_type = data.get("smell_type")
    difficulty = data.get("difficulty", 1)
    theme = data.get("theme")
    student_id = data.get("student_id")

    if student_id and not smell_type:
        rec = progression_tracker.get_recommended_puzzle(student_id)
        smell_type = rec["smell_type"]
        if "difficulty" not in data:
            difficulty = rec["difficulty"]

    result = generator.generate(smell_type=smell_type, difficulty=difficulty, theme=theme)
    if not result.get("success"):
        return jsonify(result), 422

    session = result.pop("session")
    session["student_id"] = student_id
    session["mode"] = "escape_room"
    session_store.save(result["puzzle_id"], session)

    return jsonify(result), 200


# ── HINT ──────────────────────────────────────────────────────────────────────

@edumode_bp.route("/hint", methods=["POST"])
def get_hint():
    _, hint_engine, _ = get_engines()
    data = request.get_json(silent=True) or {}

    ok, err = _require_fields(data, "puzzle_id")
    if not ok:
        return jsonify({"success": False, "error": "missing_field", "message": err}), 400

    session, err_resp = _get_session(data["puzzle_id"])
    if err_resp:
        return err_resp

    result = hint_engine.get_next_hint(session)

    if result.get("success"):
        updated = result.pop("updated_session")
        session_store.save(data["puzzle_id"], updated)

    return jsonify(result), 200 if result.get("success") else 422


# ── HINT REPLAY ───────────────────────────────────────────────────────────────

@edumode_bp.route("/hint/replay", methods=["POST"])
def replay_hint():
    _, hint_engine, _ = get_engines()
    data = request.get_json(silent=True) or {}

    ok, err = _require_fields(data, "puzzle_id", "stage")
    if not ok:
        return jsonify({"success": False, "error": "missing_field", "message": err}), 400

    session, err_resp = _get_session(data["puzzle_id"])
    if err_resp:
        return err_resp

    result = hint_engine.get_specific_hint(session, int(data["stage"]))
    result.pop("updated_session", None)
    return jsonify(result), 200 if result.get("success") else 422


# ── VALIDATE ─────────────────────────────────────────────────────────────────

@edumode_bp.route("/validate", methods=["POST"])
def validate_refactoring():
    """
    Validates the student's refactored code and — on success — generates
    a city_diff that Unity uses to rebuild only the affected buildings.

    Request body:
    {
      "puzzle_id":          "...",
      "refactored_code":    "...full refactored Java source...",
      "original_code":      "...original Java source...",       ← optional
      "original_city_class": {                                  ← optional but needed for city_diff
        "name": "OrderProcessor",
        "type": "class",
        "methods": [...],
        "constructors": [...],
        "methodParameters": [...],
        "attributes": [...],
        "linesOfCode": 200
      },
      "original_relationships": [...]                           ← optional, all rels from cityData.json
    }

    Response (on smell_resolved = true):
    {
      "success":         true,
      "score":           87,
      "smell_resolved":  true,
      "stars":           3,
      "feedback":        "...",
      "city_diff": {
        "success":        true,
        "affected_class": "OrderProcessor",
        "change_type":    "split",
        "city_patch": {
          "updated_classes":       [ { cityData class entry } ],
          "added_classes":         [ { cityData class entry } ],
          "removed_classes":       [],
          "added_relationships":   [ { from, to, type } ],
          "removed_relationships": [],
          "updated_relationships": []
        },
        "rebuild_targets": ["OrderProcessor", "OrderValidator"]
      }
    }

    Response (on smell_resolved = false):
    {
      "success":        true,
      "score":          45,
      "smell_resolved": false,
      "feedback":       "...",
      "city_diff":      null   ← no city change until smell is actually fixed
    }
    """
    _, _, validator = get_engines()
    data = request.get_json(silent=True) or {}

    ok, err = _require_fields(data, "puzzle_id", "refactored_code")
    if not ok:
        return jsonify({"success": False, "error": "missing_field", "message": err}), 400

    session, err_resp = _get_session(data["puzzle_id"])
    if err_resp:
        return err_resp

    result = validator.validate(
        session,
        data.get("original_code", ""),
        data["refactored_code"]
    )

    if not result.get("success"):
        return jsonify(result), 422

    updated_session = result.pop("updated_session")
    session_store.save(data["puzzle_id"], updated_session)

    # ── City diff — only generated when smell is actually resolved ────────────
    city_diff = None
    if result.get("smell_resolved"):
        original_city_class   = data.get("original_city_class")
        original_relationships = data.get("original_relationships", [])

        if original_city_class:
            city_diff = city_diff_generator.generate_diff(
                puzzle_id=data["puzzle_id"],
                smell_type=session.get("smell_type", ""),
                original_city_class=original_city_class,
                refactored_code=data["refactored_code"],
                original_relationships=original_relationships
            )
        else:
            # No city class provided — return a minimal signal so Unity knows to refresh
            city_diff = {
                "success": True,
                "puzzle_id": data["puzzle_id"],
                "smell_type": session.get("smell_type", ""),
                "affected_class": session.get("affected_class", ""),
                "change_type": "modified",
                "city_patch": {
                    "updated_classes": [],
                    "added_classes": [],
                    "removed_classes": [],
                    "updated_relationships": [],
                    "added_relationships": [],
                    "removed_relationships": []
                },
                "rebuild_targets": [session.get("affected_class", "")]
            }

    result["city_diff"] = city_diff

    # ── Progression tracking (GitHub mode skips difficulty) ───────────────────
    student_id = session.get("student_id")
    mode = session.get("mode", "escape_room")

    if student_id and result.get("smell_resolved"):
        # GitHub mode has no difficulty — record as difficulty 0 (real-world)
        record_difficulty = 0 if mode == "github" else session.get("difficulty", 1)
        progression = progression_tracker.record_completion(
            student_id=student_id,
            puzzle_id=data["puzzle_id"],
            smell_type=session["smell_type"],
            score=result["score"],
            stars=result["stars"],
            hints_used=len(session.get("hints_seen", [])),
            difficulty=record_difficulty
        )
        result["progression"] = progression

    return jsonify(result), 200


# ── PROGRESS ─────────────────────────────────────────────────────────────────

@edumode_bp.route("/progress/<student_id>", methods=["GET"])
def get_progress(student_id):
    progress = progression_tracker.get_progress(student_id)
    return jsonify({"success": True, **progress})


# ── RECOMMEND ────────────────────────────────────────────────────────────────

@edumode_bp.route("/recommend/<student_id>", methods=["GET"])
def get_recommendation(student_id):
    from engine.smell_definitions import get_smell_definition
    rec = progression_tracker.get_recommended_puzzle(student_id)
    defn = get_smell_definition(rec["smell_type"])
    return jsonify({
        "success": True,
        **rec,
        "display_name": defn["display_name"] if defn else rec["smell_type"],
        "principle": defn["principle"] if defn else ""
    })


# ── SMELLS ───────────────────────────────────────────────────────────────────

@edumode_bp.route("/smells", methods=["GET"])
def list_smells():
    from engine.progression_tracker import SMELL_CURRICULUM
    generator, _, _ = get_engines()
    smells = generator.get_available_smells()
    tier_map = {s: 1 for s in SMELL_CURRICULUM[:5]}
    tier_map.update({s: 2 for s in SMELL_CURRICULUM[5:10]})
    tier_map.update({s: 3 for s in SMELL_CURRICULUM[10:]})
    for s in smells:
        s["tier"] = tier_map.get(s["smell_type"], 1)
    return jsonify({"success": True, "smells": smells, "count": len(smells)})


# ── HEALTH ───────────────────────────────────────────────────────────────────

@edumode_bp.route("/health", methods=["GET"])
def health():
    return jsonify({
        "success": True,
        "service": "EduCode Refactoring Engine",
        "status": "operational",
        "active_sessions": session_store.count(),
        "endpoints": [
            "POST /edumode/generate",
            "POST /edumode/hint",
            "POST /edumode/hint/replay",
            "POST /edumode/validate  ← returns city_diff on success",
            "POST /world/solve  ← Open World auto-refactor (returns refactored code + city_diff)",
            "GET  /edumode/progress/<student_id>",
            "GET  /edumode/recommend/<student_id>",
            "GET  /edumode/smells",
            "GET  /edumode/health"
        ]
    })
