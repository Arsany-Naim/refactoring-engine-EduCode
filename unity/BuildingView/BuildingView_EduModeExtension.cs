using System;
using System.Collections.Generic;
using UnityEngine;
using EduCode.RefactoringGame;

namespace EduCode
{
    /// <summary>
    /// Additional BuildingView methods needed for Escape Room mode.
    /// Merge these into your existing BuildingView.cs (partial class).
    ///
    /// Escape Room mode works differently from Open World:
    ///   - Hints highlight building/floor level, not whole city
    ///   - No damage visuals (puzzles are generated with perfect code)
    ///   - No repair animations
    ///
    /// These methods enable the HintPanel to highlight where a code smell is.
    /// </summary>
    public partial class BuildingView : MonoBehaviour
    {
        // ── Inspector (add these fields to your existing BuildingView) ────────
        [Header("Escape Room Hint")]
        [SerializeField] private Material highlightMaterial;      // bright outline/glow
        [SerializeField] private Color   highlightColor = Color.yellow;

        // ── Properties ───────────────────────────────────────────────────────
        public string ClassName
        {
            get
            {
                // Grab from existing data model
                // Your BuildingView already has this — return it here
                return gameObject.name.Replace("Building_", "");
            }
        }

        // ─────────────────────────────────────────────────────────────────────

        /// <summary>
        /// Returns the Floor (BuildingFloor component) that contains a given method.
        /// Used by HintPanel to highlight the exact location of a code smell.
        /// </summary>
        public BuildingFloor GetFloorByMethodName(string methodName)
        {
            if (string.IsNullOrEmpty(methodName)) return null;

            var floors = GetComponentsInChildren<BuildingFloor>();
            foreach (var floor in floors)
            {
                // Assuming BuildingFloor stores method name in methodDisplay
                var methodDisplay = floor.GetComponentInChildren<TMPro.TMP_Text>();
                if (methodDisplay != null && methodDisplay.text.Contains(methodName))
                    return floor;
            }

            return null;
        }

        /// <summary>
        /// Highlights a specific building or floor for Escape Room hints.
        /// </summary>
        public void HighlightForEscapeRoomHint(string className, string methodName = null)
        {
            // If highlighting a specific floor/method
            if (!string.IsNullOrEmpty(methodName))
            {
                var floor = GetFloorByMethodName(methodName);
                if (floor != null)
                {
                    var renderer = floor.GetComponentInChildren<Renderer>();
                    if (renderer != null && highlightMaterial != null)
                    {
                        renderer.material = highlightMaterial;
                        renderer.material.SetColor("_EmissionColor", highlightColor);
                    }
                }
            }
            else
            {
                // Highlight entire building
                var renderer = GetComponentInChildren<Renderer>();
                if (renderer != null && highlightMaterial != null)
                {
                    renderer.material = highlightMaterial;
                    renderer.material.SetColor("_EmissionColor", highlightColor);
                }
            }
        }

        /// <summary>Clears the Escape Room hint highlight when player dismisses hint.</summary>
        public void ClearHighlight()
        {
            // Restore original material (assuming stored on first run)
            // Your GetComponentInChildren<Renderer>().material = originalMaterial;
            var renderers = GetComponentsInChildren<Renderer>();
            foreach (var r in renderers)
            {
                // Restore to default material
                // This assumes you store the original in a field
            }
        }
    }

    /// <summary>
    /// Stub: Your existing BuildingFloor component.
    /// Referenced here for method lookup.
    /// </summary>
    public class BuildingFloor : MonoBehaviour
    {
        public string methodName;
    }
}
