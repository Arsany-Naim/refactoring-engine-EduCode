using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using TMPro;
using EduCode.RefactoringGame;

namespace EduCode.UI
{
    /// <summary>
    /// VR Hint Panel — displays progressive hints and triggers city highlights.
    ///
    /// Wiring (Inspector):
    ///   hintText          → TMP_Text showing the hint body
    ///   encouragementText → TMP_Text showing the short motivational line
    ///   stageIndicators   → 4 Image objects (filled/unfilled dots)
    ///   requestHintButton → Button player presses to ask for next hint
    ///   hintPanel         → root panel GameObject to show/hide
    ///   cityHighlighter   → reference to CityHighlighter component
    /// </summary>
    public class HintPanelUI : MonoBehaviour
    {
        // ── Inspector References ─────────────────────────────────────────────
        [Header("UI Elements")]
        [SerializeField] private TMP_Text hintText;
        [SerializeField] private TMP_Text encouragementText;
        [SerializeField] private TMP_Text stageLabel;          // "Hint 2 of 4"
        [SerializeField] private TMP_Text smellNameLabel;      // "God Class"
        [SerializeField] private TMP_Text principleLabel;      // "SRP"
        [SerializeField] private Image[] stageIndicators;      // 4 dot images
        [SerializeField] private Button requestHintButton;
        [SerializeField] private Button closeButton;
        [SerializeField] private GameObject hintPanel;
        [SerializeField] private GameObject allHintsUsedPanel;

        [Header("Stage Indicator Colors")]
        [SerializeField] private Color stageUnlockedColor   = new Color(0.2f, 0.8f, 0.4f);
        [SerializeField] private Color stageLockedColor     = new Color(0.3f, 0.3f, 0.3f);
        [SerializeField] private Color stageCurrentColor    = new Color(1f, 0.85f, 0.1f);

        [Header("Dependencies")]
        [SerializeField] private CityHighlighter cityHighlighter;

        // ── Private State ─────────────────────────────────────────────────────
        private List<HintResponse> _hintHistory = new();
        private int _displayedStage = 0;

        // ─────────────────────────────────────────────────────────────────────

        private void Start()
        {
            requestHintButton?.onClick.AddListener(OnRequestHintClicked);
            closeButton?.onClick.AddListener(() => hintPanel.SetActive(false));

            // Escape Room: wired to puzzle generation
            if (EduModeManager.Instance != null)
            {
                EduModeManager.Instance.OnPuzzleGenerated += OnPuzzleGenerated;
                EduModeManager.Instance.OnHintReceived    += OnHintReceived;
            }

            hintPanel.SetActive(false);
        }

        private void OnDestroy()
        {
            if (EduModeManager.Instance != null)
            {
                EduModeManager.Instance.OnPuzzleGenerated -= OnPuzzleGenerated;
                EduModeManager.Instance.OnHintReceived    -= OnHintReceived;
            }
        }

        // ═══════════════════════════════════════════════════════════════════════
        // EVENT HANDLERS
        // ═══════════════════════════════════════════════════════════════════════

        private void OnPuzzleGenerated(GeneratePuzzleResponse puzzle)
        {
            if (!puzzle.success) return;

            // Reset panel for new Escape Room puzzle
            _hintHistory.Clear();
            _displayedStage = 0;

            smellNameLabel.text = puzzle.display_name;
            principleLabel.text = puzzle.principle;
            hintText.text = "Press the hint button when you need guidance.";
            encouragementText.text = "";
            stageLabel.text = "Hint 0 of 4";

            UpdateStageIndicators(0);
            UpdateHintButton(false);
            allHintsUsedPanel?.SetActive(false);
        }

        private void OnHintReceived(HintResponse hint)
        {
            if (!hint.success)
            {
                // All hints exhausted
                allHintsUsedPanel?.SetActive(true);
                requestHintButton.interactable = false;
                return;
            }

            _hintHistory.Add(hint);
            _displayedStage = hint.hint_stage;

            // Update text
            hintText.text = hint.hint_text;
            encouragementText.text = hint.encouragement;
            stageLabel.text = $"Hint {hint.hint_stage} of {hint.max_stages}";

            // Update stage dots
            UpdateStageIndicators(hint.hint_stage);

            // Show panel
            hintPanel.SetActive(true);

            // Disable button if final hint
            if (hint.is_final_hint)
            {
                UpdateHintButton(false);
            }

            // Trigger city highlight
            if (hint.highlight != null && cityHighlighter != null)
            {
                cityHighlighter.HighlightSmell(hint.highlight);
            }
        }

        // ═══════════════════════════════════════════════════════════════════════
        // BUTTON HANDLER
        // ═══════════════════════════════════════════════════════════════════════

        private void OnRequestHintClicked()
        {
            if (EduModeManager.Instance == null) return;

            // Disable button while waiting for response
            requestHintButton.interactable = false;
            hintText.text = "Getting hint...";

            EduModeManager.Instance.RequestHint(onComplete: (hint) =>
            {
                // Re-enable if more hints remain
                if (hint.success && !hint.is_final_hint)
                    requestHintButton.interactable = true;
            });
        }

        // ═══════════════════════════════════════════════════════════════════════
        // UI HELPERS
        // ═══════════════════════════════════════════════════════════════════════

        private void UpdateStageIndicators(int currentStage)
        {
            if (stageIndicators == null) return;
            for (int i = 0; i < stageIndicators.Length; i++)
            {
                int stageNumber = i + 1;
                if (stageNumber < currentStage)
                    stageIndicators[i].color = stageUnlockedColor;
                else if (stageNumber == currentStage)
                    stageIndicators[i].color = stageCurrentColor;
                else
                    stageIndicators[i].color = stageLockedColor;
            }
        }

        private void UpdateHintButton(bool interactable)
        {
            if (requestHintButton != null)
                requestHintButton.interactable = interactable;
        }

        /// <summary>Called from puzzle start button in Unity UI.</summary>
        public void ShowPanel()
        {
            hintPanel.SetActive(true);
            UpdateHintButton(true);
        }
    }
}
