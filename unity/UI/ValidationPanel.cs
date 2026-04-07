using System;
using System.Collections;
using UnityEngine;
using UnityEngine.UI;
using TMPro;
using EduCode.RefactoringGame;
using EduCode.WorldMode;

namespace EduCode.UI
{
    /// <summary>
    /// ValidationPanel — shows the result of a refactoring attempt.
    /// Works in all three modes: Escape Room, Open World, and GitHub.
    ///
    /// Wiring (Inspector):
    ///   panel              → root GameObject to show/hide
    ///   scoreText          → "87 / 100"
    ///   starsContainer     → parent of 3 star Image objects
    ///   starImages         → 3 Image references (filled/unfilled)
    ///   feedbackText       → Gemini's feedback paragraph
    ///   smellStatusText    → "✓ God Class resolved" or "✗ Not yet fixed"
    ///   newSmellsText      → "⚠ Introduced: Long Method" (shown if any)
    ///   tryAgainButton     → shown when smell_resolved = false
    ///   nextChallengeButton → shown when smell_resolved = true (world modes)
    ///   continueButton     → shown when smell_resolved = true (Escape Room)
    ///   partialCreditPanel → shown when partial_credit = true
    ///   partialReasonText  → explains partial credit
    /// </summary>
    public class ValidationPanel : MonoBehaviour
    {
        // ── Inspector ────────────────────────────────────────────────────────
        [Header("Panel Root")]
        [SerializeField] private GameObject panel;

        [Header("Score & Stars")]
        [SerializeField] private TMP_Text scoreText;
        [SerializeField] private GameObject starsContainer;
        [SerializeField] private Image[]    starImages;         // 3 stars
        [SerializeField] private Color      starFilledColor  = new Color(1f, 0.85f, 0.1f);
        [SerializeField] private Color      starEmptyColor   = new Color(0.3f, 0.3f, 0.3f);

        [Header("Feedback")]
        [SerializeField] private TMP_Text feedbackText;
        [SerializeField] private TMP_Text smellStatusText;
        [SerializeField] private TMP_Text newSmellsText;
        [SerializeField] private GameObject newSmellsPanel;

        [Header("Partial Credit")]
        [SerializeField] private GameObject partialCreditPanel;
        [SerializeField] private TMP_Text   partialReasonText;

        [Header("Buttons")]
        [SerializeField] private Button tryAgainButton;
        [SerializeField] private Button nextChallengeButton;   // world modes
        [SerializeField] private Button continueButton;        // Escape Room
        [SerializeField] private Button closeButton;

        [Header("Mode")]
        [SerializeField] private bool isEscapeRoomMode = false;

        // ── Events ────────────────────────────────────────────────────────────
        public event Action OnTryAgain;
        public event Action OnNextChallenge;
        public event Action OnContinue;

        // ─────────────────────────────────────────────────────────────────────

        private void Start()
        {
            tryAgainButton?.onClick.AddListener(() => {
                Hide();
                OnTryAgain?.Invoke();
            });

            nextChallengeButton?.onClick.AddListener(() => {
                Hide();
                OnNextChallenge?.Invoke();
            });

            continueButton?.onClick.AddListener(() => {
                Hide();
                OnContinue?.Invoke();
            });

            closeButton?.onClick.AddListener(Hide);

            // Auto-wire to validation events
            if (EduModeManager.Instance != null)
                EduModeManager.Instance.OnValidationComplete += Show;

            panel?.SetActive(false);
        }

        private void OnDestroy()
        {
            if (EduModeManager.Instance != null)
                EduModeManager.Instance.OnValidationComplete -= Show;
        }

        // ═══════════════════════════════════════════════════════════════════════
        // PUBLIC API
        // ═══════════════════════════════════════════════════════════════════════

        public void Show(ValidationResponse result)
        {
            if (!result.success) return;

            // Score
            if (scoreText != null)
                scoreText.text = $"{result.score} / 100";

            // Stars
            UpdateStars(result.stars);

            // Smell resolved status
            if (smellStatusText != null)
            {
                smellStatusText.text = result.smell_resolved
                    ? $"✓ {result.smell_resolved} resolved"
                    : "✗ Smell not yet resolved — keep going";
                smellStatusText.color = result.smell_resolved
                    ? new Color(0.2f, 0.8f, 0.4f)
                    : new Color(1f, 0.4f, 0.4f);
            }

            // Feedback paragraph
            if (feedbackText != null)
                feedbackText.text = result.feedback;

            // New smells introduced warning
            bool hasNewSmells = result.new_smells_introduced?.Count > 0;
            if (newSmellsPanel != null)
                newSmellsPanel.SetActive(hasNewSmells);
            if (hasNewSmells && newSmellsText != null)
                newSmellsText.text = "⚠ Introduced: " +
                    string.Join(", ", result.new_smells_introduced);

            // Partial credit
            bool isPartial = result.partial_credit && !result.smell_resolved;
            if (partialCreditPanel != null)
                partialCreditPanel.SetActive(isPartial);
            if (isPartial && partialReasonText != null && result.partial_reason != null)
                partialReasonText.text = result.partial_reason;

            // Button visibility
            bool resolved = result.smell_resolved;
            tryAgainButton?.gameObject.SetActive(!resolved);

            if (isEscapeRoomMode)
            {
                continueButton?.gameObject.SetActive(resolved);
                nextChallengeButton?.gameObject.SetActive(false);
            }
            else
            {
                nextChallengeButton?.gameObject.SetActive(resolved);
                continueButton?.gameObject.SetActive(false);
            }

            // Show with entrance animation
            panel?.SetActive(true);
            StartCoroutine(AnimateIn());
        }

        public void Hide()
        {
            panel?.SetActive(false);
        }

        // ═══════════════════════════════════════════════════════════════════════
        // INTERNAL
        // ═══════════════════════════════════════════════════════════════════════

        private void UpdateStars(int earned)
        {
            if (starImages == null) return;
            for (int i = 0; i < starImages.Length; i++)
                starImages[i].color = (i < earned) ? starFilledColor : starEmptyColor;
        }

        private IEnumerator AnimateIn()
        {
            if (panel == null) yield break;

            // Simple scale-in from 0.8 → 1.0
            var canvasGroup = panel.GetComponent<CanvasGroup>();
            if (canvasGroup == null)
                canvasGroup = panel.AddComponent<CanvasGroup>();

            canvasGroup.alpha = 0f;
            panel.transform.localScale = Vector3.one * 0.85f;

            float elapsed = 0f;
            float duration = 0.25f;

            while (elapsed < duration)
            {
                elapsed += Time.deltaTime;
                float t = elapsed / duration;
                canvasGroup.alpha = Mathf.Lerp(0f, 1f, t);
                panel.transform.localScale = Vector3.Lerp(
                    Vector3.one * 0.85f, Vector3.one, t);
                yield return null;
            }

            canvasGroup.alpha = 1f;
            panel.transform.localScale = Vector3.one;
        }
    }
}
