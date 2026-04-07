using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using Newtonsoft.Json;
using EduCode.RefactoringGame;

namespace EduCode
{
    // ═══════════════════════════════════════════════════════════════════════════
    // CITY DIFF DATA MODELS  (mirror the backend CityDiff schema)
    // ═══════════════════════════════════════════════════════════════════════════

    [Serializable]
    public class MethodParameter
    {
        public List<string> parameters;
    }

    [Serializable]
    public class CityClassEntry
    {
        public string            name;
        public string            type;            // "class" | "interface" | "enum"
        public List<string>      methods;
        public List<string>      constructors;
        public List<MethodParameter> methodParameters;
        public List<string>      attributes;
        public int               linesOfCode;
    }

    [Serializable]
    public class CityRelationship
    {
        public string from;
        public string to;
        public string type;   // "extends"|"implements"|"uses"|"aggregates"
    }

    [Serializable]
    public class CityPatch
    {
        public List<CityClassEntry>    updated_classes;
        public List<CityClassEntry>    added_classes;
        public List<string>            removed_classes;
        public List<CityRelationship>  updated_relationships;
        public List<CityRelationship>  added_relationships;
        public List<CityRelationship>  removed_relationships;
    }

    [Serializable]
    public class CityDiff
    {
        public bool             success;
        public string           puzzle_id;
        public string           smell_type;
        public string           affected_class;
        public string           change_type;      // "modified"|"split"|"merged"|"deleted_method"|"added_method"
        public CityPatch        city_patch;
        public List<string>     rebuild_targets;  // class names to rebuild
        public string           error;
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // CITY PATCH APPLIER
    // ═══════════════════════════════════════════════════════════════════════════

    /// <summary>
    /// CityPatchApplier — applies a CityDiff to the live 3D city.
    ///
    /// Called automatically by ValidationPanel after a successful validation
    /// that returns smell_resolved = true and a non-null city_diff.
    ///
    /// What it does per change_type:
    ///   "modified"       → rebuild the existing building in place
    ///   "split"          → rebuild original + spawn new buildings for added classes
    ///   "merged"         → remove original building, update the absorbing class
    ///   "deleted_method" → remove floor(s) from the building
    ///   "added_method"   → add floor(s) to the building
    ///   "deleted"        → destroy the building entirely
    ///
    /// Wiring (Inspector):
    ///   cityRenderer     → CityRenderer reference (existing component)
    ///   connectionRenderer → ConnectionRenderer reference
    ///
    /// Usage:
    ///   CityPatchApplier.Instance.ApplyDiff(cityDiff);
    /// </summary>
    public class CityPatchApplier : MonoBehaviour
    {
        public static CityPatchApplier Instance { get; private set; }

        [Header("Dependencies")]
        [SerializeField] private CityRenderer          cityRenderer;
        [SerializeField] private ConnectionRenderer    connectionRenderer;

        [Header("Animation")]
        [SerializeField] private float rebuildAnimDuration = 0.8f;

        // ── Events ────────────────────────────────────────────────────────────
        public event Action<CityDiff>  OnPatchApplied;
        public event Action<string>    OnPatchError;

        // ─────────────────────────────────────────────────────────────────────

        private void Awake()
        {
            if (Instance != null && Instance != this) { Destroy(gameObject); return; }
            Instance = this;
        }

        private void Start()
        {
            // Auto-wire: listen for validation results that carry a city_diff
            if (EduModeManager.Instance != null)
                EduModeManager.Instance.OnValidationComplete += OnValidationComplete;
        }

        private void OnDestroy()
        {
            if (EduModeManager.Instance != null)
                EduModeManager.Instance.OnValidationComplete -= OnValidationComplete;
        }

        // ═══════════════════════════════════════════════════════════════════════
        // AUTO-TRIGGER FROM VALIDATION
        // ═══════════════════════════════════════════════════════════════════════

        private void OnValidationComplete(ValidationResponse validation)
        {
            // Only apply patch when smell is actually resolved
            if (!validation.success || !validation.smell_resolved)
                return;

            if (validation.city_diff == null)
            {
                Debug.LogWarning("[CityPatch] Validation succeeded but no city_diff returned.");
                return;
            }

            ApplyDiff(validation.city_diff);
        }

        // ═══════════════════════════════════════════════════════════════════════
        // PUBLIC API
        // ═══════════════════════════════════════════════════════════════════════

        /// <summary>
        /// Applies a CityDiff to the live city.
        /// Can be called directly or fires automatically on validation completion.
        /// </summary>
        public void ApplyDiff(CityDiff diff)
        {
            if (diff == null || !diff.success)
            {
                OnPatchError?.Invoke(diff?.error ?? "Null diff received");
                return;
            }

            Debug.Log($"[CityPatch] Applying diff: change_type={diff.change_type} " +
                      $"affected={diff.affected_class} " +
                      $"rebuild_targets=[{string.Join(", ", diff.rebuild_targets ?? new List<string>())}]");

            StartCoroutine(ApplyDiffCoroutine(diff));
        }

        // ═══════════════════════════════════════════════════════════════════════
        // PATCH APPLICATION
        // ═══════════════════════════════════════════════════════════════════════

        private IEnumerator ApplyDiffCoroutine(CityDiff diff)
        {
            var patch = diff.city_patch;

            // Step 1: Remove deleted buildings with animation
            foreach (string removedName in patch.removed_classes ?? new List<string>())
            {
                yield return StartCoroutine(AnimateRemoveBuilding(removedName));
            }

            // Step 2: Update existing buildings
            foreach (var classEntry in patch.updated_classes ?? new List<CityClassEntry>())
            {
                yield return StartCoroutine(AnimateRebuildBuilding(classEntry, diff.change_type));
            }

            // Step 3: Spawn new buildings (e.g. after Extract Class)
            foreach (var classEntry in patch.added_classes ?? new List<CityClassEntry>())
            {
                yield return StartCoroutine(AnimateSpawnBuilding(classEntry, diff.affected_class));
            }

            // Step 4: Update connections
            ApplyRelationshipPatches(patch, diff.affected_class);

            Debug.Log($"[CityPatch] Patch applied. Rebuilt: {string.Join(", ", diff.rebuild_targets ?? new List<string>())}");
            OnPatchApplied?.Invoke(diff);
        }

        // ── Building operations ───────────────────────────────────────────────

        private IEnumerator AnimateRebuildBuilding(CityClassEntry classEntry, string changeType)
        {
            var building = FindBuilding(classEntry.name);
            if (building == null)
            {
                Debug.LogWarning($"[CityPatch] Building not found for rebuild: {classEntry.name}");
                yield break;
            }

            // Convert CityClassEntry to ClassReport that BuildingView.SetData expects
            var classReport = ConvertToClassReport(classEntry);

            // Animate out → update → animate in
            yield return StartCoroutine(building.AnimateOut(rebuildAnimDuration * 0.4f));
            building.SetData(classReport, building.BuildingIndex);
            building.GenerateFloors();
            yield return StartCoroutine(building.AnimateIn(rebuildAnimDuration * 0.6f));
        }

        private IEnumerator AnimateRemoveBuilding(string className)
        {
            var building = FindBuilding(className);
            if (building == null) yield break;

            yield return StartCoroutine(building.AnimateOut(rebuildAnimDuration));
            Destroy(building.gameObject);
        }

        private IEnumerator AnimateSpawnBuilding(CityClassEntry classEntry, string nearClassName)
        {
            // Find position near the original building
            var nearBuilding = FindBuilding(nearClassName);
            Vector3 spawnPos = nearBuilding != null
                ? nearBuilding.transform.position + new Vector3(8f, 0, 0)
                : Vector3.zero;

            // Ask CityRenderer to spawn a new building
            var classReport = ConvertToClassReport(classEntry);
            var newBuilding = cityRenderer.SpawnBuilding(classReport, spawnPos);

            if (newBuilding != null)
                yield return StartCoroutine(newBuilding.AnimateIn(rebuildAnimDuration));
        }

        // ── Relationship operations ───────────────────────────────────────────

        private void ApplyRelationshipPatches(CityPatch patch, string affectedClass)
        {
            if (connectionRenderer == null) return;

            // Remove stale connections
            foreach (var rel in patch.removed_relationships ?? new List<CityRelationship>())
                connectionRenderer.RemoveConnection(rel.from, rel.to, rel.type);

            // Add new connections
            foreach (var rel in patch.added_relationships ?? new List<CityRelationship>())
                connectionRenderer.AddConnection(rel.from, rel.to, rel.type);

            // Update changed connections
            foreach (var rel in patch.updated_relationships ?? new List<CityRelationship>())
            {
                connectionRenderer.RemoveConnection(rel.from, rel.to, rel.type);
                connectionRenderer.AddConnection(rel.from, rel.to, rel.type);
            }
        }

        // ═══════════════════════════════════════════════════════════════════════
        // HELPERS
        // ═══════════════════════════════════════════════════════════════════════

        private BuildingView FindBuilding(string className)
        {
            var allBuildings = FindObjectsOfType<BuildingView>();
            foreach (var b in allBuildings)
                if (b.ClassName == className) return b;
            return null;
        }

        private ClassReport ConvertToClassReport(CityClassEntry entry)
        {
            // Convert cityData.json class entry format into ClassReport
            // that your existing BuildingView.SetData() accepts.
            var methods = new List<MethodReport>();
            for (int i = 0; i < (entry.methods?.Count ?? 0); i++)
            {
                var paramList = (entry.methodParameters != null && i < entry.methodParameters.Count)
                    ? entry.methodParameters[i].parameters
                    : new List<string>();

                methods.Add(new MethodReport
                {
                    name       = entry.methods[i],
                    parameters = paramList
                });
            }

            return new ClassReport
            {
                className  = entry.name,
                classType  = entry.type,
                methods    = methods,
                attributes = entry.attributes,
                lines      = entry.linesOfCode
            };
        }
    }
}
