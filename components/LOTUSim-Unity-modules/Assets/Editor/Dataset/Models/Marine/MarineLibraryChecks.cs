using System;
using System.Linq;
using Lotusim.Dataset;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using Object = UnityEngine.Object;

namespace Lotusim.EditorTools
{
    public static partial class MarineLibraryBuilder
    {
        [MenuItem("LOTUSim/Models/Validate marine library and flotation")]
        public static void ValidateLibrary()
        {
            CheckFlotationMath();
            var geometry = new Geometry();
            geometry.Box(Vector3.zero, new Vector3(2, 1, 1), 0, .1f);
            geometry.Tube(Vector3.zero, Vector3.up, .05f, 0);
            geometry.Ellipsoid(Vector3.right * 3, Vector3.one, 0);
            geometry.Sail(Vector3.zero, Vector3.up * 4, Vector3.left * 2, .3f, 0);
            geometry.Hull(10, 3, .8f, 1, 0, 1, 2, 3);
            var test = geometry.ToMesh("Marine primitive regression", out var slots);
            try
            {
                CheckMesh(test);
                CheckWinding(test);
            }
            finally
            {
                Object.DestroyImmediate(test);
            }

            foreach (string name in MarineVesselCatalog.Models)
            {
                var prefab = AssetDatabase.LoadAssetAtPath<GameObject>("Assets/Prefabs/" + name + ".prefab");
                if (prefab == null)
                    throw new InvalidOperationException("Missing marine prefab: " + name);
                var response = prefab.GetComponent<MarineVesselWaveMotion>();
                var body = prefab.GetComponent<Rigidbody>();
                if (response == null || response.visual == null || response.visual == prefab.transform || body == null || !body.isKinematic || body.useGravity || response.mode != MarineWaveMode.VisualResponse)
                    throw new InvalidOperationException("Unsafe or incomplete flotation prefab: " + name);
                response.parameters.Validate();
                if (prefab.GetComponentsInChildren<Collider>().Length != 3 || prefab.GetComponentsInChildren<MeshCollider>().Length != 0 || prefab.GetComponentsInChildren<Camera>().Length != 0)
                    throw new InvalidOperationException("Unexpected collider/camera setup: " + name);
                foreach (var r in prefab.GetComponentsInChildren<MeshRenderer>())
                {
                    var mesh = r.GetComponent<MeshFilter>().sharedMesh;
                    CheckMesh(mesh);
                    CheckWinding(mesh);
                    if (r.sharedMaterials.Any(m => m == null || m.shader.name != "HDRP/Lit" || m.GetFloat("_SurfaceType") != 0))
                        throw new InvalidOperationException("Marine annotation materials must stay opaque.");
                    if (mesh.bounds.size.x < response.parameters.lengthM * .9f || mesh.bounds.min.y >= 0)
                        throw new InvalidOperationException("Invalid model units/waterline.");
                }

                var preview = EditorSceneManager.NewPreviewScene();
                var root = (GameObject)PrefabUtility.InstantiatePrefab(prefab, preview);
                try
                {
                    var wave = root.GetComponent<MarineVesselWaveMotion>();
                    var position = root.transform.position;
                    wave.mode = MarineWaveMode.FreeRigidbody;
                    wave.MarkExternallyDriven();
                    if (wave.mode != MarineWaveMode.VisualResponse || !wave.ExternallyDriven || !root.GetComponent<Rigidbody>().isKinematic || root.transform.position != position)
                        throw new InvalidOperationException("ROS ownership failed: " + name);
                }
                finally
                {
                    Object.DestroyImmediate(root);
                    EditorSceneManager.ClosePreviewScene(preview);
                }
            }

            Debug.Log("[Marine Library] PASS seven geometries, units, normals/winding, opaque HDRP, compound colliders, ROS root ownership and flotation math.");
        }

        static void CheckWinding(Mesh mesh)
        {
            var vertices = mesh.vertices;
            var normals = mesh.normals;
            var faces = mesh.triangles;
            for (int i = 0; i < faces.Length; i += 3)
            {
                int a = faces[i], b = faces[i + 1], c = faces[i + 2];
                var cross = Vector3.Cross(vertices[b] - vertices[a], vertices[c] - vertices[a]);
                if (cross.sqrMagnitude < 1e-17f || Vector3.Dot(cross, normals[a] + normals[b] + normals[c]) < -.00001f)
                    throw new InvalidOperationException("Degenerate or inverted face: " + mesh.name + ", triangle " + i / 3);
            }
        }

        public static void CheckFlotationMath()
        {
            for (int i = 0; i < 7; i++)
            {
                var p = MarineVesselCatalog.Parameters(i);
                p.Validate();
                float mass = p.MassKg, g = 9.81f;
                float equilibrium = 9 * MarineVesselWaveMotion.ColumnForce(mass, g, p.draftM, p.draftM, 0, 0, 9);
                if (Math.Abs(equilibrium / (mass * g) - 1) > 1e-5 || MarineVesselWaveMotion.ColumnForce(mass, g, p.draftM, -1, 0, 0, 9) != 0)
                    throw new InvalidOperationException("Hydrostatic equilibrium failed: " + i);
                foreach (float dt in new[]
                {
                    1 / 15f,
                    1 / 30f,
                    1 / 120f,
                    .25f
                }

                )
                {
                    float value = 0, velocity = 0;
                    for (int step = 0; step < 3000; step++)
                        MarineVesselWaveMotion.Spring(ref value, ref velocity, 1, 2, .85f, dt);
                    if (Math.Abs(value - 1) > .0001f || Math.Abs(velocity) > .0001f)
                        throw new InvalidOperationException("Damped wave response did not settle.");
                }
            }
        }
    }
}
