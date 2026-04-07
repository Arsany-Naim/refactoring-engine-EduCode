using System;
using System.Collections;
using UnityEngine;
using UnityEngine.Networking;
using TMPro;
using Newtonsoft.Json;
using EduCode.RefactoringGame;

namespace EduCode
{
    /// <summary>
    /// GitHubModeController — handles the GitHub-specific entry flow.
    ///
    /// Differences from Open World:
    ///   1. Requires GitHub OAuth token (from OAuthController)
    ///   2. Student selects their own repository
    ///   3. Calls /analyze/github (not /analyze/repo) to fetch + analyze
    ///   4. After analysis, hands AnalysisReport JSON to OpenWorldController
    ///      which runs the shared teaching plan + city generation flow
    ///
    /// Wiring:
    ///   - openWorldController  → reference to OpenWorldController in scene
    ///   - oauthController      → reference to OAuthController in scene
    ///   - repoSelectorPanel    → UI panel for picking a repository
    ///   - statusText           → loading/status messages
    /// </summary>
    public class GitHubModeController : MonoBehaviour
    {
        // ── Inspector ────────────────────────────────────────────────────────
        [Header("Dependencies")]
        [SerializeField] private OpenWorldController openWorldController;

        [Header("Backend")]
        [SerializeField] private string backendBaseUrl = "http://localhost:5001";

        [Header("UI")]
        [SerializeField] private GameObject repoSelectorPanel;
        [SerializeField] private TMP_Text   statusText;
        [SerializeField] private TMP_InputField repoUrlInput;
        [SerializeField] private UnityEngine.UI.Button analyzeButton;
        [SerializeField] private GameObject loadingOverlay;

        // ── State ──────────────────────────────────────────────────────────
        private string _githubToken;
        private string _selectedRepoUrl;

        // ─────────────────────────────────────────────────────────────────────

        private void Start()
        {
            analyzeButton?.onClick.AddListener(OnAnalyzeClicked);

            // Grab GitHub token from OAuthController if available
            var oauth = FindObjectOfType<OAuthController>();
            if (oauth != null && oauth.IsAuthenticated())
                _githubToken = oauth.GetToken();
        }

        // ═══════════════════════════════════════════════════════════════════════
        // ENTRY POINT
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Called from the mode selection menu when student picks GitHub Mode.
        /// </summary>
        public void EnterGitHubMode()
        {
            if (string.IsNullOrEmpty(_githubToken))
            {
                SetStatus("Please log in with GitHub first.");
                return;
            }

            // Show repo selector
            if (repoSelectorPanel != null)
                repoSelectorPanel.SetActive(true);

            SetStatus("Enter your repository URL to get started.");
        }

        /// <summary>
        /// Called programmatically if repo URL is already known.
        /// </summary>
        public void AnalyzeRepository(string repoUrl)
        {
            _selectedRepoUrl = repoUrl;
            StartCoroutine(FetchAndAnalyze(repoUrl));
        }

        // ─────────────────────────────────────────────────────────────────────

        private void OnAnalyzeClicked()
        {
            string url = repoUrlInput?.text?.Trim();
            if (string.IsNullOrEmpty(url))
            {
                SetStatus("Please enter a repository URL.");
                return;
            }
            AnalyzeRepository(url);
        }

        // ═══════════════════════════════════════════════════════════════════════
        // ANALYSIS FLOW
        // ═══════════════════════════════════════════════════════════════════════

        private IEnumerator FetchAndAnalyze(string repoUrl)
        {
            // Hide selector, show loading
            if (repoSelectorPanel != null) repoSelectorPanel.SetActive(false);
            if (loadingOverlay   != null) loadingOverlay.SetActive(true);
            SetStatus($"Analyzing {repoUrl}...");

            // POST /world/analyze/github → AnalysisReport
            var body = new System.Collections.Generic.Dictionary<string, object>
            {
                ["repo_url"]     = repoUrl,
                ["github_token"] = _githubToken
            };

            string analysisJson = null;
            bool   success      = false;

            yield return StartCoroutine(PostRaw(
                endpoint:   "/world/analyze/github",
                body:       body,
                onSuccess:  json => { analysisJson = json; success = true; },
                onError:    err  => SetStatus($"Analysis failed: {err}")
            ));

            if (loadingOverlay != null) loadingOverlay.SetActive(false);

            if (!success || string.IsNullOrEmpty(analysisJson))
            {
                SetStatus("Could not analyze repository. Check the URL and try again.");
                if (repoSelectorPanel != null) repoSelectorPanel.SetActive(true);
                yield break;
            }

            SetStatus("Building your city...");

            // Hand off to OpenWorldController — same flow as Open World from here
            if (openWorldController != null)
                openWorldController.OnAnalysisComplete(analysisJson);
            else
                Debug.LogError("[GitHubMode] openWorldController reference not set.");
        }

        // ═══════════════════════════════════════════════════════════════════════
        // HTTP
        // ═══════════════════════════════════════════════════════════════════════

        private IEnumerator PostRaw(
            string endpoint,
            System.Collections.Generic.Dictionary<string, object> body,
            Action<string> onSuccess,
            Action<string> onError)
        {
            string url  = backendBaseUrl.TrimEnd('/') + endpoint;
            string json = JsonConvert.SerializeObject(body);
            byte[] raw  = System.Text.Encoding.UTF8.GetBytes(json);

            using var req = new UnityWebRequest(url, "POST");
            req.uploadHandler   = new UploadHandlerRaw(raw);
            req.downloadHandler = new DownloadHandlerBuffer();
            req.SetRequestHeader("Content-Type", "application/json");
            req.timeout = 120;   // repo analysis can take time

            yield return req.SendWebRequest();

            if (req.result != UnityWebRequest.Result.Success)
                onError?.Invoke($"HTTP {req.responseCode}: {req.error}");
            else
                onSuccess?.Invoke(req.downloadHandler.text);
        }

        // ─────────────────────────────────────────────────────────────────────

        private void SetStatus(string msg)
        {
            if (statusText != null) statusText.text = msg;
            Debug.Log($"[GitHubMode] {msg}");
        }
    }

    // ── Stub for OAuthController reference ───────────────────────────────────
    // Your existing OAuthController.cs already implements these.
    // Declared here as an interface so GitHubModeController compiles standalone.
    public interface IOAuthController
    {
        bool IsAuthenticated();
        string GetToken();
    }
}
