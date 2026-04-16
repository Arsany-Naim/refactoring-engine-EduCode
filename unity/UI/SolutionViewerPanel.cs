using System;
using UnityEngine;
using UnityEngine.UI;
using TMPro;
using EduCode.WorldMode;

namespace EduCode.UI
{
    /// <summary>
    /// SolutionViewerPanel — Open World Mode only.
    ///
    /// Shows the server-generated refactored code after /world/solve succeeds.
    /// Listens to TeachingPlanManager.OnChallengeSolved and displays the result.
    ///
    /// Wiring (Inspector):
    ///   panel              → root GameObject to show/hide
    ///   titleText          → "God Class in OrderProcessor"
    ///   summaryText        → 1-2 sentence explanation from Gemini
    ///   refactoredCodeText → the refactored Java source
    ///   nextButton         → dismisses and signals ready for next challenge
    ///   closeButton        → dismisses the panel
    ///   teachingPlanManager → source of OnChallengeSolved events
    /// </summary>
    public class SolutionViewerPanel : MonoBehaviour
    {
        [Header("Panel Root")]
        [SerializeField] private GameObject panel;

        [Header("Content")]
        [SerializeField] private TMP_Text titleText;
        [SerializeField] private TMP_Text summaryText;
        [SerializeField] private TMP_Text refactoredCodeText;

        [Header("Buttons")]
        [SerializeField] private Button nextButton;
        [SerializeField] private Button closeButton;

        [Header("Dependencies")]
        [SerializeField] private TeachingPlanManager teachingPlanManager;

        public event Action OnDismissed;

        private void Start()
        {
            if (teachingPlanManager != null)
                teachingPlanManager.OnChallengeSolved += Show;

            nextButton?.onClick.AddListener(Hide);
            closeButton?.onClick.AddListener(Hide);

            if (panel != null) panel.SetActive(false);
        }

        private void OnDestroy()
        {
            if (teachingPlanManager != null)
                teachingPlanManager.OnChallengeSolved -= Show;
        }

        public void Show(SolveResponse solve)
        {
            if (solve == null || !solve.success) return;

            if (titleText != null)
                titleText.text = $"{solve.display_name} in {solve.class_name}";

            if (summaryText != null)
                summaryText.text = string.IsNullOrEmpty(solve.summary)
                    ? "Refactor applied."
                    : solve.summary;

            if (refactoredCodeText != null)
                refactoredCodeText.text = solve.refactored_code ?? "";

            if (panel != null) panel.SetActive(true);
        }

        public void Hide()
        {
            if (panel != null) panel.SetActive(false);
            OnDismissed?.Invoke();
        }
    }
}
