using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Networking;
using Newtonsoft.Json;

namespace EduCode.RefactoringGame
{
    // ═══════════════════════════════════════════════════════════════════════════
    // DATA MODELS
    // ═══════════════════════════════════════════════════════════════════════════

    [Serializable]
    public class PuzzleFile
    {
        public string filename;
        public string content;
    }

    [Serializable]
    public class GeneratePuzzleResponse
    {
        public bool   success;
        public string puzzle_id;
        public string smell_type;
        public string display_name;
        public string principle;
        public int    difficulty;
        public string difficulty_label;
        public string theme;
        public List<PuzzleFile> files;
        public string error;
    }

    [Serializable]
    public class HintHighlight
    {
        public string class_name;
        public string method_name;       // null = building-level
        public string highlight_level;   // "building" | "floor"
        public string highlight_type;    // "error" | "warning" | "info"
    }

    [Serializable]
    public class HintResponse
    {
        public bool         success;
        public int          hint_stage;
        public int          max_stages;
        public bool         is_final_hint;
        public string       smell_type;
        public string       hint_text;
        public string       encouragement;
        public string       tone;
        public HintHighlight highlight;
        public string       error;
        public string       message;
    }

    [Serializable]
    public class CurriculumProgress
    {
        public int completed;
        public int total;
    }

    [Serializable]
    public class ProgressionState
    {
        public string student_id;
        public int    total_puzzles_completed;
        public int    total_stars;
        public float  average_score;
        public int    unlocked_difficulty;
        public List<string> completed_smells;
        public List<string> pending_smells;
        public string next_recommended;
    }

    [Serializable]
    public class ValidationResponse
    {
        public bool   success;
        public int    attempt_number;
        public int    score;
        public bool   smell_resolved;
        public bool   correct_technique;
        public bool   still_valid_java;
        public List<string> new_smells_introduced;
        public string feedback;
        public bool   partial_credit;
        public string partial_reason;
        public int    stars;
        public ProgressionState progression;
        public CityDiff city_diff;        // ← non-null when smell_resolved = true
        public string error;
    }

    [Serializable]
    public class RecommendationResponse
    {
        public bool   success;
        public string smell_type;
        public int    difficulty;
        public string reason;
        public string display_name;
        public string principle;
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // EDUMODE MANAGER
    // ═══════════════════════════════════════════════════════════════════════════

    /// <summary>
    /// Central manager for the EduCode refactoring game mode.
    /// Sessions are now stored server-side — only puzzle_id is kept locally.
    ///
    /// Attach to a persistent GameObject in the EduMode scene.
    /// </summary>
    public class EduModeManager : MonoBehaviour
    {
        // ── Singleton ────────────────────────────────────────────────────────
        public static EduModeManager Instance { get; private set; }

        // ── Inspector ────────────────────────────────────────────────────────
        [Header("Backend")]
        [SerializeField] private string backendBaseUrl = "http://localhost:5001";

        [Header("Student Identity")]
        [Tooltip("Set at login time. Used for adaptive progression.")]
        [SerializeField] private string studentId = "";

        // ── State ─────────────────────────────────────────────────────────────
        private string _activePuzzleId;
        private List<PuzzleFile> _currentFiles;
        private string _originalCode;
        private int _currentHintStage;
        private List<int> _hintsSeenThisPuzzle = new();

        // ── Events ────────────────────────────────────────────────────────────
        public event Action<GeneratePuzzleResponse> OnPuzzleGenerated;
        public event Action<HintResponse>           OnHintReceived;
        public event Action<ValidationResponse>     OnValidationComplete;
        public event Action<string>                 OnError;

        // ── Properties ───────────────────────────────────────────────────────
        public bool   HasActivePuzzle   => !string.IsNullOrEmpty(_activePuzzleId);
        public string ActivePuzzleId    => _activePuzzleId;
        public int    CurrentHintStage  => _currentHintStage;
        public bool   AllHintsExhausted => _currentHintStage >= 4;
        public string StudentId
        {
            get => studentId;
            set => studentId = value;
        }

        // ─────────────────────────────────────────────────────────────────────

        private void Awake()
        {
            if (Instance != null && Instance != this) { Destroy(gameObject); return; }
            Instance = this;
            DontDestroyOnLoad(gameObject);
        }

        // ═══════════════════════════════════════════════════════════════════════
        // PUBLIC API
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>Generates a new refactoring puzzle.</summary>
        public void GeneratePuzzle(
            int    difficulty = 1,
            string smellType  = null,
            string theme      = null,
            Action<GeneratePuzzleResponse> onComplete = null)
        {
            var body = new Dictionary<string, object>
            {
                ["difficulty"]  = difficulty,
                ["smell_type"]  = string.IsNullOrEmpty(smellType) ? null : smellType,
                ["theme"]       = theme,
                ["student_id"]  = string.IsNullOrEmpty(studentId) ? null : studentId
            };

            StartCoroutine(Post<GeneratePuzzleResponse>("/edumode/generate", body, response =>
            {
                if (response.success)
                {
                    _activePuzzleId       = response.puzzle_id;
                    _currentFiles         = response.files;
                    _originalCode         = JoinFiles(response.files);
                    _currentHintStage     = 0;
                    _hintsSeenThisPuzzle  = new List<int>();
                    Debug.Log($"[EduMode] Puzzle: {response.puzzle_id} | {response.display_name} | D{response.difficulty}");
                }
                else
                {
                    Debug.LogError($"[EduMode] Generate failed: {response.error}");
                    OnError?.Invoke(response.error);
                }
                onComplete?.Invoke(response);
                OnPuzzleGenerated?.Invoke(response);
            }));
        }

        /// <summary>
        /// Generates a puzzle using adaptive recommendation for the current student.
        /// Shorthand for GeneratePuzzle() with no explicit smell — backend picks from curriculum.
        /// </summary>
        public void GenerateRecommendedPuzzle(Action<GeneratePuzzleResponse> onComplete = null)
        {
            GeneratePuzzle(onComplete: onComplete);
        }

        /// <summary>
        /// Sets the currently active puzzle from an externally engaged challenge
        /// (Open World / GitHub mode).
        /// </summary>
        public void SetActivePuzzle(string puzzleId, string sourceCode = "")
        {
            if (string.IsNullOrEmpty(puzzleId))
            {
                OnError?.Invoke("Cannot set active puzzle: puzzle_id is empty.");
                return;
            }

            _activePuzzleId = puzzleId;
            _originalCode = sourceCode ?? "";
            _currentFiles = new List<PuzzleFile>();
            _currentHintStage = 0;
            _hintsSeenThisPuzzle = new List<int>();
        }

        /// <summary>Requests the next progressive hint.</summary>
        public void RequestHint(Action<HintResponse> onComplete = null)
        {
            if (!HasActivePuzzle)
            {
                OnError?.Invoke("No active puzzle. Call GeneratePuzzle first.");
                return;
            }

            if (AllHintsExhausted)
            {
                onComplete?.Invoke(new HintResponse
                {
                    success = false,
                    message = "All 4 hints used. Try applying what you've learned!",
                    hint_stage = 4
                });
                return;
            }

            var body = new Dictionary<string, object> { ["puzzle_id"] = _activePuzzleId };

            StartCoroutine(Post<HintResponse>("/edumode/hint", body, response =>
            {
                if (response.success)
                {
                    _currentHintStage = response.hint_stage;
                    _hintsSeenThisPuzzle.Add(response.hint_stage);
                    Debug.Log($"[EduMode] Hint {response.hint_stage}/{response.max_stages}");
                }
                onComplete?.Invoke(response);
                OnHintReceived?.Invoke(response);
            }));
        }

        /// <summary>Replays a previously unlocked hint without advancing stage.</summary>
        public void ReplayHint(int stage, Action<HintResponse> onComplete = null)
        {
            if (!HasActivePuzzle) { OnError?.Invoke("No active puzzle."); return; }

            var body = new Dictionary<string, object>
            {
                ["puzzle_id"] = _activePuzzleId,
                ["stage"]     = stage
            };

            StartCoroutine(Post<HintResponse>("/edumode/hint/replay", body, response =>
            {
                onComplete?.Invoke(response);
                OnHintReceived?.Invoke(response);
            }));
        }

        /// <summary>
        /// Submits the student's refactored code for evaluation.
        /// Pass the original cityData class entry and relationships so the
        /// backend can generate a city_diff to rebuild affected buildings.
        /// </summary>
        public void ValidateRefactoring(
            string refactoredCode,
            CityClassEntry originalCityClass = null,
            List<CityRelationship> originalRelationships = null,
            Action<ValidationResponse> onComplete = null)
        {
            if (!HasActivePuzzle) { OnError?.Invoke("No active puzzle."); return; }

            var body = new Dictionary<string, object>
            {
                ["puzzle_id"]             = _activePuzzleId,
                ["original_code"]         = _originalCode,
                ["refactored_code"]       = refactoredCode,
                ["original_city_class"]   = originalCityClass,
                ["original_relationships"] = originalRelationships ?? new List<CityRelationship>()
            };

            StartCoroutine(Post<ValidationResponse>("/edumode/validate", body, response =>
            {
                if (response.success)
                    Debug.Log($"[EduMode] Score: {response.score} | Stars: {response.stars} | " +
                              $"Resolved: {response.smell_resolved} | " +
                              $"CityDiff: {(response.city_diff != null ? response.city_diff.change_type : "none")}");
                else
                    OnError?.Invoke(response.error);

                onComplete?.Invoke(response);
                OnValidationComplete?.Invoke(response);
            }));
        }

        // ═══════════════════════════════════════════════════════════════════════
        // HTTP HELPER
        // ═══════════════════════════════════════════════════════════════════════

        private IEnumerator Post<T>(
            string endpoint,
            object body,
            Action<T> onComplete) where T : new()
        {
            string url  = backendBaseUrl.TrimEnd('/') + endpoint;
            string json = JsonConvert.SerializeObject(body);
            byte[] raw  = System.Text.Encoding.UTF8.GetBytes(json);

            using var req = new UnityWebRequest(url, "POST");
            req.uploadHandler   = new UploadHandlerRaw(raw);
            req.downloadHandler = new DownloadHandlerBuffer();
            req.SetRequestHeader("Content-Type", "application/json");
            req.timeout = 30;

            yield return req.SendWebRequest();

            var result = new T();
            if (req.result == UnityWebRequest.Result.Success)
                result = JsonConvert.DeserializeObject<T>(req.downloadHandler.text);
            else
                Debug.LogError($"[EduMode] HTTP {req.responseCode}: {req.error}");

            onComplete?.Invoke(result);
        }

        // ─────────────────────────────────────────────────────────────────────

        private string JoinFiles(List<PuzzleFile> files)
        {
            if (files == null || files.Count == 0) return "";
            return string.Join("\n\n", files.ConvertAll(f => f.content));
        }
    }
}
