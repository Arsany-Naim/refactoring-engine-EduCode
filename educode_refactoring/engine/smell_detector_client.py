"""Adapter between poulaLabib Code_Smell API and EduCode AnalysisReport schema."""

from __future__ import annotations

import os
from typing import Any

import requests

from engine.smell_definitions import canonicalize_smell_type


_DEFAULT_BASE_URL = os.getenv("CODE_SMELL_API_URL", "http://localhost:5000").rstrip("/")

_SEVERITY_BY_SMELL = {
    "GodClass": "error",
    "ShotgunSurgery": "error",
    "HighCoupling": "error",
    "LongMethod": "warning",
    "FeatureEnvy": "warning",
    "DataClass": "warning",
    "DeepNesting": "warning",
    "ComplexConditional": "warning",
    "LongParameterList": "warning",
    "MessageChain": "warning",
    "RefusedBequest": "warning",
    "DuplicatedCode": "warning",
    "DeadCode": "info",
    "LazyClass": "info",
    "MiddleMan": "info",
}


class SmellDetectorError(RuntimeError):
    """Raised when sidecar smell detector is unreachable or returns bad payload."""


def detector_health(base_url: str | None = None, timeout: int = 5) -> dict[str, Any]:
    url = f"{(base_url or _DEFAULT_BASE_URL)}/health"
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        return {
            "status": payload.get("status", "unknown"),
            "models_loaded": bool(payload.get("models_loaded", False)),
            "version": payload.get("version"),
        }
    except Exception as exc:
        raise SmellDetectorError(f"Detector health check failed: {exc}") from exc


def analyze_code_to_analysis_report(
    code: str,
    filename: str = "",
    base_url: str | None = None,
    timeout: int = 20,
) -> dict[str, Any]:
    building = _post_json(
        endpoint="/analyze/code",
        payload={"code": code, "filename": filename},
        base_url=base_url,
        timeout=timeout,
    )
    cls = _normalize_building(building, source_code=code)
    return {"classes": [cls], "relationships": []}


def analyze_repo_to_analysis_report(
    directory: str,
    max_files: int = 100,
    base_url: str | None = None,
    timeout: int = 180,
) -> dict[str, Any]:
    city = _post_json(
        endpoint="/analyze/repo",
        payload={"directory": directory, "max_files": max_files},
        base_url=base_url,
        timeout=timeout,
    )
    return _normalize_city(city)


def analyze_github_to_analysis_report(
    repo_url: str,
    max_files: int = 100,
    base_url: str | None = None,
    timeout: int = 240,
) -> dict[str, Any]:
    city = _post_json(
        endpoint="/analyze/github",
        payload={"repo_url": repo_url, "max_files": max_files},
        base_url=base_url,
        timeout=timeout,
    )
    return _normalize_city(city)


def _post_json(
    endpoint: str,
    payload: dict[str, Any],
    base_url: str | None,
    timeout: int,
) -> dict[str, Any]:
    url = f"{(base_url or _DEFAULT_BASE_URL)}{endpoint}"

    try:
        response = requests.post(url, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        raise SmellDetectorError(f"Cannot reach smell detector at {url}: {exc}") from exc

    if not response.ok:
        message = response.text
        try:
            data = response.json()
            if isinstance(data, dict):
                message = data.get("error", message)
        except Exception:
            pass
        raise SmellDetectorError(
            f"Detector request failed for {endpoint} with HTTP {response.status_code}: {message}"
        )

    try:
        return response.json()
    except Exception as exc:
        raise SmellDetectorError(
            f"Detector returned invalid JSON for {endpoint}: {exc}"
        ) from exc


def _normalize_city(city: dict[str, Any]) -> dict[str, Any]:
    classes = []
    for building in city.get("buildings", []):
        classes.append(_normalize_building(building))

    relationships = _normalize_relationships(city)
    return {
        "classes": classes,
        "relationships": relationships,
    }


def _normalize_building(
    building: dict[str, Any], source_code: str = ""
) -> dict[str, Any]:
    class_name = building.get("class_name") or "UnknownClass"
    all_smells = building.get("all_smells") or []

    smell_counts: dict[str, int] = {}
    smell_confidences: dict[str, float] = {}

    for smell in all_smells:
        raw_name = smell.get("name")
        canonical = canonicalize_smell_type(raw_name)
        if not canonical or canonical == "Clean":
            continue

        confidence = _as_float(smell.get("confidence"), default=0.0)
        smell_counts[canonical] = smell_counts.get(canonical, 0) + 1
        smell_confidences[canonical] = max(confidence, smell_confidences.get(canonical, 0.0))

    primary_raw = building.get("primary_smell")
    primary_canonical = canonicalize_smell_type(primary_raw)
    if primary_canonical and primary_canonical != "Clean":
        primary_confidence = _as_float(building.get("smell_confidence"), default=0.5)
        smell_counts[primary_canonical] = max(smell_counts.get(primary_canonical, 1), 1)
        smell_confidences[primary_canonical] = max(
            primary_confidence, smell_confidences.get(primary_canonical, 0.0)
        )

    smells = []
    for smell_name, confidence in sorted(
        smell_confidences.items(), key=lambda item: item[1], reverse=True
    ):
        if smell_name == "Clean":
            continue

        count = smell_counts.get(smell_name, 1)
        sources = ["CodeSmellAPI"] + [f"CrossCheck{i + 1}" for i in range(max(0, count - 1))]

        smells.append(
            {
                "type": smell_name,
                "confidence": round(confidence, 3),
                "severity": _SEVERITY_BY_SMELL.get(smell_name, "warning"),
                "line_hint": None,
                "method_name": None,
                "sources": sources,
            }
        )

    metrics = {
        "loc": _as_int(building.get("loc"), default=0),
        "wmc": _as_int(building.get("wmc"), default=0),
        "cbo": _as_int(building.get("cbo"), default=0),
        "dit": _as_int(building.get("dit"), default=0),
        "rfc": _as_int(building.get("rfc"), default=0),
        "lcom": _as_float(building.get("lcom"), default=0.0),
        # TeachingPlanEngine expects NOM and falls back to len(methods) when absent.
        "nom": max(0, _as_int(building.get("rfc"), default=0)),
    }

    recommendations = building.get("recommendations") or []
    feedback = " ".join(str(item).strip() for item in recommendations if str(item).strip())

    return {
        "class_name": class_name,
        "file_path": building.get("file_path", ""),
        "metrics": metrics,
        "smells": smells,
        "methods": [],
        "feedback": feedback,
        "source_code": source_code,
    }


def _normalize_relationships(city: dict[str, Any]) -> list[dict[str, str]]:
    relationships: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    def add_many(items: list[dict[str, Any]], rel_type: str):
        for item in items:
            source = item.get("from") or item.get("source")
            target = item.get("to") or item.get("target")
            if not source or not target:
                continue
            key = (source, target, rel_type)
            if key in seen:
                continue
            seen.add(key)
            relationships.append(
                {
                    "source": source,
                    "target": target,
                    "type": rel_type,
                }
            )

    add_many(city.get("inheritance", []), "inheritance")
    add_many(city.get("dependencies", []), "dependency")
    add_many(city.get("associations", []), "dependency")
    add_many(city.get("compositions", []), "composition")
    add_many(city.get("aggregations", []), "composition")

    return relationships


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
