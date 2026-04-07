"""
Teaching Plan Engine — EduCode Open World / GitHub Mode
=========================================================
Consumes an AnalysisReport from the existing HybridAnalysisPipeline
and produces a TeachingPlan: a prioritized, sequenced list of smells
across all classes — ordered by teachability for this specific student.

AnalysisReport schema (from your existing backend):
{
  "classes": [
    {
      "class_name": str,
      "file_path":  str,
      "metrics":    { "loc": int, "wmc": int, "cbo": int, ... },
      "smells": [
        {
          "type":        str,   e.g. "GodClass"
          "confidence":  float, 0.0-1.0
          "severity":    str,   "error"|"warning"|"info"
          "line_hint":   int,   optional
          "method_name": str,   optional
          "sources":     [str]  e.g. ["ML","PMD"]
        }
      ],
      "feedback": str   LLM-generated explanation
    }
  ],
  "relationships": [
    {
      "source": str,
      "target": str,
      "type":   str   "inheritance"|"dependency"|"composition"
    }
  ]
}
"""

import time
from typing import Optional
from engine.smell_definitions import (
    get_smell_definition,
    get_all_smell_types,
    get_highlight_type
)
from engine.progression_tracker import (
    SMELL_CURRICULUM,
    progression_tracker
)

# Maximum smells shown as active challenges at once
MAX_ACTIVE_CHALLENGES = 5

# Minimum confidence threshold to include a smell as a challenge
MIN_CONFIDENCE = 0.45

# Severity → numeric weight for sorting
SEVERITY_WEIGHT = {"error": 3, "warning": 2, "info": 1}

# How many sources agreeing boosts priority
SOURCE_BONUS = 0.15   # per additional source beyond first


class TeachingPlanEngine:

    def build_plan(
        self,
        analysis_report: dict,
        student_id: Optional[str] = None,
        mode: str = "open_world"   # "open_world" | "github"
    ) -> dict:
        """
        Converts an AnalysisReport into a TeachingPlan.

        Returns:
        {
          "plan_id": str,
          "mode": str,
          "total_smells_found": int,
          "active_challenges": [ChallengeItem],  ← shown to student now
          "queued_challenges":  [ChallengeItem],  ← unlocked as active ones resolve
          "clean_classes": [str],                 ← class names with no smells
          "summary": str                          ← one-sentence overview
        }

        ChallengeItem:
        {
          "challenge_id": str,
          "class_name":   str,
          "file_path":    str,
          "smell_type":   str,
          "display_name": str,
          "principle":    str,
          "severity":     str,
          "confidence":   float,
          "priority":     int,    1 = highest
          "highlight_type": str,
          "method_name":  str | null,
          "line_hint":    int | null,
          "sources":      [str],
          "hint_context": dict,   pre-filled from metrics
          "status":       "active" | "queued" | "completed"
        }
        """
        classes = analysis_report.get("classes", [])
        relationships = analysis_report.get("relationships", [])

        # 1. Extract all smell instances across all classes
        all_candidates = self._extract_candidates(classes, relationships)

        # 2. Filter by confidence
        candidates = [
            c for c in all_candidates
            if c["confidence"] >= MIN_CONFIDENCE
        ]

        # 3. Score and sort by teachability for this student
        unlocked_difficulty = 1
        completed_smells = set()
        if student_id:
            progress = progression_tracker.get_progress(student_id)
            unlocked_difficulty = progress.get("unlocked_difficulty", 1)
            completed_smells = set(progress.get("completed_smells", []))

        scored = self._score_candidates(
            candidates, student_id, completed_smells, unlocked_difficulty
        )
        scored.sort(key=lambda x: x["_score"], reverse=True)

        # 4. Assign priority numbers and split active vs queued
        for i, item in enumerate(scored):
            item["priority"] = i + 1
            item.pop("_score", None)

        active = []
        queued = []
        for item in scored:
            if len(active) < MAX_ACTIVE_CHALLENGES:
                item["status"] = "active"
                active.append(item)
            else:
                item["status"] = "queued"
                queued.append(item)

        # 5. Identify clean classes
        smelly_classes = {c["class_name"] for c in scored}
        clean_classes = [
            cls["class_name"] for cls in classes
            if cls["class_name"] not in smelly_classes
        ]

        # 6. Build summary
        summary = self._build_summary(active, queued, clean_classes, mode)

        mode_code = "OW" if mode == "open_world" else "GH"
        plan_id = f"PLAN-{mode_code}-{int(time.time())}"

        return {
            "plan_id": plan_id,
            "mode": mode,
            "total_classes_analyzed": len(classes),
            "total_smells_found": len(scored),
            "active_challenges": active,
            "queued_challenges": queued,
            "clean_classes": clean_classes,
            "summary": summary
        }

    def unlock_next_challenge(self, teaching_plan: dict) -> dict:
        """
        Moves the highest-priority queued challenge into active.
        Call this after a student completes an active challenge.
        Returns updated teaching_plan.
        """
        queued = teaching_plan.get("queued_challenges", [])
        active = teaching_plan.get("active_challenges", [])

        if not queued:
            return teaching_plan

        # Move first queued item to active
        next_challenge = queued.pop(0)
        next_challenge["status"] = "active"
        active.append(next_challenge)

        return {
            **teaching_plan,
            "active_challenges": active,
            "queued_challenges": queued
        }

    def mark_challenge_complete(
        self, teaching_plan: dict, challenge_id: str
    ) -> dict:
        """
        Marks a challenge as completed and unlocks the next queued one.
        """
        active = teaching_plan.get("active_challenges", [])
        for challenge in active:
            if challenge["challenge_id"] == challenge_id:
                challenge["status"] = "completed"
                break

        # Remove completed from active list
        teaching_plan["active_challenges"] = [
            c for c in active if c["status"] != "completed"
        ]

        # Unlock next
        return self.unlock_next_challenge(teaching_plan)

    # ── EXTRACTION ────────────────────────────────────────────────────────────

    def _extract_candidates(
        self, classes: list, relationships: list
    ) -> list:
        """Flatten all smells from all classes into candidate items."""
        candidates = []
        rel_map = self._build_relationship_map(relationships)

        for cls in classes:
            class_name = cls.get("class_name", "Unknown")
            file_path = cls.get("file_path", "")
            metrics = cls.get("metrics", {})
            smells = cls.get("smells", [])

            for smell in smells:
                smell_type = smell.get("type")
                if smell_type not in get_all_smell_types():
                    continue

                defn = get_smell_definition(smell_type)
                if not defn:
                    continue

                challenge_id = f"{class_name}-{smell_type}"
                hint_context = self._build_hint_context(
                    smell_type, cls, smell, metrics, rel_map
                )

                candidates.append({
                    "challenge_id": challenge_id,
                    "class_name": class_name,
                    "file_path": file_path,
                    "smell_type": smell_type,
                    "display_name": defn["display_name"],
                    "principle": defn["principle"],
                    "severity": smell.get("severity", "warning"),
                    "confidence": smell.get("confidence", 0.5),
                    "highlight_type": defn["highlight_type"],
                    "method_name": smell.get("method_name"),
                    "line_hint": smell.get("line_hint"),
                    "sources": smell.get("sources", ["ML"]),
                    "hint_context": hint_context,
                    "status": "active"
                })

        return candidates

    def _build_hint_context(
        self,
        smell_type: str,
        cls: dict,
        smell: dict,
        metrics: dict,
        rel_map: dict
    ) -> dict:
        """
        Pre-fills hint_context from real analysis metrics.
        These values flow directly into the 4-stage hint templates.
        """
        class_name = cls.get("class_name", "")
        methods = cls.get("methods", [])
        method_name = smell.get("method_name")

        ctx = {
            # Basic identity
            "class_name": class_name,
            "method_name": method_name,

            # Metric-driven context
            "line_count": metrics.get("loc", 0),
            "responsibility_count": self._estimate_responsibilities(metrics),
            "group_count": max(2, self._estimate_responsibilities(metrics) - 1),
            "param_count": self._get_param_count(methods, method_name),
            "dependency_count": metrics.get("cbo", 0),
            "method_count": metrics.get("nom", len(methods)),

            # Method lists
            "method_list": [m.get("name") for m in methods[:4] if m.get("name")],
            "param_list": self._get_param_names(methods, method_name),

            # Relationship context
            "envied_class": self._find_envied_class(rel_map, class_name),
            "concrete_dependency": self._find_main_dependency(rel_map, class_name),
            "parent_class": self._find_parent(rel_map, class_name),

            # Line range (for LongMethod hints)
            "start_line": smell.get("line_hint", 1),
            "end_line": (smell.get("line_hint", 1) or 1) + max(
                0, (metrics.get("loc", 20) // max(1, metrics.get("nom", 1))) - 5
            ),

            # Suggestions — generated from class/method names
            "suggested_method": self._suggest_method_name(
                smell_type, method_name, class_name
            ),
            "suggested_class": self._suggest_class_name(
                smell_type, class_name, methods
            ),
            "suggested_interface": f"I{self._find_main_dependency(rel_map, class_name) or class_name}",
            "suggested_object": f"{class_name}Request",

            # Misc
            "using_class": self._find_user_class(rel_map, class_name),
            "delegate_class": self._find_main_dependency(rel_map, class_name),
            "field_name": "delegate",
            "concept": class_name.lower().replace("manager", "").replace("service", ""),
            "condition": "the main condition",
            "line": smell.get("line_hint", 1),
            "grouped_params": [],
            "class_list": list(rel_map.get(class_name, {}).get("dependencies", set()))[:3],
            "access_count": max(3, metrics.get("cbo", 3)),
            "own_access_count": 1,
            "dead_element": method_name or "unusedMethod",
            "chain": f"get{class_name}().getData().getValue()",
            "start_class": class_name,
            "final_value": "the required value",
            "delegation_count": max(2, metrics.get("nom", 4) // 2),
            "total_methods": metrics.get("nom", 4),
            "delegating_method": method_name or "delegateMethod",
            "real_method": method_name or "realMethod",
            "foreign_class": self._find_envied_class(rel_map, class_name) or "OtherClass",
            "foreign_method": method_name or "foreignMethod",
            "method_a": methods[0].get("name") if len(methods) > 0 else "methodA",
            "method_b": methods[1].get("name") if len(methods) > 1 else "methodB",
        }
        return ctx

    # ── SCORING ───────────────────────────────────────────────────────────────

    def _score_candidates(
        self,
        candidates: list,
        student_id: Optional[str],
        completed_smells: set,
        unlocked_difficulty: int
    ) -> list:
        """
        Assigns a teachability score to each candidate.
        Higher score = show first.

        Factors:
          - Severity (error > warning > info)
          - Curriculum tier match (beginner smells first for beginners)
          - Multi-source confidence (ML + PMD + Checkstyle = more reliable)
          - Not already mastered by this student
          - Confidence score from ML pipeline
        """
        curriculum_index = {s: i for i, s in enumerate(SMELL_CURRICULUM)}

        for c in candidates:
            score = 0.0
            smell_type = c["smell_type"]

            # 1. Severity is the primary factor (weighted heavily)
            score += SEVERITY_WEIGHT.get(c["severity"], 1) * 3.0

            # 2. Confidence from ML (0-1)
            score += c["confidence"]

            # 3. Multi-source agreement bonus
            extra_sources = max(0, len(c["sources"]) - 1)
            score += extra_sources * SOURCE_BONUS

            # 4. Curriculum position — secondary tiebreaker within same severity
            curr_pos = curriculum_index.get(smell_type, 14)
            tier = (curr_pos // 5) + 1   # 1, 2, or 3
            if tier <= unlocked_difficulty:
                # In range — tier 1 smells get slight boost as tiebreaker only
                tier_score = (4 - tier) * 0.2
                score += tier_score
            else:
                # Above student's level — slight deprioritize
                score -= 0.3

            # 5. Already mastered — deprioritize (they know this one)
            if smell_type in completed_smells:
                score -= 2.0

            c["_score"] = score

        return candidates

    # ── HELPERS ───────────────────────────────────────────────────────────────

    def _build_relationship_map(self, relationships: list) -> dict:
        """
        Builds { class_name: { "dependencies": set, "parent": str, "users": set } }
        """
        rel_map = {}
        for rel in relationships:
            src = rel.get("source", "")
            tgt = rel.get("target", "")
            rel_type = rel.get("type", "")

            if src not in rel_map:
                rel_map[src] = {"dependencies": set(), "parent": None, "users": set()}
            if tgt not in rel_map:
                rel_map[tgt] = {"dependencies": set(), "parent": None, "users": set()}

            if rel_type == "inheritance":
                rel_map[src]["parent"] = tgt
            elif rel_type in ("dependency", "composition"):
                rel_map[src]["dependencies"].add(tgt)
                rel_map[tgt]["users"].add(src)

        return rel_map

    def _estimate_responsibilities(self, metrics: dict) -> int:
        """Estimate number of responsibilities from WMC and NOM."""
        wmc = metrics.get("wmc", 0)
        nom = metrics.get("nom", 0)
        if nom == 0:
            return 2
        avg_complexity = wmc / nom if nom > 0 else 1
        if nom >= 15 or avg_complexity >= 5:
            return 4
        if nom >= 8:
            return 3
        return 2

    def _get_param_count(self, methods: list, method_name: Optional[str]) -> int:
        if not method_name or not methods:
            return 4
        for m in methods:
            if m.get("name") == method_name:
                return len(m.get("parameters", []))
        return 4

    def _get_param_names(self, methods: list, method_name: Optional[str]) -> list:
        if not method_name or not methods:
            return ["param1", "param2", "param3"]
        for m in methods:
            if m.get("name") == method_name:
                return [p.get("name", f"p{i}") for i, p in
                        enumerate(m.get("parameters", []))]
        return []

    def _find_envied_class(self, rel_map: dict, class_name: str) -> Optional[str]:
        deps = rel_map.get(class_name, {}).get("dependencies", set())
        return next(iter(deps), None)

    def _find_main_dependency(self, rel_map: dict, class_name: str) -> Optional[str]:
        deps = rel_map.get(class_name, {}).get("dependencies", set())
        return next(iter(deps), None)

    def _find_parent(self, rel_map: dict, class_name: str) -> Optional[str]:
        return rel_map.get(class_name, {}).get("parent")

    def _find_user_class(self, rel_map: dict, class_name: str) -> Optional[str]:
        users = rel_map.get(class_name, {}).get("users", set())
        return next(iter(users), None)

    def _suggest_method_name(
        self,
        smell_type: str,
        method_name: Optional[str],
        class_name: str
    ) -> str:
        suggestions = {
            "LongMethod":       f"extract{class_name}Logic",
            "DuplicatedCode":   "extractSharedLogic",
            "ComplexConditional": f"is{class_name}Valid",
            "DeepNesting":      f"validate{class_name}",
            "FeatureEnvy":      method_name or "movedMethod",
            "MiddleMan":        method_name or "directMethod",
        }
        return suggestions.get(smell_type, method_name or "refactoredMethod")

    def _suggest_class_name(
        self,
        smell_type: str,
        class_name: str,
        methods: list
    ) -> str:
        suggestions = {
            "GodClass":      f"{class_name}Handler",
            "DataClass":     f"{class_name}Service",
            "ShotgunSurgery": f"{class_name}Manager",
            "LazyClass":     class_name,
        }
        return suggestions.get(smell_type, f"{class_name}Helper")

    def _build_summary(
        self,
        active: list,
        queued: list,
        clean_classes: list,
        mode: str
    ) -> str:
        """Generates a one-line summary of the teaching plan."""
        total = len(active) + len(queued)
        
        if mode == "github":
            return f"Found {total} code smell{'s' if total != 1 else ''} in your repository. Start with the {len(active)} most critical—then work your way through."
        else:
            return f"Discovered {total} code smell{'s' if total != 1 else ''} in this codebase. Focus on fixing the {len(active)} active challenge{'s' if len(active) != 1 else ''} to unlock more."


# Singleton
teaching_plan_engine = TeachingPlanEngine()
