"""
City Diff Generator — EduCode
================================
After a successful refactoring validation, this module:
  1. Parses the refactored Java code to extract the new class structure
  2. Compares it against the original cityData.json class entries
  3. Returns a CityDiff — the exact changes Unity needs to rebuild
     only the affected buildings, not regenerate the whole city.

The output matches the cityData.json schema Unity already reads:

cityData.json schema:
{
  "classes": [
    {
      "name": str,
      "type": "class" | "interface" | "enum" | "abstract",
      "methods": [str],
      "constructors": [str],
      "methodParameters": [ {"parameters": [str]} ],
      "attributes": [str],
      "linesOfCode": int
    }
  ],
  "relationships": [
    { "from": str, "to": str, "type": "extends"|"implements"|"uses"|"aggregates" }
  ]
}

CityDiff output:
{
  "success": bool,
  "puzzle_id": str,
  "smell_type": str,
  "affected_class": str,
  "change_type": "modified" | "split" | "merged" | "deleted_method" | "renamed_method",
  "city_patch": {
    "updated_classes": [ <full class entry in cityData format> ],
    "added_classes":   [ <full class entry in cityData format> ],
    "removed_classes": [str],                                       ← class names
    "updated_relationships": [ <relationship entry> ],
    "added_relationships":   [ <relationship entry> ],
    "removed_relationships": [ {"from":str,"to":str,"type":str} ]
  },
  "rebuild_targets": [str]   ← class names Unity must rebuild (buildings to re-render)
}
"""

import re
import json
from typing import Optional
from engine.smell_definitions import get_smell_definition


# ── Java parser helpers ──────────────────────────────────────────────────────
# Lightweight regex-based parser — mirrors your existing GitHubJavaAnalyzer
# approach. Does NOT require a full AST; sufficient for city diff purposes.

_CLASS_RE    = re.compile(
    r'(?:public\s+)?(?:abstract\s+)?(class|interface|enum)\s+(\w+)'
    r'(?:\s+extends\s+(\w+))?(?:\s+implements\s+([\w\s,]+))?'
)
_METHOD_RE   = re.compile(
    r'(?:public|private|protected|static|\s)+[\w<>\[\]]+\s+(\w+)\s*\(([^)]*)\)\s*(?:throws\s+\w+\s*)?\{'
)
_CONSTRUCTOR_RE = re.compile(
    r'(?:public|private|protected)\s+(\w+)\s*\(([^)]*)\)\s*(?:throws\s+\w+\s*)?\{'
)
_FIELD_RE    = re.compile(
    r'(?:private|protected|public)(?:\s+static)?(?:\s+final)?\s+[\w<>\[\]]+\s+(\w+)\s*[;=]'
)
_IMPORT_RE   = re.compile(r'import\s+[\w.]+\.(\w+)\s*;')
_LOC_RE      = re.compile(r'\n')


class CityDiffGenerator:

    # ── PUBLIC ────────────────────────────────────────────────────────────────

    def generate_diff(
        self,
        puzzle_id: str,
        smell_type: str,
        original_city_class: dict,          # the single class entry from cityData.json
        refactored_code: str,               # full Java source after student's fix
        original_relationships: list,       # all relationships from cityData.json
    ) -> dict:
        """
        Main entry point.

        Args:
            puzzle_id:             session puzzle_id for tracing
            smell_type:            the smell that was fixed (drives change_type inference)
            original_city_class:   the cityData.json class dict that was changed
            refactored_code:       the student's complete refactored Java source
            original_relationships: all relationship entries from cityData.json

        Returns:
            CityDiff dict (see module docstring)
        """
        original_name = original_city_class.get("name", "")

        # Parse all classes in the refactored code
        parsed_classes = self._parse_java_source(refactored_code)

        if not parsed_classes:
            return self._error(puzzle_id, "Could not parse refactored code — no classes found")

        # Determine what changed
        change_type = self._infer_change_type(
            smell_type, original_city_class, parsed_classes
        )

        # Build the city patch
        city_patch = self._build_patch(
            original_class=original_city_class,
            parsed_classes=parsed_classes,
            original_relationships=original_relationships,
            change_type=change_type
        )

        rebuild_targets = self._compute_rebuild_targets(
            original_name, city_patch, change_type
        )

        return {
            "success": True,
            "puzzle_id": puzzle_id,
            "smell_type": smell_type,
            "affected_class": original_name,
            "change_type": change_type,
            "city_patch": city_patch,
            "rebuild_targets": rebuild_targets
        }

    def apply_patch_to_city_data(
        self,
        city_data: dict,
        city_patch: dict
    ) -> dict:
        """
        Applies a CityDiff patch to a full cityData dict, returning the
        updated cityData. Use this server-side if you need to persist
        the updated city state.

        Unity can also apply the patch itself — this is provided as a
        convenience for server-side city state management.
        """
        classes       = {c["name"]: c for c in city_data.get("classes", [])}
        relationships = list(city_data.get("relationships", []))

        # Remove classes
        for name in city_patch.get("removed_classes", []):
            classes.pop(name, None)

        # Update classes
        for cls in city_patch.get("updated_classes", []):
            classes[cls["name"]] = cls

        # Add new classes
        for cls in city_patch.get("added_classes", []):
            classes[cls["name"]] = cls

        # Remove relationships
        remove_rels = {
            (r["from"], r["to"], r["type"])
            for r in city_patch.get("removed_relationships", [])
        }
        relationships = [
            r for r in relationships
            if (r["from"], r["to"], r["type"]) not in remove_rels
        ]

        # Add/update relationships
        existing_rel_keys = {(r["from"], r["to"], r["type"]) for r in relationships}
        for rel in city_patch.get("added_relationships", []):
            key = (rel["from"], rel["to"], rel["type"])
            if key not in existing_rel_keys:
                relationships.append(rel)

        for rel in city_patch.get("updated_relationships", []):
            for i, r in enumerate(relationships):
                if r["from"] == rel["from"] and r["to"] == rel["to"]:
                    relationships[i] = rel
                    break

        return {
            "classes": list(classes.values()),
            "relationships": relationships
        }

    # ── JAVA PARSER ───────────────────────────────────────────────────────────

    def _parse_java_source(self, source: str) -> list[dict]:
        """
        Parses Java source and returns a list of cityData-format class dicts.
        Handles multiple classes in one source string (e.g. after Extract Class).
        """
        classes = []

        # Split source into per-class blocks by finding top-level class declarations
        blocks = self._split_into_class_blocks(source)

        for block in blocks:
            parsed = self._parse_class_block(block)
            if parsed:
                classes.append(parsed)

        return classes

    def _split_into_class_blocks(self, source: str) -> list[str]:
        """
        Splits multi-class Java source into individual class blocks.
        Simple brace-counting approach.
        """
        blocks = []
        lines  = source.split('\n')
        current_block = []
        brace_depth   = 0
        in_class       = False

        for line in lines:
            stripped = line.strip()

            # Detect class/interface/enum declaration
            if not in_class and _CLASS_RE.search(stripped):
                in_class = True
                current_block = [line]
                brace_depth = stripped.count('{') - stripped.count('}')
                continue

            if in_class:
                current_block.append(line)
                brace_depth += stripped.count('{') - stripped.count('}')

                if brace_depth <= 0:
                    blocks.append('\n'.join(current_block))
                    current_block = []
                    brace_depth   = 0
                    in_class       = False

        # Catch any trailing block
        if current_block:
            blocks.append('\n'.join(current_block))

        return blocks if blocks else [source]

    def _parse_class_block(self, block: str) -> Optional[dict]:
        """Parses a single class block into cityData format."""
        # Class declaration
        class_match = _CLASS_RE.search(block)
        if not class_match:
            return None

        class_type   = class_match.group(1)   # class | interface | enum
        class_name   = class_match.group(2)
        extends_name = class_match.group(3)    # may be None
        implements_raw = class_match.group(4)  # may be None

        # Lines of code (non-blank, non-comment lines)
        loc = len([
            l for l in block.split('\n')
            if l.strip() and not l.strip().startswith('//')
            and not l.strip().startswith('*')
        ])

        # Methods — exclude constructors and common noise
        methods      = []
        method_params = []

        for m in _METHOD_RE.finditer(block):
            name   = m.group(1)
            params = m.group(2).strip()

            # Skip constructors matched by method RE and obvious non-methods
            if name == class_name:
                continue
            if name in ('if', 'while', 'for', 'switch', 'catch', 'try'):
                continue

            param_list = self._parse_param_names(params)
            methods.append(name)
            method_params.append({"parameters": param_list})

        # Constructors
        constructors = []
        for m in _CONSTRUCTOR_RE.finditer(block):
            ctor_name = m.group(1)
            if ctor_name == class_name:
                params = m.group(2).strip()
                constructors.append(f"public {class_name}({params})")

        # Attributes (fields)
        attributes = []
        for m in _FIELD_RE.finditer(block):
            field_name = m.group(1)
            if field_name not in ('if', 'while', 'for', 'true', 'false', 'null'):
                attributes.append(field_name)
        # Deduplicate while preserving order
        seen = set()
        attributes = [a for a in attributes if not (a in seen or seen.add(a))]

        return {
            "name": class_name,
            "type": class_type,
            "methods": methods,
            "constructors": constructors,
            "methodParameters": method_params,
            "attributes": attributes,
            "linesOfCode": loc,
            # Internal — used for relationship inference, stripped before returning
            "_extends": extends_name,
            "_implements": [i.strip() for i in implements_raw.split(',')] if implements_raw else []
        }

    def _parse_param_names(self, params_str: str) -> list[str]:
        """Extracts parameter names from a parameter declaration string."""
        if not params_str.strip():
            return []
        names = []
        for param in params_str.split(','):
            parts = param.strip().split()
            if len(parts) >= 2:
                # Last token is the name, handle array/generic types
                name = parts[-1].strip('[]')
                if name and name.isidentifier():
                    names.append(name)
        return names

    # ── CHANGE TYPE INFERENCE ─────────────────────────────────────────────────

    def _infer_change_type(
        self,
        smell_type: str,
        original: dict,
        parsed: list[dict]
    ) -> str:
        """
        Infers what kind of structural change the refactoring made.
        """
        original_name = original.get("name", "")
        parsed_names  = {c["name"] for c in parsed}

        # Original class still exists?
        original_still_exists = original_name in parsed_names

        # New classes appeared?
        new_classes = [c for c in parsed if c["name"] != original_name]

        if not original_still_exists:
            return "deleted"

        if len(parsed) > 1 and new_classes:
            return "split"       # e.g. Extract Class, God Class fix

        # Same class, different methods
        orig_methods = set(original.get("methods", []))
        new_class    = next((c for c in parsed if c["name"] == original_name), None)
        if new_class:
            new_methods = set(new_class.get("methods", []))
            if orig_methods - new_methods:
                return "deleted_method"
            if len(new_methods) > len(orig_methods):
                return "added_method"

        # Smell-specific heuristics
        type_map = {
            "GodClass":        "split",
            "LongMethod":      "deleted_method",
            "FeatureEnvy":     "deleted_method",
            "DuplicatedCode":  "deleted_method",
            "LazyClass":       "merged",
            "MiddleMan":       "merged",
            "DataClass":       "added_method",
        }
        return type_map.get(smell_type, "modified")

    # ── PATCH BUILDER ─────────────────────────────────────────────────────────

    def _build_patch(
        self,
        original_class: dict,
        parsed_classes: list[dict],
        original_relationships: list,
        change_type: str
    ) -> dict:
        original_name = original_class.get("name", "")

        updated_classes = []
        added_classes   = []
        removed_classes = []
        added_rels      = []
        removed_rels    = []
        updated_rels    = []

        parsed_names = {c["name"] for c in parsed_classes}

        for cls in parsed_classes:
            name = cls["name"]

            # Strip internal fields before returning to Unity
            clean = {k: v for k, v in cls.items() if not k.startswith('_')}

            if name == original_name:
                updated_classes.append(clean)
            else:
                added_classes.append(clean)

        # If original is gone (merged/deleted)
        if original_name not in parsed_names:
            removed_classes.append(original_name)
            # Remove all relationships involving original
            for rel in original_relationships:
                if rel["from"] == original_name or rel["to"] == original_name:
                    removed_rels.append(rel)

        # Infer new relationships from parsed class structure
        for cls in parsed_classes:
            class_name = cls["name"]
            extends    = cls.get("_extends")
            implements = cls.get("_implements", [])

            if extends:
                rel = {"from": class_name, "to": extends, "type": "extends"}
                if not self._rel_exists(rel, original_relationships):
                    added_rels.append(rel)

            for iface in implements:
                if iface:
                    rel = {"from": class_name, "to": iface, "type": "implements"}
                    if not self._rel_exists(rel, original_relationships):
                        added_rels.append(rel)

        # Relationships between newly added classes and the original
        for cls in added_classes:
            new_name = cls["name"]
            # New class likely uses or is used by the original
            rel = {"from": original_name, "to": new_name, "type": "uses"}
            if not self._rel_exists(rel, original_relationships):
                added_rels.append(rel)

        return {
            "updated_classes":       updated_classes,
            "added_classes":         added_classes,
            "removed_classes":       removed_classes,
            "updated_relationships": updated_rels,
            "added_relationships":   added_rels,
            "removed_relationships": removed_rels
        }

    def _rel_exists(self, rel: dict, relationships: list) -> bool:
        return any(
            r["from"] == rel["from"] and
            r["to"]   == rel["to"]   and
            r["type"] == rel["type"]
            for r in relationships
        )

    # ── REBUILD TARGETS ───────────────────────────────────────────────────────

    def _compute_rebuild_targets(
        self,
        original_name: str,
        patch: dict,
        change_type: str
    ) -> list[str]:
        """
        Returns the list of class names whose buildings Unity must rebuild.
        """
        targets = set()
        targets.add(original_name)

        for cls in patch.get("updated_classes", []):
            targets.add(cls["name"])
        for cls in patch.get("added_classes", []):
            targets.add(cls["name"])
        for name in patch.get("removed_classes", []):
            targets.add(name)

        return sorted(targets)

    # ── ERROR ─────────────────────────────────────────────────────────────────

    def _error(self, puzzle_id: str, message: str) -> dict:
        return {
            "success": False,
            "puzzle_id": puzzle_id,
            "error": message
        }


# Singleton
city_diff_generator = CityDiffGenerator()
