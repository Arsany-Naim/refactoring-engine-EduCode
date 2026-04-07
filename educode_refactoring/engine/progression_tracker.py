"""
Progression Tracker — EduCode Refactoring Engine
==================================================
Tracks which smells a student has completed, their scores,
and computes what they should tackle next (adaptive difficulty).

Storage: in-memory per student_id.
In production, persist to PostgreSQL via DatabaseService.
"""

import time
from typing import Optional
from engine.smell_definitions import get_all_smell_types, get_smell_definition

# Smell types ordered by typical teaching progression
# (simpler / more visual smells first, structural ones later)
SMELL_CURRICULUM = [
    # Tier 1 — Beginner: immediately visible
    "LongMethod",
    "LongParameterList",
    "DeadCode",
    "DeepNesting",
    "DuplicatedCode",

    # Tier 2 — Intermediate: requires understanding OOP
    "DataClass",
    "FeatureEnvy",
    "LazyClass",
    "ComplexConditional",
    "MessageChain",

    # Tier 3 — Advanced: architectural smells
    "GodClass",
    "HighCoupling",
    "MiddleMan",
    "RefusedBequest",
    "ShotgunSurgery",
]

# Difficulty unlock thresholds (score needed to advance difficulty)
DIFFICULTY_UNLOCK_SCORE = {
    1: 60,   # need 60+ average to unlock difficulty 2
    2: 75,   # need 75+ average to unlock difficulty 3
}


class ProgressionTracker:
    """
    Per-student progression state.

    completion_record schema per smell:
    {
        "smell_type": str,
        "attempts": int,
        "best_score": int,
        "stars_earned": int,
        "hints_used_on_best": int,
        "completed_at": float,
        "difficulty_beaten": int   (1, 2, or 3)
    }
    """

    def __init__(self):
        # student_id → { "records": [...], "created_at": float }
        self._students: dict[str, dict] = {}

    # ── PUBLIC API ─────────────────────────────────────────────────────────

    def record_completion(
        self,
        student_id: str,
        puzzle_id: str,
        smell_type: str,
        score: int,
        stars: int,
        hints_used: int,
        difficulty: int
    ) -> dict:
        """
        Records a completed puzzle attempt. Returns updated progression state.

        difficulty=0 means "GitHub real-world mode" — no curriculum level.
        These completions count toward the student's mastered smells but
        do not affect difficulty unlock calculations.
        """
        self._ensure_student(student_id)
        student = self._students[student_id]

        existing = self._find_record(student, smell_type, difficulty)

        if existing:
            if score > existing["best_score"]:
                existing["best_score"] = score
                existing["stars_earned"] = stars
                existing["hints_used_on_best"] = hints_used
            existing["attempts"] += 1
        else:
            student["records"].append({
                "smell_type": smell_type,
                "difficulty": difficulty,
                "mode": "github" if difficulty == 0 else "curriculum",
                "attempts": 1,
                "best_score": score,
                "stars_earned": stars,
                "hints_used_on_best": hints_used,
                "completed_at": time.time(),
                "difficulty_beaten": difficulty if score >= 60 and difficulty > 0 else 0
            })

        return self.get_progress(student_id)

    def get_progress(self, student_id: str) -> dict:
        """Returns full progression state for a student."""
        self._ensure_student(student_id)
        student = self._students[student_id]
        records = student["records"]

        completed_smells = {
            r["smell_type"] for r in records
            if r.get("best_score", 0) >= 60
            # difficulty=0 = GitHub real-world, still counts as mastered
        }

        unlocked_difficulty = self._compute_unlocked_difficulty(records)
        next_smell = self._suggest_next_smell(completed_smells, unlocked_difficulty)
        total_stars = sum(r.get("stars_earned", 0) for r in records)
        average_score = (
            sum(r.get("best_score", 0) for r in records) / len(records)
            if records else 0
        )

        return {
            "student_id": student_id,
            "total_puzzles_completed": len(completed_smells),
            "total_stars": total_stars,
            "average_score": round(average_score, 1),
            "unlocked_difficulty": unlocked_difficulty,
            "completed_smells": sorted(list(completed_smells)),
            "pending_smells": [
                s for s in SMELL_CURRICULUM if s not in completed_smells
            ],
            "next_recommended": next_smell,
            "curriculum_progress": self._curriculum_progress(completed_smells),
            "records": records
        }

    def get_recommended_puzzle(self, student_id: str) -> dict:
        """
        Returns the recommended next smell + difficulty for this student.
        Used by /edumode/generate when no smell_type is specified.
        """
        self._ensure_student(student_id)
        progress = self.get_progress(student_id)

        smell_type = progress["next_recommended"]
        difficulty = progress["unlocked_difficulty"]

        # Retry an already-seen smell at higher difficulty if available
        records = self._students[student_id]["records"]
        for r in records:
            if (r["smell_type"] == smell_type and
                    r.get("best_score", 0) >= 60 and
                    r["difficulty"] < difficulty):
                return {
                    "smell_type": smell_type,
                    "difficulty": min(r["difficulty"] + 1, difficulty),
                    "reason": "mastery_challenge"
                }

        return {
            "smell_type": smell_type,
            "difficulty": difficulty,
            "reason": "curriculum_progression"
        }

    def has_completed(self, student_id: str, smell_type: str, difficulty: int = 1) -> bool:
        self._ensure_student(student_id)
        record = self._find_record(self._students[student_id], smell_type, difficulty)
        return record is not None and record.get("best_score", 0) >= 60

    # ── INTERNAL ───────────────────────────────────────────────────────────

    def _ensure_student(self, student_id: str):
        if student_id not in self._students:
            self._students[student_id] = {
                "records": [],
                "created_at": time.time()
            }

    def _find_record(self, student: dict, smell_type: str, difficulty: int) -> Optional[dict]:
        for r in student["records"]:
            if r["smell_type"] == smell_type and r["difficulty"] == difficulty:
                return r
        return None

    def _compute_unlocked_difficulty(self, records: list) -> int:
        """
        Difficulty 2 unlocks when average score on difficulty-1 puzzles >= 60.
        Difficulty 3 unlocks when average score on difficulty-2 puzzles >= 75.

        Returns the highest difficulty the student is allowed to play.
        """
        max_unlocked = 1

        for unlock_difficulty, prev_difficulty in [(2, 1), (3, 2)]:
            prev_records = [
                r for r in records
                if r["difficulty"] == prev_difficulty and r.get("best_score", 0) > 0
            ]
            if not prev_records:
                # No attempts at prev_difficulty yet — can't unlock next tier
                break

            avg = sum(r["best_score"] for r in prev_records) / len(prev_records)
            threshold = DIFFICULTY_UNLOCK_SCORE[prev_difficulty]
            if avg >= threshold:
                max_unlocked = unlock_difficulty
            else:
                break   # threshold not met, stop checking higher tiers

        return max_unlocked

    def _suggest_next_smell(self, completed: set, difficulty: int) -> str:
        """
        Suggests the next smell from the curriculum the student hasn't beaten yet.
        Falls back to a random smell at higher difficulty if all are completed.
        """
        import random
        for smell in SMELL_CURRICULUM:
            if smell not in completed:
                return smell
        # All smells completed — suggest random at current difficulty
        return random.choice(SMELL_CURRICULUM)

    def _curriculum_progress(self, completed: set) -> dict:
        """Returns tier-by-tier progress."""
        tier1 = SMELL_CURRICULUM[:5]
        tier2 = SMELL_CURRICULUM[5:10]
        tier3 = SMELL_CURRICULUM[10:]
        return {
            "tier1_beginner": {
                "completed": len([s for s in tier1 if s in completed]),
                "total": len(tier1)
            },
            "tier2_intermediate": {
                "completed": len([s for s in tier2 if s in completed]),
                "total": len(tier2)
            },
            "tier3_advanced": {
                "completed": len([s for s in tier3 if s in completed]),
                "total": len(tier3)
            }
        }


# ── Singleton ─────────────────────────────────────────────────────────────────
progression_tracker = ProgressionTracker()
