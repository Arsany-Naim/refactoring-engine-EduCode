using System;
using System.Collections;
using UnityEngine;
using TMPro;

namespace EduCode.RefactoringGame
{
    /// <summary>
    /// Additional BuildingView methods needed for Open World / GitHub mode.
    /// Merge these into your existing BuildingView.cs (partial class).
    ///
    /// New responsibilities:
    ///   - ApplySmellVisuals(smellType, severity)  — persistent damage per smell type
    ///   - ApplyRepairVisual()                     — healing animation on fix
    ///   - ApplyLockedSmellVisual()                — dim/gray for queued challenges
    ///   - ShowEngagePrompt(name, principle, cb)   — floating "Fix This?" UI
    ///   - HideEngagePrompt()
    /// </summary>
    public partial class BuildingView : MonoBehaviour
    {
        // ── Inspector (add these fields to your existing BuildingView) ────────
        [Header("World Mode Visuals")]
        [SerializeField] private Material cleanMaterial;
        [SerializeField] private Material damagedMaterial;        // error smells
        [SerializeField] private Material warnMaterial;           // warning smells
        [SerializeField] private Material infoMaterial;           // info smells
        [SerializeField] private Material lockedMaterial;         // queued/locked
        [SerializeField] private ParticleSystem damageParticles;
        [SerializeField] private ParticleSystem repairParticles;

        [Header("Engage Prompt")]
        [SerializeField] private GameObject engagePromptPrefab;   // floating panel prefab
        [SerializeField] private Vector3    promptOffset = new Vector3(0, 5f, 0);

        // ── Runtime ───────────────────────────────────────────────────────────
        private GameObject _engagePromptInstance;
        private Coroutine  _repairCoroutine;
        private bool       _isDamaged;

        // ═══════════════════════════════════════════════════════════════════════
        // DAMAGE VISUALS
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Applies persistent damage visuals based on smell type and severity.
        /// Called by TeachingPlanManager.ApplyDamageToBuilding().
        /// </summary>
        public void ApplySmellVisuals(string smellType, string severity)
        {
            _isDamaged = true;
            var renderer = GetComponentInChildren<Renderer>();
            if (renderer == null) return;

            // Choose material by severity
            renderer.material = severity switch
            {
                "error"   => damagedMaterial  ?? renderer.material,
                "warning" => warnMaterial     ?? renderer.material,
                "info"    => infoMaterial     ?? renderer.material,
                _         => warnMaterial     ?? renderer.material
            };

            // Smell-specific particle effects
            if (damageParticles != null)
            {
                var main = damageParticles.main;
                main.startColor = severity switch
                {
                    "error"   => new Color(1f, 0.2f, 0.2f),   // red
                    "warning" => new Color(1f, 0.65f, 0f),    // orange
                    "info"    => new Color(0.3f, 0.6f, 1f),   // blue
                    _         => Color.yellow
                };

                if (!damageParticles.isPlaying)
                    damageParticles.Play();
            }

            // God Class / Shotgun Surgery → shake animation (more severe)
            if (smellType == "GodClass" || smellType == "ShotgunSurgery")
                StartCoroutine(SubtleShake());
        }

        /// <summary>
        /// Dims the building for queued (not yet unlocked) challenges.
        /// </summary>
        public void ApplyLockedSmellVisual()
        {
            var renderer = GetComponentInChildren<Renderer>();
            if (renderer != null && lockedMaterial != null)
                renderer.material = lockedMaterial;

            // No particles, no interaction
            if (damageParticles != null)
                damageParticles.Stop();
        }

        // ═══════════════════════════════════════════════════════════════════════
        // REPAIR VISUAL
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Triggers the building repair animation.
        /// Called by TeachingPlanManager.RepairBuilding() after a successful fix.
        /// </summary>
        public void ApplyRepairVisual()
        {
            _isDamaged = false;

            if (_repairCoroutine != null)
                StopCoroutine(_repairCoroutine);

            _repairCoroutine = StartCoroutine(RepairSequence());
        }

        private IEnumerator RepairSequence()
        {
            // Stop damage particles
            if (damageParticles != null)
                damageParticles.Stop();

            // Play repair particles
            if (repairParticles != null)
                repairParticles.Play();

            // Animate material back to clean over 1.5 seconds
            var renderer = GetComponentInChildren<Renderer>();
            if (renderer != null && cleanMaterial != null)
            {
                float elapsed = 0f;
                float duration = 1.5f;
                Material current = renderer.material;

                while (elapsed < duration)
                {
                    elapsed += Time.deltaTime;
                    float t = elapsed / duration;
                    // Lerp emission to zero as building "heals"
                    Color emission = Color.Lerp(
                        current.GetColor("_EmissionColor"),
                        Color.black,
                        t
                    );
                    current.SetColor("_EmissionColor", emission);
                    yield return null;
                }

                renderer.material = cleanMaterial;
            }

            // Stop repair particles after 2 seconds
            yield return new WaitForSeconds(2f);
            if (repairParticles != null)
                repairParticles.Stop();
        }

        // ═══════════════════════════════════════════════════════════════════════
        // ENGAGE PROMPT
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Shows a floating "Fix This?" prompt above the building.
        /// onEngageClicked fires when the player presses the button.
        /// </summary>
        public void ShowEngagePrompt(
            string smellName,
            string principle,
            Action onEngageClicked)
        {
            if (engagePromptPrefab == null) return;

            // Remove existing prompt if any
            HideEngagePrompt();

            _engagePromptInstance = Instantiate(
                engagePromptPrefab,
                transform.position + promptOffset,
                Quaternion.identity,
                transform
            );

            // Configure the prompt UI
            var prompt = _engagePromptInstance.GetComponent<EngagePromptUI>();
            if (prompt != null)
                prompt.Setup(smellName, principle, onEngageClicked);
        }

        /// <summary>Hides the engage prompt (after engagement or repair).</summary>
        public void HideEngagePrompt()
        {
            if (_engagePromptInstance != null)
            {
                Destroy(_engagePromptInstance);
                _engagePromptInstance = null;
            }
        }

        // ═══════════════════════════════════════════════════════════════════════
        // ANIMATIONS
        // ═══════════════════════════════════════════════════════════════════════

        private IEnumerator SubtleShake()
        {
            Vector3 originalPos = transform.localPosition;
            float   duration    = 0.4f;
            float   magnitude   = 0.05f;
            float   elapsed     = 0f;

            while (elapsed < duration)
            {
                elapsed += Time.deltaTime;
                transform.localPosition = originalPos + new Vector3(
                    UnityEngine.Random.Range(-magnitude, magnitude),
                    UnityEngine.Random.Range(-magnitude * 0.3f, magnitude * 0.3f),
                    0f
                );
                yield return null;
            }

            transform.localPosition = originalPos;
        }
    }

    // ── Engage Prompt UI component ────────────────────────────────────────────

    /// <summary>
    /// Attach to the engage prompt prefab.
    /// Shows smell name, principle, and a "Fix This?" button.
    /// </summary>
    public class EngagePromptUI : MonoBehaviour
    {
        [SerializeField] private TMP_Text  smellNameText;
        [SerializeField] private TMP_Text  principleText;
        [SerializeField] private UnityEngine.UI.Button engageButton;

        public void Setup(string smellName, string principle, Action onEngage)
        {
            if (smellNameText != null) smellNameText.text = smellName;
            if (principleText != null) principleText.text = principle;

            engageButton?.onClick.RemoveAllListeners();
            engageButton?.onClick.AddListener(() => onEngage?.Invoke());
        }
    }
}
