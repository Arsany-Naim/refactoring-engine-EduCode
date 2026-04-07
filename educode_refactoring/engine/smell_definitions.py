"""Canonical smell metadata for EduCode engines."""

from copy import deepcopy


_SMELL_DEFINITIONS = {
    "LongMethod": {
        "display_name": "Long Method",
        "principle": "Extract Method and Single Responsibility",
        "highlight_type": "warning",
    },
    "LongParameterList": {
        "display_name": "Long Parameter List",
        "principle": "Introduce Parameter Object",
        "highlight_type": "warning",
    },
    "DeadCode": {
        "display_name": "Dead Code",
        "principle": "Keep Codebase Lean",
        "highlight_type": "info",
    },
    "DeepNesting": {
        "display_name": "Deep Nesting",
        "principle": "Replace Nested Conditionals",
        "highlight_type": "warning",
    },
    "DuplicatedCode": {
        "display_name": "Duplicated Code",
        "principle": "Don't Repeat Yourself (DRY)",
        "highlight_type": "warning",
    },
    "DataClass": {
        "display_name": "Data Class",
        "principle": "Tell, Don't Ask",
        "highlight_type": "warning",
    },
    "FeatureEnvy": {
        "display_name": "Feature Envy",
        "principle": "Move Behavior to Owning Data",
        "highlight_type": "warning",
    },
    "LazyClass": {
        "display_name": "Lazy Class",
        "principle": "High Cohesion",
        "highlight_type": "info",
    },
    "ComplexConditional": {
        "display_name": "Complex Conditional",
        "principle": "Replace Conditionals with Polymorphism",
        "highlight_type": "warning",
    },
    "MessageChain": {
        "display_name": "Message Chain",
        "principle": "Law of Demeter",
        "highlight_type": "warning",
    },
    "GodClass": {
        "display_name": "God Class",
        "principle": "Single Responsibility Principle (SRP)",
        "highlight_type": "error",
    },
    "HighCoupling": {
        "display_name": "High Coupling",
        "principle": "Dependency Inversion Principle",
        "highlight_type": "error",
    },
    "MiddleMan": {
        "display_name": "Middle Man",
        "principle": "Reduce Unnecessary Delegation",
        "highlight_type": "info",
    },
    "RefusedBequest": {
        "display_name": "Refused Bequest",
        "principle": "Favor Composition Over Inheritance",
        "highlight_type": "warning",
    },
    "ShotgunSurgery": {
        "display_name": "Shotgun Surgery",
        "principle": "Encapsulate Change",
        "highlight_type": "error",
    },
}


# External detectors may use slightly different labels.
_SMELL_ALIASES = {
    "DuplicateCode": "DuplicatedCode",
    "God Method": "LongMethod",
    "GodMethod": "LongMethod",
    "Clean": "Clean",
}


def canonicalize_smell_type(smell_type: str | None) -> str | None:
    """Return canonical smell name used by EduCode pipelines."""
    if not smell_type:
        return None
    return _SMELL_ALIASES.get(smell_type, smell_type)


def get_smell_definition(smell_type: str | None) -> dict | None:
    """Lookup metadata for a smell type."""
    canonical = canonicalize_smell_type(smell_type)
    if not canonical or canonical == "Clean":
        return None
    data = _SMELL_DEFINITIONS.get(canonical)
    if not data:
        return None
    result = deepcopy(data)
    result["smell_type"] = canonical
    return result


def get_highlight_type(smell_type: str | None) -> str:
    """Get highlight category used by Unity visuals."""
    definition = get_smell_definition(smell_type)
    if not definition:
        return "warning"
    return definition.get("highlight_type", "warning")


def get_all_smell_types() -> list[str]:
    """Return canonical smell names used in curriculum and planning."""
    return list(_SMELL_DEFINITIONS.keys())


def get_all_smell_definitions() -> dict[str, dict]:
    """Return a copy of all canonical smell metadata."""
    return deepcopy(_SMELL_DEFINITIONS)
