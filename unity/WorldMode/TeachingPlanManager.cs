using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Networking;
using Newtonsoft.Json;
using TMPro;
using EduCode.RefactoringGame;

namespace EduCode.WorldMode
{
    // ═══════════════════════════════════════════════════════════════════════════
    // DATA MODELS (shared with backend)
    // ═══════════════════════════════════════════════════════════════════════════

    [Serializable]
    public class TeachingPlan
    {
        public bool   success;
        public string plan_id;
        public string student_id;
        public string mode;                    // "open_world" or "github"
        public int    total_classes_analyzed;
        public int    total_smells_found;
        public int    active_challenge_count;
        public int    queued_challenge_count;
        public int    total_challenge_count;
        public string summary;                 // "5 code smells detected. Fix them to earn stars."
        public List<string> clean_classes;
        public List<ChallengeItem> active_challenges;
        public List<ChallengeItem> queued_challenges;
        public string error;
    }

    [Serializable]
    public class ChallengeItem
    {
        public string challenge_id;
        public string id;
        public string class_name;
        public string file_path;
        public string display_name;            // "God Class"
        public string smell_type;             // "GodClass"
        public string principle;              // "Single Responsibility Principle"
        public int    severity;               // 1 (low) to 3 (critical)
        public string severity_label;
        public float  confidence;             // 0.0 to 1.0
        public int    priority;
        public string highlight_type;
        public string method_name;
        public int    line_hint;
        public string educator_note;
        public string hint_context;           // pre-computed hints
        public string status;                 // "active" or "queued"
    }

    [Serializable]
    public class EngageResponse
    {
        public bool   success;
        public string puzzle_id;              // injected into EduModeManager
        public string class_name;
        public string display_name;
        public string smell_type;
        public string principle;
        public string method_name;
        public string file_path;
        public string mode;
        public string severity;
        public string highlight_type;
        public string educator_note;
        public string source_code;
        public string error;
    }

    [Serializable]
    public class AdvanceResponse
    {
        public bool           success;
        public bool           all_complete;
        public int            remaining_active;
        public int            remaining_queued;
        public ChallengeItem  unlocked_challenge;  // newly unlocked, or null
        public string error;
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // TEACHING PLAN MANAGER
    // ═══════════════════════════════════════════════════════════════════════════

    /// <summary>
    /// Orchestrates the Open World / GitHub mode teaching plan.
    ///
    /// Responsibilities:
    ///   1. LoadTeachingPlan() — sends AnalysisReport → /analyze, gets TeachingPlan
    ///   2. ApplyDamageToBuilding() — shows damage visuals for each challenge
    ///   3. EngageChallenge() — player clicks building, gets puzzle_id
    ///   4. RepairBuilding() — building heals after successful validation
    ///   5. AdvanceToNext() — unlocks next challenge in queue
    ///
    /// Events:
    ///   OnPlanReady         — plan loaded + damage applied to city
    ///   OnChallengeEngaged  — player clicked building, puzzle_id ready
    ///   OnChallengeAdvanced — next challenge unlocked
    ///   OnError             — any backend/network error
    ///
    /// Wiring (Inspector):
    ///   backendBaseUrl → http://localhost:5001 (or your server URL)
    ///   cityRenderer   → CityRenderer for building lookup
    ///   studentId      → set by login flow or OpenWorldController
    /// </summary>
    public class TeachingPlanManager : MonoBehaviour
    {
        // ── Inspector ────────────────────────────────────────────────────────
        [Header("Backend")]
        [SerializeField] private string backendBaseUrl = "http://localhost:5001";

        [Header("Student")]
        [SerializeField] private string studentId = "";

        [Header("Dependencies")]
        [SerializeField] private CityRenderer cityRenderer;

        // ── State ────────────────────────────────────────────────────────────
        private string _currentPlanId;
        private TeachingPlan _currentPlan;
        private Dictionary<string, ChallengeItem> _challengeById = new();
        private HashSet<string> _repairedBuildings = new();

        // ── Events ───────────────────────────────────────────────────────────
        public event Action<TeachingPlan>     OnPlanReady;
        public event Action<EngageResponse>   OnChallengeEngaged;
        public event Action<AdvanceResponse>  OnChallengeAdvanced;
        public event Action<string>           OnError;

        // ─────────────────────────────────────────────────────────────────────

        private void Start()
        {
            // Auto-wire to validation results for repair + advance
            if (EduModeManager.Instance != null)
                EduModeManager.Instance.OnValidationComplete += OnValidationComplete;
        }

        private void OnDestroy()
        {
            if (EduModeManager.Instance != null)
                EduModeManager.Instance.OnValidationComplete -= OnValidationComplete;
        }

        // ═══════════════════════════════════════════════════════════════════════
        // PUBLIC API
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Loads a teaching plan from an AnalysisReport.
        /// Automatically applies damage visuals to city.
        /// </summary>
        public void LoadTeachingPlan(
            string analysisReportJson,
            string mode = "open_world",
            Action<TeachingPlan> onComplete = null)
        {
            object analysisReport;
            try
            {
                analysisReport = JsonConvert.DeserializeObject<object>(analysisReportJson);
            }
            catch (Exception ex)
            {
                OnError?.Invoke($"Invalid analysis report JSON: {ex.Message}");
                return;
            }

            var body = new Dictionary<string, object>
            {
                ["analysis_report"] = analysisReport,
                ["student_id"]      = string.IsNullOrEmpty(studentId) ? "anon" : studentId,
                ["mode"]            = mode
            };

            StartCoroutine(Post<TeachingPlan>("/world/analyze", body, plan =>
            {
                if (!plan.success)
                {
                    OnError?.Invoke(plan.error ?? "Failed to load teaching plan");
                    onComplete?.Invoke(plan);
                    return;
                }

                _currentPlanId = plan.plan_id;
                _currentPlan   = plan;

                // Index challenges by ID
                _challengeById.Clear();
                foreach (var c in plan.active_challenges ?? new List<ChallengeItem>())
                    _challengeById[GetChallengeId(c)] = c;
                foreach (var c in plan.queued_challenges ?? new List<ChallengeItem>())
                    _challengeById[GetChallengeId(c)] = c;

                // Apply damage visuals
                ApplyDamageVisuals(plan.active_challenges);

                int activeCount = plan.active_challenge_count > 0
                    ? plan.active_challenge_count
                    : (plan.active_challenges?.Count ?? 0);
                int queuedCount = plan.queued_challenge_count > 0
                    ? plan.queued_challenge_count
                    : (plan.queued_challenges?.Count ?? 0);

                Debug.Log($"[TeachingPlan] Plan {_currentPlanId} loaded. "
                        + $"{activeCount} active, "
                        + $"{queuedCount} queued.");

                OnPlanReady?.Invoke(plan);
                onComplete?.Invoke(plan);
            }));
        }

        /// <summary>
        /// Called when player clicks "Fix This" on a building.
        /// Injects puzzle_id into EduModeManager and fires OnChallengeEngaged.
        /// </summary>
        public void EngageChallenge(string challengeId, Action<EngageResponse> onComplete = null)
        {
            if (!_challengeById.TryGetValue(challengeId, out var challenge))
            {
                OnError?.Invoke($"Challenge {challengeId} not found.");
                return;
            }

            if (challenge.status == "queued")
            {
                // Cannot engage with queued challenge — wait for unlock
                var resp = new EngageResponse { success = false, error = "Challenge not yet unlocked." };
                onComplete?.Invoke(resp);
                return;
            }

            var body = new Dictionary<string, object>
            {
                ["plan_id"]      = _currentPlanId,
                ["challenge_id"] = challengeId
            };

            StartCoroutine(Post<EngageResponse>("/world/engage", body, response =>
            {
                if (response.success)
                {
                    // Inject puzzle_id into EduModeManager
                    var mgr = EduModeManager.Instance;
                    if (mgr != null)
                    {
                        mgr.SetActivePuzzle(response.puzzle_id, response.source_code);
                        Debug.Log($"[TeachingPlan] Engage: puzzle_id={response.puzzle_id}");
                    }
                }
                else
                {
                    OnError?.Invoke(response.error);
                }

                onComplete?.Invoke(response);
                OnChallengeEngaged?.Invoke(response);
            }));
        }

        /// <summary>
        /// Called after successful validation.
        /// Marks challenge complete, unlocks next queued challenge.
        /// </summary>
        public void AdvanceToNext(
            string justCompletedChallengeId,
            Action<AdvanceResponse> onComplete = null)
        {
            var body = new Dictionary<string, object>
            {
                ["plan_id"]      = _currentPlanId,
                ["challenge_id"] = justCompletedChallengeId
            };

            StartCoroutine(Post<AdvanceResponse>("/world/advance", body, response =>
            {
                if (!response.success)
                {
                    OnError?.Invoke(response.error);
                    onComplete?.Invoke(response);
                    return;
                }

                // Mark building as repaired
                _repairedBuildings.Add(justCompletedChallengeId);

                // If next challenge unlocked, show it
                if (response.unlocked_challenge != null)
                {
                    _challengeById[GetChallengeId(response.unlocked_challenge)] = response.unlocked_challenge;
                    ApplyDamageVisual(response.unlocked_challenge);
                    Debug.Log($"[TeachingPlan] Unlocked: {response.unlocked_challenge.display_name}");
                }

                if (response.all_complete)
                    Debug.Log("[TeachingPlan] 🎉 All challenges complete!");

                onComplete?.Invoke(response);
                OnChallengeAdvanced?.Invoke(response);
            }));
        }

        // ═════════════════════════════════════════════════════════════════════
        // INTERNAL
        // ═════════════════════════════════════════════════════════════════════

        private void ApplyDamageVisuals(List<ChallengeItem> challenges)
        {
            foreach (var challenge in challenges ?? new List<ChallengeItem>())
                ApplyDamageVisual(challenge);
        }

        private void ApplyDamageVisual(ChallengeItem challenge)
        {
            if (cityRenderer == null) return;

            var building = cityRenderer.FindBuildingByClassName(challenge.class_name);
            if (building == null) return;

            // BuildingView_WorldModeExtension.cs has these methods:
            if (challenge.status == "queued")
                building.ApplyLockedSmellVisual();
            else
                building.ApplySmellVisuals(challenge.smell_type, SeverityToString(challenge.severity));
        }

        private void OnValidationComplete(ValidationResponse validation)
        {
            if (!validation.success || !validation.smell_resolved) return;

            // Find which challenge this was and repair it + advance
            // (You'll need to track the current active challenge somewhere)
            // For now, assume single active challenge:
            if (_currentPlan?.active_challenges?.Count > 0)
            {
                string challengeId = GetChallengeId(_currentPlan.active_challenges[0]);

                // Repair the building
                var building = cityRenderer.FindBuildingByClassName(
                    _currentPlan.active_challenges[0].class_name);
                if (building != null)
                    building.ApplyRepairVisual();

                // Advance to next
                AdvanceToNext(challengeId);
            }
        }

        // ─────────────────────────────────────────────────────────────────────

        private IEnumerator Post<T>(
            string endpoint,
            Dictionary<string, object> body,
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
                Debug.LogError($"[TeachingPlan] HTTP {req.responseCode}: {req.error}");

            onComplete?.Invoke(result);
        }

        private string SeverityToString(int severity)
        {
            return severity switch
            {
                3 => "error",
                2 => "warning",
                _ => "info"
            };
        }

        private string GetChallengeId(ChallengeItem challenge)
        {
            return !string.IsNullOrEmpty(challenge?.challenge_id)
                ? challenge.challenge_id
                : challenge?.id;
        }
    }

    // ── Extension method on CityRenderer ─────────────────────────────────────
    public static class CityRendererExtensions
    {
        /// <summary>Find a building by its class name.</summary>
        public static BuildingView FindBuildingByClassName(
            this CityRenderer renderer, string className)
        {
            // Your implementation — iterate through spawned buildings
            var allBuildings = FindObjectsOfType<BuildingView>();
            foreach (var b in allBuildings)
                if (b.ClassName == className) return b;
            return null;
        }
    }

    // ── Stubs for existing components ────────────────────────────────────────
    /// <summary>Stub: reference to your existing CityRenderer component.</summary>
    public class CityRenderer : MonoBehaviour
    {
        public void GenerateCity(object analysisReport) { }
    }
}
