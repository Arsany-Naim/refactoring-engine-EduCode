# EduCode Refactoring Game Backend

Complete Flask backend for the EduCode refactoring learning game. Three modes: Escape Room (curriculum-driven), Open World (student's own codebase), and GitHub (GitHub repositories).

## Project Structure

```
educode_refactoring/
├── app.py                           # Flask application factory
├── requirements.txt                 # Python dependencies
├── .env.example                     # Environment template
├── engine/
│   ├── city_diff_generator.py       # Java code parser → CityDiff patches
│   ├── engage_engine.py             # Hint session initialization (GitHub mode)
│   ├── refactor_engine.py           # Auto-refactor via Gemini (Open World mode)
│   ├── progression_tracker.py       # Student progress & curriculum tracking
│   └── teaching_plan_engine.py      # AnalysisReport → TeachingPlan conversion
├── prompts/
│   └── templates.py                 # All Gemini prompt templates
└── routes/
    ├── edumode_routes.py            # Escape Room endpoints
    └── world_routes.py              # Open World & GitHub endpoints
```

## Setup

### 1. Environment

```bash
cd educode_refactoring
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows
pip install -r requirements.txt
```

### 2. Configuration

Copy `.env.example` to `.env` and fill in your Gemini API key:

```bash
cp .env.example .env
# Edit .env: GEMINI_API_KEY=your_key_here
```

Obtain a free Gemini API key from [makersuite.google.com/app/apikeys](https://makersuite.google.com/app/apikeys).

### 3. Run

```bash
python app.py
```

Server starts on `http://localhost:5001/`

## API Endpoints

### Escape Room Mode (`/edumode`)

#### `POST /edumode/generate`

Generate a new refactoring puzzle.

**Request:**
```json
{
  "difficulty": 1,           // 1 = Beginner, 2 = Intermediate, 3 = Advanced
  "smell_type": "GodClass",  // optional: specific smell to practice
  "theme": "ecommerce",      // optional: code domain theme
  "student_id": "alice123"   // optional: for progression tracking
}
```

**Response:**
```json
{
  "success": true,
  "puzzle_id": "puzzle_abc123",
  "smell_type": "GodClass",
  "display_name": "User Manager",
  "principle": "Single Responsibility Principle",
  "difficulty": 1,
  "difficulty_label": "Beginner",
  "theme": "ecommerce",
  "files": [
    {
      "filename": "UserManager.java",
      "content": "public class UserManager { ... }"
    }
  ]
}
```

#### `POST /edumode/hint`

Get the next progressive hint (stages 0→1→2→3→4).

**Request:**
```json
{
  "puzzle_id": "puzzle_abc123"
}
```

**Response:**
```json
{
  "success": true,
  "hint_stage": 2,
  "max_stages": 4,
  "is_final_hint": false,
  "smell_type": "GodClass",
  "hint_text": "Try breaking this into separate classes by responsibility...",
  "encouragement": "You're on the right track!",
  "tone": "supportive",
  "highlight": {
    "class_name": "UserManager",
    "method_name": "updateUserPassword",
    "highlight_level": "floor",
    "highlight_type": "warning"
  }
}
```

#### `POST /edumode/hint/replay`

Replay a previously unlocked hint stage without advancing.

**Request:**
```json
{
  "puzzle_id": "puzzle_abc123",
  "stage": 1
}
```

#### `POST /edumode/validate`

Submit refactored code for evaluation.

**Request:**
```json
{
  "puzzle_id": "puzzle_abc123",
  "original_code": "public class UserManager { ... }",
  "refactored_code": "public class User { ... } public class UserValidator { ... }",
  "original_city_class": {
    "name": "UserManager",
    "type": "class",
    "methods": ["updateUser", "validateEmail"],
    "attributes": ["users", "emailValidator"],
    "linesOfCode": 487
  },
  "original_relationships": []
}
```

**Response:**
```json
{
  "success": true,
  "attempt_number": 1,
  "score": 87,
  "smell_resolved": true,
  "correct_technique": true,
  "still_valid_java": true,
  "new_smells_introduced": [],
  "feedback": "Excellent separation of concerns! You successfully extracted the validation logic...",
  "partial_credit": false,
  "stars": 3,
  "progression": {
    "student_id": "alice123",
    "total_puzzles_completed": 5,
    "total_stars": 12,
    "average_score": 82.4,
    "unlocked_difficulty": 2,
    "completed_smells": ["GodClass", "LongMethod"],
    "pending_smells": ["ShotgunSurgery", "FeatureEnvy"],
    "next_recommended": "LongMethod"
  },
  "city_diff": null  // null = smell not resolved; non-null = patch to apply
}
```

#### `GET /edumode/progress/<student_id>`

Get progression state for a student.

**Response:**
```json
{
  "success": true,
  "student_id": "alice123",
  "total_puzzles_completed": 5,
  "average_score": 82.4,
  "unlocked_difficulty": 2,
  "completed_smells": ["GodClass", "LongMethod"],
  "pending_smells": ["ShotgunSurgery", "FeatureEnvy"]
}
```

#### `GET /edumode/recommend/<student_id>`

Get AI recommendation for the next puzzle.

**Response:**
```json
{
  "success": true,
  "smell_type": "LongMethod",
  "difficulty": 2,
  "reason": "You've mastered Beginner God Class. Ready for Intermediate?",
  "display_name": "Invoice Processor",
  "principle": "Extract Method"
}
```

#### `GET /edumode/smells`

List all available code smells and their curriculum tier.

#### `GET /edumode/health`

Service health check.

---

### Open World & GitHub Modes (`/world`)

#### `POST /world/analyze`

Convert an AnalysisReport into a TeachingPlan with prioritized challenges.

**Request:**
```json
{
  "analysis_report": {
    "classes": [...],
    "detected_smells": [...]
  },
  "student_id": "alice123"
}
```

**Response:**
```json
{
  "success": true,
  "plan_id": "plan_xyz789",
  "student_id": "alice123",
  "mode": "world",
  "active_challenge_count": 5,
  "queued_challenge_count": 8,
  "total_challenge_count": 13,
  "summary": "5 code smells detected. Fix them to earn stars.",
  "active_challenges": [
    {
      "id": "c1",
      "class_name": "UserService",
      "display_name": "User Manager",
      "smell_type": "GodClass",
      "principle": "Single Responsibility Principle",
      "severity": 3,
      "confidence": 0.94,
      "educator_note": "This class handles authentication, validation, and persistence.",
      "hint_context": "Consider extracting validators and persistence logic.",
      "status": "active"
    }
  ],
  "queued_challenges": [...]
}
```

#### `POST /world/engage`

Start a challenge inside the plan (get puzzle_id for hints/validation).

**Request:**
```json
{
  "plan_id": "plan_xyz789",
  "challenge_id": "c1"
}
```

**Response:**
```json
{
  "success": true,
  "puzzle_id": "puzzle_world_123",
  "class_name": "UserService",
  "display_name": "User Manager",
  "smell_type": "GodClass",
  "principle": "Single Responsibility Principle",
  "educator_note": "..."
}
```

#### `POST /world/advance`

Mark a challenge complete and unlock the next queued one.

**Request:**
```json
{
  "plan_id": "plan_xyz789",
  "challenge_id": "c1"
}
```

**Response:**
```json
{
  "success": true,
  "all_complete": false,
  "remaining_active": 4,
  "remaining_queued": 8,
  "unlocked_challenge": {
    "id": "c2",
    "class_name": "PaymentProcessor",
    "display_name": "Payment Handler",
    "smell_type": "FeatureEnvy",
    ...
  }
}
```

#### `POST /world/solve`

**Open World Mode Only** — Auto-refactor and immediately return the fixed code + city_diff.

This endpoint replaces the engage → hint → validate → advance flow for Open World. GitHub Mode continues using /world/engage + /edumode/validate.

**Request:**
```json
{
  "plan_id": "plan_xyz789",
  "challenge_id": "c1",
  "source_code": "public class UserService { ... }",
  "original_city_class": {
    "name": "UserService",
    "type": "class",
    "methods": ["authenticate", "validate", "persist"],
    "attributes": ["db", "cache"],
    "linesOfCode": 456
  },
  "original_relationships": []
}
```

**Response:**
```json
{
  "success": true,
  "smell_type": "GodClass",
  "display_name": "God Class",
  "class_name": "UserService",
  "refactored_code": "public class UserService { ... } public class UserValidator { ... } public class UserPersistence { ... }",
  "summary": "Split into UserService (auth), UserValidator (validation), and UserPersistence (storage).",
  "city_diff": {
    "success": true,
    "affected_class": "UserService",
    "change_type": "split",
    "city_patch": {
      "updated_classes": [...],
      "added_classes": [...],
      "removed_classes": [],
      "added_relationships": [...],
      "removed_relationships": [],
      "updated_relationships": []
    },
    "rebuild_targets": ["UserService", "UserValidator", "UserPersistence"]
  },
  "unlocked_challenge": { ... } | null,
  "remaining_active": 4,
  "remaining_queued": 8,
  "all_complete": false
}
```

#### `GET /world/plan/<plan_id>`

Retrieve a cached plan (for session recovery).

---

## Server Flow

### Escape Room Mode

1. **Generate**: `/edumode/generate` → `city_diff_generator` parses generated code
2. **Hint Loop**: Player requests hints via `/edumode/hint` (4-stage progression)
3. **Validate**: `/edumode/validate` → generates `city_diff` if smell resolved
4. **Progress**: `/edumode/progress/<student_id>` tracks completion

### Open World Mode (Auto-Solve)

1. **Analyze**: User's code → AnalysisReport → `/world/analyze`
2. **Plan**: Creates teaching plan with prioritized challenges
3. **Solve**: Player clicks building → `/world/solve` (one-shot)
   - Gemini auto-refactors the class
   - Returns `city_diff` for 3D rebuild
   - Plan auto-advances, unlocks next challenge
4. **Display**: Solution Viewer panel shows refactored code + summary
5. **Repeat**: Next challenge available to solve

### GitHub Mode (Interactive Flow)

1. **Analyze**: User's GitHub repo → AnalysisReport → `/world/analyze`
2. **Plan**: Creates teaching plan with prioritized challenges
3. **Engage**: Player clicks building → `/world/engage` → puzzle injects into EduModeManager
4. **Hint Loop**: Player requests hints via `/edumode/hint` (4-stage progression)
5. **Validate**: Player submits refactoring → `/edumode/validate` → Gemini grades it
6. **Repair**: If correct, `/world/advance` unlocks next challenge, building repairs animate

---

## Code Smells

All 15 code smells are tracked in a curriculum with 3 difficulty tiers:

| Tier | Smells |
|------|--------|
| Beginner | LongMethod, LongParameterList, DeadCode, DeepNesting, DuplicatedCode |
| Intermediate | DataClass, FeatureEnvy, LazyClass, ComplexConditional, MessageChain |
| Advanced | GodClass, HighCoupling, MiddleMan, RefusedBequest, ShotgunSurgery |

Curriculum progression is unlocked based on average scores:
- Difficulty 1 → Difficulty 2: 60% average on Difficulty 1 puzzles
- Difficulty 2 → Difficulty 3: 75% average on Difficulty 2 puzzles

**Note:** Open World and GitHub modes do not use difficulty levels—they analyze real code and assign smells based on actual violations found.

---

## Architecture Decisions

- **Session Storage**: In-memory dict with 2-hour TTL (expandable to Redis)
- **Code Analysis**: Lightweight regex-based Java parser (extensible to AST)
- **AI Integration**: Google Gemini API (fallbacks to template hints if API unavailable)
- **City Diff**: Automatic city rebuild patch generation (parsed from refactored code diff)

---

## Troubleshooting

### `ModuleNotFoundError: No module named 'googleai'`

```bash
pip install google-generativeai
```

### `GEMINI_API_KEY not set`

Create a `.env` file:
```bash
GEMINI_API_KEY=your_key_from_makersuite.google.com
```

### CORS errors from Unity

Ensure Flask is running with CORS enabled (default in `app.py`).

### Puzzle validation keeps failing

Check:
1. `original_code` matches the exact file sent to Unity
2. `refactored_code` is valid Java
3. Backend Gemini API has quota remaining

---

## Future Enhancements

- Redis session persistence
- Database (PostgreSQL) for student data
- GitHub real-time code analysis (push-triggered)
- Multi-language support (C#, Python, JavaScript)
- Collaborative mode (pair programming)
- Leaderboards & achievements
