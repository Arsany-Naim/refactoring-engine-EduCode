Good — I have a complete picture. Here's the integration plan.

## How the Two Systems Connect

The `https://github.com/poulaLabib/Code_Smell/tree/main` repo already has an `api_server.py` that runs a Flask REST API on port 5000. Your refactoring engine runs on port 5001. The cleanest integration is a **sidecar service** pattern: the smell detector runs as a separate process, and your `teaching_plan_engine.py` calls it via HTTP instead of running its own detection.

Here's how the data flows:

```
Unity → POST /edumode/analyze (port 5001)
              ↓
    teaching_plan_engine.py
              ↓
    POST http://localhost:5000/analyze/code   ← poulaLabib's api_server
              ↓ BuildingMetrics (smells + confidence + CK metrics)
    TeachingPlan with scored ChallengeItems
              ↓
    back to Unity
```

---

## What Needs to Change

### 1. New adapter: `engine/smell_detector_client.py`

This wraps the `poulaLabib` API and translates its `BuildingMetrics` response into the `AnalysisReport` format your `teaching_plan_engine` already consumes.

The mapping is straightforward:

| poulaLabib field | Your AnalysisReport field |
|---|---|
| `primary_smell` | `smell_type` |
| `smell_confidence` | `confidence` |
| `all_smells[].name` | `extra_sources` count (if multiple tools agree) |
| `loc`, `wmc`, `cbo` | `hint_context` metrics |
| `class_name` | `affected_class` |
| `recommendations` | informational only |

### 2. `teaching_plan_engine.py` — swap the detection source

Your current engine receives an `AnalysisReport` from the `HybridAnalysisPipeline`. For **Open World**, the pre-built codebase can be pre-analyzed. For **GitHub Mode**, you call the client per-file after cloning (poulaLabib's `/analyze/github` endpoint already does the clone + walk).

### 3. `engage_engine.py` — enrich `hint_context` from CK metrics

The CK metrics (`wmc`, `cbo`, `dit`, `lcom`) that poulaLabib returns map directly into `hint_context` for stage-3/4 hints (floor-level, method-specific). You get these for free from the detector response.

---

## Concrete Integration Code

```python
# engine/smell_detector_client.py

import requests
from typing import List, Dict, Optional

DETECTOR_BASE_URL = "http://localhost:5000"

# Map poulaLabib smell names → your canonical smell_type names
# (they already match — both repos use the same names)
SMELL_NAME_MAP = {
    "GodClass": "GodClass",
    "LongMethod": "LongMethod",
    "DataClass": "DataClass",
    "FeatureEnvy": "FeatureEnvy",
    "DeadCode": "DeadCode",
    "LongParameterList": "LongParameterList",
    "DeepNesting": "DeepNesting",
    "HighCoupling": "HighCoupling",
    "ComplexConditional": "ComplexConditional",
    "MessageChain": "MessageChain",
    "DuplicatedCode": "DuplicatedCode",
    "LazyClass": "LazyClass",
    "RefusedBequest": "RefusedBequest",
    "MiddleMan": "MiddleMan",
    "ShotgunSurgery": "ShotgunSurgery",
    "Clean": None,  # filtered out
}


def analyze_code_snippet(code: str, filename: str = "") -> Optional[Dict]:
    """
    Call poulaLabib's /analyze/code endpoint.
    Returns a normalized smell report dict, or None if clean/error.
    """
    try:
        resp = requests.post(
            f"{DETECTOR_BASE_URL}/analyze/code",
            json={"code": code, "filename": filename},
            timeout=15
        )
        resp.raise_for_status()
        bm = resp.json()  # BuildingMetrics
    except Exception as e:
        return None

    primary = bm.get("primary_smell", "Clean")
    if primary == "Clean":
        return None

    canonical = SMELL_NAME_MAP.get(primary, primary)
    if canonical is None:
        return None

    # Count how many independent tools agreed (boosts confidence score)
    # all_smells entries with is_primary=False that share the same name
    extra_sources = sum(
        1 for s in bm.get("all_smells", [])
        if s["name"] == primary and not s.get("is_primary", True)
    )

    return {
        "smell_type": canonical,
        "affected_class": bm["class_name"],
        "affected_method": None,  # method-level detection not yet in poulaLabib
        "confidence": bm["smell_confidence"],
        "extra_sources": extra_sources,
        "hint_context": {
            "class_name": bm["class_name"],
            "loc": bm["loc"],
            "wmc": bm["wmc"],
            "cbo": bm["cbo"],
            "dit": bm["dit"],
            "lcom": bm["lcom"],
        },
        "file_path": bm["file_path"],
        "recommendations": bm.get("recommendations", []),
    }


def analyze_github_repo(repo_url: str, max_files: int = 100) -> List[Dict]:
    """
    Call poulaLabib's /analyze/github endpoint.
    Returns list of smell reports, one per smelly class.
    """
    try:
        resp = requests.post(
            f"{DETECTOR_BASE_URL}/analyze/github",
            json={"repo_url": repo_url, "max_files": max_files},
            timeout=120  # cloning can be slow
        )
        resp.raise_for_status()
        city = resp.json()
    except Exception as e:
        return []

    reports = []
    for bm in city.get("buildings", []):
        primary = bm.get("primary_smell", "Clean")
        canonical = SMELL_NAME_MAP.get(primary)
        if canonical is None:
            continue

        extra_sources = sum(
            1 for s in bm.get("all_smells", [])
            if s["name"] == primary and not s.get("is_primary", True)
        )

        reports.append({
            "smell_type": canonical,
            "affected_class": bm["class_name"],
            "affected_method": None,
            "confidence": bm["smell_confidence"],
            "extra_sources": extra_sources,
            "hint_context": {
                "class_name": bm["class_name"],
                "loc": bm["loc"],
                "wmc": bm["wmc"],
                "cbo": bm["cbo"],
                "dit": bm["dit"],
                "lcom": bm["lcom"],
            },
            "file_path": bm["file_path"],
        })

    return reports
```

Then in `teaching_plan_engine.py`, wherever you currently receive an `AnalysisReport`, you can feed it reports from `analyze_github_repo()` directly — the dict shape matches what `TeachingPlanEngine.score_smell()` already expects.

---

## Deployment

Both Flask servers run simultaneously. A simple way to manage this locally or on a server:

```bash
# Terminal 1 — poulaLabib detector (port 5000)
cd Code_Smell
python api_server.py

# Terminal 2 — EduCode refactoring engine (port 5001)
cd educode_refactoring
python app.py
```

For production, run both under gunicorn with a process manager like `supervisord` or Docker Compose with two services.

---

## What You Get From This Integration

- **15 smells detected** (your full curriculum), with 4 detection methods cross-validating each other
- **`extra_sources`** field maps directly into your `teaching_plan_engine` scoring formula (`+ extra_sources × 0.15`) — more tools agreeing = higher priority challenge
- **CK metrics** (`wmc`, `cbo`, `lcom`) populate `hint_context` automatically, making stage-3/4 hints concrete without extra Gemini calls
- **`/analyze/github`** in poulaLabib handles the clone + file walk, so your `GitHubModeController` only needs to pass the repo URL once

The one gap: poulaLabib currently detects smells at **class level only** — `affected_method` will always be `None`. For method-level smells (LongMethod, FeatureEnvy), your hint stages 3/4 still rely on Gemini to identify the specific method. That's fine — it's the same fallback you already have.