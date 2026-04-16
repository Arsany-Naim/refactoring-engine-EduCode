using System;
using System.Collections;
using UnityEngine;
using Newtonsoft.Json;
using EduCode.RefactoringGame;
using EduCode.WorldMode;

namespace EduCode
{
    /// <summary>
    /// OpenWorldController — drives Open World and GitHub Modes.
    ///
    /// Full flow:
    ///   1. OnRepositorySelected()  → GitHubAdapter fetches Java files
    ///   2. AnalyzeAndBuild()       → HybridAnalysisPipeline analyzes code
    ///                             → CityRenderer generates the 3D city
    ///   3. LoadTeachingPlan()      → TeachingPlanManager sends AnalysisReport
    ///                               to /edumode/analyze → damaged buildings appear
    ///   4. OnBuildingEngaged()     → Player clicks "Fix This" on a building
    ///                             → TeachingPlanManager.EngageChallenge()
    ///                             → EduModeManager gets puzzle_id injected
    ///   5. Hint loop               → HintPanelUI handles via EduModeManager
    ///   6. Validate                → EduModeManager.ValidateRefactoring()
    ///   7. OnValidationComplete    → TeachingPlanManager repairs building,
    ///                               advances plan, unlocks next challenge
    ///
    /// This class owns the orchestration.
    /// TeachingPlanManager owns the teaching plan state.
    /// EduModeManager owns the active puzzle (hint/validate) state.
    /// </summary>
    public class OpenWorldController : MonoBehaviour
    {
        // ── Inspector ────────────────────────────────────────────────────────
        [Header("Core Components")]
        [SerializeField] private CityRenderer         cityRenderer;
        [SerializeField] private TeachingPlanManager  teachingPlanManager;

        [Header("Mode")]
        [SerializeField] private bool isGitHubMode = false;

        [Header("UI")]
        [SerializeField] private GameObject loadingPanel;
        [SerializeField] private GameObject progressSummaryPanel;
        [SerializeField] private TMPro.TMP_Text summaryText;
        [SerializeField] private TMPro.TMP_Text statusText;

        // ── State ──────────────────────────────────────────────────────────
        private string _lastAnalysisReportJson;

        // ═══════════════════════════════════════════════════════════════════
        // UNITY LIFECYCLE
        // ═══════════════════════════════════════════════════════════════════

        private void Start()
        {
            // Wire TeachingPlanManager events
            if (teachingPlanManager != null)
            {
                teachingPlanManager.OnPlanReady       += OnPlanReady;
                teachingPlanManager.OnChallengeEngaged += OnChallengeEngaged;
                teachingPlanManager.OnChallengeAdvanced += OnChallengeAdvanced;
                teachingPlanManager.OnChallengeSolved  += OnChallengeSolved;
                teachingPlanManager.OnError            += OnTeachingPlanError;
            }

            // Wire EduModeManager events (GitHub mode only — Open World skips validate)
            if (EduModeManager.Instance != null)
            {
                EduModeManager.Instance.OnValidationComplete += OnValidationComplete;
                EduModeManager.Instance.OnError += OnEduModeError;
            }
        }

        private void OnDestroy()
        {
            if (teachingPlanManager != null)
            {
                teachingPlanManager.OnPlanReady        -= OnPlanReady;
                teachingPlanManager.OnChallengeEngaged  -= OnChallengeEngaged;
                teachingPlanManager.OnChallengeAdvanced -= OnChallengeAdvanced;
                teachingPlanManager.OnChallengeSolved   -= OnChallengeSolved;
                teachingPlanManager.OnError             -= OnTeachingPlanError;
            }

            if (EduModeManager.Instance != null)
            {
                EduModeManager.Instance.OnValidationComplete -= OnValidationComplete;
                EduModeManager.Instance.OnError -= OnEduModeError;
            }
        }

        /// <summary>
        /// Called by BuildingView (or the "Fix This" UI) when the player picks a
        /// damaged building. In Open World we call /world/solve directly — the
        /// server refactors the class and returns the fix. In GitHub mode we
        /// keep the interactive engage → hint → validate flow.
        /// </summary>
        public void OnBuildingInteract(
            string challengeId,
            CityClassEntry originalCityClass = null,
            System.Collections.Generic.List<CityRelationship> originalRelationships = null)
        {
            if (teachingPlanManager == null) return;

            if (isGitHubMode)
            {
                teachingPlanManager.EngageChallenge(challengeId);
            }
            else
            {
                SetStatus("Refactoring...");
                teachingPlanManager.SolveChallenge(challengeId, originalCityClass, originalRelationships);
            }
        }

        // ═══════════════════════════════════════════════════════════════════
        // STEP 1 + 2 — ANALYZE AND BUILD CITY
        // ═══════════════════════════════════════════════════════════════════

        /// <summary>
        /// Entry point. Called when user selects a repository (GitHub mode)
        /// or when Open World mode loads its pre-built codebase.
        ///
        /// analysisReportJson: the JSON string from your existing
        /// HybridAnalysisPipeline (/analyze/repo or /analyze/github).
        /// </summary>
        public void OnAnalysisComplete(string analysisReportJson)
        {
            _lastAnalysisReportJson = analysisReportJson;

            SetStatus("Building city...");
            ShowLoading(true);

            // Parse the report and build the city
            var report = JsonConvert.DeserializeObject<AnalysisReport>(analysisReportJson);
            cityRenderer.GenerateCity(report);

            // Once city is built, load the teaching plan
            // (In practice, hook this to CityRenderer's OnCityGenerated event)
            StartCoroutine(LoadTeachingPlanAfterCityBuilds());
        }

        private IEnumerator LoadTeachingPlanAfterCityBuilds()
        {
            // Wait one frame for city to fully instantiate buildings
            yield return new WaitForEndOfFrame();
            yield return new WaitForSeconds(0.5f);   // allow physics settle

            ShowLoading(false);
            SetStatus("Analyzing code quality...");

            // Step 3 — Load teaching plan
            teachingPlanManager.LoadTeachingPlan(
                _lastAnalysisReportJson,
                mode: isGitHubMode ? "github" : "open_world",
                onComplete: _ => SetStatus("Explore the city. Damaged buildings need your help.")
            );
        }

        // ═══════════════════════════════════════════════════════════════════
        // STEP 3 — TEACHING PLAN READY
        // ═══════════════════════════════════════════════════════════════════

        private void OnPlanReady(TeachingPlan plan)
        {
            if (!plan.success) return;

            // Show summary panel
            if (summaryText != null)
                summaryText.text = plan.summary;

            if (progressSummaryPanel != null)
                progressSummaryPanel.SetActive(true);

            string mode = isGitHubMode ? "your repository" : "this codebase";
            Debug.Log($"[OpenWorld] Teaching plan ready. "
                    + $"{plan.active_challenges?.Count} buildings damaged in {mode}.");
        }

        // ═══════════════════════════════════════════════════════════════════
        // STEP 4 — BUILDING ENGAGED
        // ═══════════════════════════════════════════════════════════════════

        private void OnChallengeEngaged(EngageResponse response)
        {
            if (!response.success) return;

            SetStatus($"Fixing: {response.display_name} in {response.class_name}");

            // HintPanelUI will now automatically show because EduModeManager
            // has the puzzle_id injected and is ready to serve hints.
            // (Reached only in GitHub mode — Open World uses /world/solve.)
            Debug.Log($"[OpenWorld] Challenge engaged. "
                    + $"Principle: {response.principle}. "
                    + $"Note: {response.educator_note}");
        }

        // ═══════════════════════════════════════════════════════════════════
        // STEP 5 (OPEN WORLD) — CHALLENGE AUTO-SOLVED
        // ═══════════════════════════════════════════════════════════════════

        private void OnChallengeSolved(SolveResponse response)
        {
            if (!response.success)
            {
                SetStatus($"Could not refactor: {response.error ?? response.message ?? "unknown error"}");
                return;
            }

            SetStatus($"Refactored: {response.display_name} in {response.class_name}");
            Debug.Log($"[OpenWorld] Solved {response.class_name}. Summary: {response.summary}");

            if (response.all_complete)
                SetStatus("All code smells resolved! This codebase is clean.");
            else if (response.unlocked_challenge != null)
                SetStatus($"Next up: {response.unlocked_challenge.display_name} in {response.unlocked_challenge.class_name}");
        }

        // ═══════════════════════════════════════════════════════════════════
        // STEP 6 — VALIDATION COMPLETE
        // ═══════════════════════════════════════════════════════════════════

        private void OnValidationComplete(ValidationResponse validation)
        {
            if (!validation.success) return;

            if (validation.smell_resolved)
            {
                SetStatus($"Fixed! Score: {validation.score}/100 · {validation.stars}⭐");
                // TeachingPlanManager listens to this same event and handles
                // building repair + plan advancement automatically.
            }
            else
            {
                SetStatus("Not quite — try again or request another hint.");
            }
        }

        // ═══════════════════════════════════════════════════════════════════
        // STEP 7 — CHALLENGE ADVANCED (next unlocked)
        // ═══════════════════════════════════════════════════════════════════

        private void OnChallengeAdvanced(AdvanceResponse response)
        {
            if (!response.success) return;

            if (response.all_complete)
            {
                SetStatus("🎉 All code smells resolved! This codebase is clean.");
                return;
            }

            if (response.unlocked_challenge != null)
            {
                SetStatus($"New challenge unlocked: "
                        + $"{response.unlocked_challenge.display_name} "
                        + $"in {response.unlocked_challenge.class_name}");
            }
            else
            {
                SetStatus($"{response.remaining_active} challenges remaining.");
            }
        }

        // ═══════════════════════════════════════════════════════════════════
        // ERROR HANDLING
        // ═══════════════════════════════════════════════════════════════════

        private void OnTeachingPlanError(string error)
        {
            SetStatus($"Error: {error}");
            Debug.LogError($"[OpenWorld] TeachingPlan error: {error}");
        }

        private void OnEduModeError(string error)
        {
            SetStatus($"Error: {error}");
            Debug.LogError($"[OpenWorld] EduMode error: {error}");
        }

        // ═══════════════════════════════════════════════════════════════════
        // UI HELPERS
        // ═══════════════════════════════════════════════════════════════════

        private void ShowLoading(bool show)
        {
            if (loadingPanel != null)
                loadingPanel.SetActive(show);
        }

        private void SetStatus(string message)
        {
            if (statusText != null)
                statusText.text = message;
            Debug.Log($"[OpenWorld] {message}");
        }
    }

    // ── Placeholder types that your existing code already defines ────────────
    // These are referenced here for compilation. Your actual implementations
    // are in CityRenderer.cs and the analysis pipeline.

    [Serializable]
    public class AnalysisReport
    {
        // Matches the AnalysisReport schema from HybridAnalysisPipeline
        // Your existing implementation — referenced here for the cast above.
    }
}
