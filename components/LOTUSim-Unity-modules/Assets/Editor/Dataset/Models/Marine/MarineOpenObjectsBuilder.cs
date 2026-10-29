using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Lotusim.Dataset;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;
using UnityEngine.SceneManagement;
using Object = UnityEngine.Object;

namespace Lotusim.EditorTools
{
    public static class MarineOpenObjectsBuilder
    {
        public const string Root = "Assets/models/open_objects", Scene = "Assets/Scenes/Models/OpenObjectsLibrary.unity";
        [Serializable]
        public sealed class Info
        {
            public string key, category, title, author, source, license, licenseUrl, sha256, kind;
            public float lengthM, beamM, draftM, heightM, animationSeconds;
            public int vertices, triangles, animationFrames, maxTextureSize;
            public MarineOpenBoatsBuilder.MaterialInfo[] materials;
            public string[] changes;
        }

        public static Info ReadInfo(string key) => JsonUtility.FromJson<Info>(File.ReadAllText(Root + "/" + key + "/model-info.json"));
        [MenuItem("LOTUSim/Models/External objects CC-BY/1 - Build audited prefabs")]
        public static void BuildAll()
        {
            if (EditorApplication.isPlayingOrWillChangePlaymode)
                throw new InvalidOperationException("Quit Play first.");
            AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
            foreach (var key in DatasetExternalAssetCatalog.Models)
                Build(key);
            AssetDatabase.SaveAssets();
            Validate();
            CreateShowcase();
        }

        static void Build(string key)
        {
            string folder = Root + "/" + key, path = "Assets/Prefabs/" + key + ".prefab";
            var info = ReadInfo(key);
            if (info.key != key || info.license != "CC-BY-4.0" || info.sha256.Length != 64)
                throw new InvalidDataException("Unaudited external asset: " + key);
            var prior = AssetDatabase.LoadAssetAtPath<GameObject>(path);
            if (prior != null && prior.GetComponent<OpenBoatAssetCredit>() == null)
                throw new IOException("Unrelated prefab at " + path);
            MarineOpenBoatsBuilder.Folder(folder + "/Meshes");
            Mesh[][] frames;
            Material[] materials;
            if (info.kind == "bird")
            {
                frames = BakeBird(folder, info);
                materials = new[]
                {
                    BirdMaterial(folder)
                };
            }
            else
            {
                materials = info.materials.Select((m, i) => MarineOpenBoatsBuilder.Material(folder, m, i)).ToArray();
                frames = new Mesh[Math.Max(1, info.animationFrames)][];
                for (int f = 0; f < frames.Length; f++)
                    frames[f] = ReadMeshes(folder + (info.animationFrames > 0 ? "/animation_" + f.ToString("D3") + ".bytes" : "/geometry.bytes"), folder + "/Meshes/", f, materials.Length);
            }

            var scene = EditorSceneManager.NewPreviewScene();
            var root = new GameObject(key);
            SceneManager.MoveGameObjectToScene(root, scene);
            try
            {
                string marker = info.kind == "marine" ? MarineVesselWaveMotion.VisualChildName : info.kind == "buoy" ? BuoyWaveMotion.VisualChildName : "AerialModel_v1";
                var visual = new GameObject(marker).transform;
                visual.SetParent(root.transform, false);
                var filters = new List<MeshFilter>();
                for (int i = 0; i < frames[0].Length; i++)
                {
                    var batch = new GameObject("Source material " + i);
                    batch.transform.SetParent(visual, false);
                    var filter = batch.AddComponent<MeshFilter>();
                    filter.sharedMesh = frames[0][i];
                    filters.Add(filter);
                    batch.AddComponent<MeshRenderer>().sharedMaterial = materials[i];
                }

                if (frames.Length > 1)
                {
                    string clipPath = folder + "/mesh-animation.asset";
                    var clip = AssetDatabase.LoadAssetAtPath<DatasetMeshAnimationClip>(clipPath);
                    if (clip == null)
                    {
                        clip = ScriptableObject.CreateInstance<DatasetMeshAnimationClip>();
                        AssetDatabase.CreateAsset(clip, clipPath);
                    }

                    clip.durationSeconds = info.animationSeconds;
                    clip.provenance = key == "drone_amvlab" ? "procedural propeller cadence; not calibrated RPM" : "source animation baked to opaque meshes";
                    clip.frames = frames.Select(p => new DatasetMeshFrame { parts = p }).ToArray();
                    EditorUtility.SetDirty(clip);
                    var animation = root.AddComponent<DatasetMeshAnimation>();
                    animation.targets = filters.ToArray();
                    animation.clip = clip;
                }

                var body = root.AddComponent<Rigidbody>();
                body.isKinematic = true;
                body.useGravity = false;
                if (info.kind == "marine")
                {
                    var wave = root.AddComponent<MarineVesselWaveMotion>();
                    wave.visual = visual;
                    wave.parameters = new MarineVesselParameters
                    {
                        lengthM = info.lengthM,
                        beamM = info.beamM,
                        draftM = info.draftM,
                        blockCoefficient = .3f,
                        maxRollDeg = 24,
                        maxPitchDeg = 16
                    };
                    wave.parameters.Validate();
                    body.mass = wave.parameters.MassKg;
                    for (int i = 0; i < 3; i++)
                    {
                        var c = new GameObject("Hull collision " + i);
                        c.transform.SetParent(visual, false);
                        c.transform.localPosition = new Vector3((i - 1) * info.lengthM * .27f, -info.draftM * .4f, 0);
                        c.AddComponent<BoxCollider>().size = new Vector3(info.lengthM * .3f, info.draftM, info.beamM * (i == 2 ? .5f : .74f));
                    }
                }
                else
                {
                    var collider = visual.gameObject.AddComponent<BoxCollider>();
                    collider.center = info.kind == "buoy" ? new Vector3(0, info.heightM * .5f - info.draftM, 0) : Vector3.zero;
                    collider.size = new Vector3(info.lengthM, info.heightM, info.beamM);
                    body.mass = info.kind == "buoy" ? 150 : info.category == "bird" ? 1.1f : info.category == "drone" ? 1.4f : info.category == "helicopter" ? 10000 : key == "airplane_a320" ? 64000 : 800;
                    if (info.kind != "buoy")
                    {
                        var response = root.AddComponent<DatasetAerialResponse>();
                        response.visual = visual;
                        response.maxBankDeg = info.category == "drone" ? 5 : info.category == "bird" ? 5 : 2;
                        response.maxPitchDeg = 1;
                    }
                }

                AddLights(root, visual, info, folder);
                root.AddComponent<OpenBoatAssetCredit>().credit = new OpenBoatCredit
                {
                    model = key,
                    title = info.title,
                    author = info.author,
                    source = info.source,
                    license = info.license,
                    licenseUrl = info.licenseUrl,
                    sha256 = info.sha256,
                    changes = info.changes
                };
                if (PrefabUtility.SaveAsPrefabAsset(root, path) == null)
                    throw new IOException("Cannot save " + path);
                MarineOpenBoatsBuilder.Register(path, key);
            }
            finally
            {
                Object.DestroyImmediate(root);
                EditorSceneManager.ClosePreviewScene(scene);
            }
        }

        static Mesh SaveMesh(Mesh mesh, string path)
        {
            mesh.name = Path.GetFileNameWithoutExtension(path);
            mesh.RecalculateBounds();
            mesh.RecalculateTangents();
            MarineLibraryBuilder.CheckMesh(mesh);
            var prior = AssetDatabase.LoadAssetAtPath<Mesh>(path);
            if (prior == null)
            {
                AssetDatabase.CreateAsset(mesh, path);
                return mesh;
            }

            EditorUtility.CopySerialized(mesh, prior);
            Object.DestroyImmediate(mesh);
            EditorUtility.SetDirty(prior);
            return prior;
        }

        static Mesh[] ReadMeshes(string file, string folder, int frame, int expected)
        {
            using (var reader = new BinaryReader(File.OpenRead(file)))
            {
                if (reader.ReadUInt32() != 0x4C424D31 || reader.ReadInt32() != expected)
                    throw new InvalidDataException("Mesh/material header: " + file);
                var meshes = new Mesh[expected];
                for (int p = 0; p < expected; p++)
                {
                    int material = reader.ReadInt32(), n = reader.ReadInt32(), count = reader.ReadInt32();
                    if (material != p || n < 3 || n > 5000000 || count < 3 || count % 3 != 0 || count > 15000000)
                        throw new InvalidDataException("Mesh allocation: " + file);
                    var vertices = new Vector3[n];
                    var normals = new Vector3[n];
                    var uv = new Vector2[n];
                    for (int i = 0; i < n; i++)
                    {
                        vertices[i] = new Vector3(reader.ReadSingle(), reader.ReadSingle(), reader.ReadSingle());
                        normals[i] = new Vector3(reader.ReadSingle(), reader.ReadSingle(), reader.ReadSingle());
                        uv[i] = new Vector2(reader.ReadSingle(), reader.ReadSingle());
                    }

                    var triangles = new int[count];
                    for (int i = 0; i < count; i++)
                    {
                        triangles[i] = reader.ReadInt32();
                        if (triangles[i] < 0 || triangles[i] >= n)
                            throw new InvalidDataException("Triangle range");
                    }

                    meshes[p] = SaveMesh(new Mesh { indexFormat = IndexFormat.UInt32, vertices = vertices, normals = normals, uv = uv, triangles = triangles }, folder + "frame_" + frame.ToString("D3") + "_" + p + ".asset");
                }

                if (reader.BaseStream.Position != reader.BaseStream.Length)
                    throw new InvalidDataException("Trailing mesh data");
                return meshes;
            }
        }

        static Mesh[][] BakeBird(string folder, Info info)
        {
            string path = folder + "/Source/source.fbx";
            var importer = (ModelImporter)AssetImporter.GetAtPath(path);
            importer.animationType = ModelImporterAnimationType.Generic;
            importer.importAnimation = true;
            importer.isReadable = true;
            importer.SaveAndReimport();
            var clip = AssetDatabase.LoadAllAssetsAtPath(path).OfType<AnimationClip>().First(c => c.name == "WingFlap");
            var scene = EditorSceneManager.NewPreviewScene();
            var instance = Object.Instantiate(AssetDatabase.LoadAssetAtPath<GameObject>(path));
            SceneManager.MoveGameObjectToScene(instance, scene);
            try
            {
                var renderer = instance.GetComponentsInChildren<SkinnedMeshRenderer>().Single();
                int count = 24;
                var raw = new Mesh[count];
                var bounds = new Bounds();
                bool first = true;
                for (int f = 0; f < count; f++)
                {
                    clip.SampleAnimation(instance, clip.length * f / count);
                    var mesh = new Mesh
                    {
                        indexFormat = IndexFormat.UInt32
                    };
                    renderer.BakeMesh(mesh);
                    var v = mesh.vertices;
                    var normals = mesh.normals;
                    var matrix = renderer.transform.localToWorldMatrix;
                    var normalMatrix = matrix.inverse.transpose;
                    for (int i = 0; i < v.Length; i++)
                    {
                        v[i] = matrix.MultiplyPoint3x4(v[i]);
                        normals[i] = normalMatrix.MultiplyVector(normals[i]).normalized;
                        if (first)
                        {
                            bounds = new Bounds(v[i], Vector3.zero);
                            first = false;
                        }
                        else
                            bounds.Encapsulate(v[i]);
                    }

                    mesh.vertices = v;
                    mesh.normals = normals;
                    raw[f] = mesh;
                }

                // Source is upright in world coordinates, head +X, wings +/-Z.
                float scale = 1.45f / bounds.size.z;
                var center = bounds.center;
                var frames = new Mesh[count][];
                for (int f = 0; f < count; f++)
                {
                    var mesh = raw[f];
                    var vertices = mesh.vertices;
                    for (int i = 0; i < vertices.Length; i++)
                        vertices[i] = (vertices[i] - center) * scale;
                    mesh.vertices = vertices;
                    frames[f] = new[]
                    {
                        SaveMesh(mesh, folder + "/Meshes/frame_" + f.ToString("D3") + "_0.asset")
                    };
                }

                info.lengthM = bounds.size.x * scale;
                info.beamM = 1.45f;
                info.heightM = bounds.size.y * scale;
                info.animationFrames = count;
                info.animationSeconds = clip.length;
                info.vertices = frames[0][0].vertexCount;
                info.triangles = frames[0][0].triangles.Length / 3;
                info.maxTextureSize = 1024;
                // Preserve the full provenance JSON (including mirror commit/hash).
                string json = File.ReadAllText(folder + "/model-info.json");
                json = System.Text.RegularExpressions.Regex.Replace(json, "\"(lengthM|beamM|heightM|animationSeconds|vertices|triangles|maxTextureSize)\"\\s*:\\s*[0-9.eE+-]+", m => "\"" + m.Groups[1].Value + "\": " + (m.Groups[1].Value == "lengthM" ? info.lengthM : m.Groups[1].Value == "beamM" ? info.beamM : m.Groups[1].Value == "heightM" ? info.heightM : m.Groups[1].Value == "animationSeconds" ? info.animationSeconds : m.Groups[1].Value == "vertices" ? info.vertices : m.Groups[1].Value == "triangles" ? info.triangles : info.maxTextureSize).ToString("R", System.Globalization.CultureInfo.InvariantCulture));
                File.WriteAllText(folder + "/model-info.json", json);
                WriteGeometry(folder + "/geometry.bytes", frames[0]);
                return frames;
            }
            finally
            {
                Object.DestroyImmediate(instance);
                EditorSceneManager.ClosePreviewScene(scene);
            }
        }

        static Material BirdMaterial(string folder)
        {
            var data = new MarineOpenBoatsBuilder.MaterialInfo
            {
                name = "White seabird feathers",
                color = new[]
                {
                    1f,
                    1f,
                    1f,
                    1f
                },
                metallic = 0,
                smoothness = .2f,
                baseMap = "Seagull-Base_Color.png",
                emission = new[]
                {
                    0f,
                    0f,
                    0f
                },
                doubleSided = true
            };
            return MarineOpenBoatsBuilder.Material(folder, data, 0);
        }

        static void WriteGeometry(string path, Mesh[] parts)
        {
            using (var writer = new BinaryWriter(File.Create(path)))
            {
                writer.Write(0x4C424D31u);
                writer.Write(parts.Length);
                for (int p = 0; p < parts.Length; p++)
                {
                    var m = parts[p];
                    writer.Write(p);
                    writer.Write(m.vertexCount);
                    writer.Write(m.triangles.Length);
                    var v = m.vertices;
                    var n = m.normals;
                    var uv = m.uv;
                    for (int i = 0; i < v.Length; i++)
                    {
                        writer.Write(v[i].x);
                        writer.Write(v[i].y);
                        writer.Write(v[i].z);
                        writer.Write(n[i].x);
                        writer.Write(n[i].y);
                        writer.Write(n[i].z);
                        writer.Write(uv[i].x);
                        writer.Write(uv[i].y);
                    }

                    foreach (var index in m.triangles)
                        writer.Write(index);
                }
            }
        }

        static void AddLights(GameObject root, Transform visual, Info info, string folder)
        {
            if (info.kind == "bird")
                return;
            var lamps = new List<DatasetAssetLight>();
            if (info.kind == "buoy")
            {
                // Existing campaign lantern controls this lens, including its
                // restrained point-light intensity and exported flash state.
                Lens(visual, "AmberFresnelLens", new Vector3(0, info.heightM - info.draftM + .03f, 0), .055f, new Color(1, .45f, .06f), folder);
                root.AddComponent<DatasetBuoyAutoSetup>();
                return;
            }

            float length = info.lengthM, beam = info.beamM, radius = info.category == "drone" ? .009f : Mathf.Clamp(length * .004f, .025f, .12f);
            float y = info.kind == "marine" ? info.heightM * .4f : 0;
            Action<string, Vector3, Color, float, float> add = (role, position, color, period, on) =>
            {
                var renderer = Lens(visual, role, position, radius, color, folder);
                var point = renderer.gameObject.AddComponent<Light>();
                point.type = LightType.Point;
                point.color = color;
                point.range = info.category == "drone" ? .4f : 2;
                point.shadows = LightShadows.None;
                point.gameObject.AddComponent<HDAdditionalLightData>().SetIntensity(.6f, LightUnit.Lumen);
                lamps.Add(new DatasetAssetLight { role = role, lens = renderer, point = point, color = color, periodSeconds = period, flashSeconds = on, peakEmission = 8, lumens = .6f });
            };
            add("red_port", new Vector3(length * .05f, y, beam * .46f), new Color(1, .015f, .01f), 0, 0);
            add("green_starboard", new Vector3(length * .05f, y, -beam * .46f), new Color(.01f, 1, .03f), 0, 0);
            add("white_tail", new Vector3(-length * .47f, y, 0), Color.white, 0, 0);
            if (info.kind == "aircraft")
                add("red_beacon", new Vector3(-length * .12f, info.heightM * .48f, 0), Color.red, 1.4f, .14f);
            root.AddComponent<DatasetAssetLights>().lamps = lamps.ToArray();
        }

        static MeshRenderer Lens(Transform visual, string name, Vector3 position, float radius, Color color, string folder)
        {
            string path = folder + "/light_" + name + ".mat";
            var material = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (material == null)
            {
                material = new Material(Shader.Find("HDRP/Lit"));
                AssetDatabase.CreateAsset(material, path);
            }

            material.SetColor("_BaseColor", color);
            material.SetColor("_EmissiveColor", Color.black);
            material.SetFloat("_SurfaceType", 0);
            material.SetFloat("_Smoothness", .65f);
            HDMaterial.ValidateMaterial(material);
            EditorUtility.SetDirty(material);
            var lens = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            lens.name = name;
            lens.transform.SetParent(visual, false);
            lens.transform.localPosition = position;
            lens.transform.localScale = Vector3.one * (radius * 2);
            Object.DestroyImmediate(lens.GetComponent<Collider>());
            var r = lens.GetComponent<MeshRenderer>();
            r.sharedMaterial = material;
            return r;
        }

        [MenuItem("LOTUSim/Models/External objects CC-BY/2 - Enable variants in connected dataset")]
        public static void EnableVariants()
        {
            if (EditorApplication.isPlayingOrWillChangePlaymode)
                throw new InvalidOperationException("Quit Play first.");
            var config = AssetDatabase.LoadAssetAtPath<DatasetSequenceConfig>(DatasetLotusimSceneBuilder.ConfigPath);
            Undo.RecordObject(config, "Enable external object variants");
            ConfigureVariants(config);
            EditorUtility.SetDirty(config);
            AssetDatabase.SaveAssets();
            DatasetLotusimSceneBuilder.ExportScenario();
        }

        public static void ConfigureVariants(DatasetSequenceConfig config)
        {
            foreach (var c in config.classes)
            {
                var added = DatasetExternalAssetCatalog.Models.Where((n, i) => DatasetExternalAssetCatalog.Categories[i] == c.category).Select(n => AssetDatabase.LoadAssetAtPath<GameObject>("Assets/Prefabs/" + n + ".prefab")).ToArray();
                if (added.Any(p => p == null))
                    throw new FileNotFoundException("Build all eight external objects first.");
                c.prefabVariants = (c.prefabVariants ?? Array.Empty<GameObject>()).Concat(added).Distinct().ToArray();
            }

            config.Validate();
        }

        [MenuItem("LOTUSim/Models/External objects CC-BY/Validate audited prefabs")]
        public static void Validate()
        {
            foreach (var key in DatasetExternalAssetCatalog.Models)
            {
                var root = AssetDatabase.LoadAssetAtPath<GameObject>("Assets/Prefabs/" + key + ".prefab");
                if (root == null || root.GetComponent<OpenBoatAssetCredit>()?.credit.license != "CC-BY-4.0" || root.GetComponent<Rigidbody>()?.isKinematic != true)
                    throw new Exception("Incomplete physics/credits: " + key);
                foreach (var r in root.GetComponentsInChildren<MeshRenderer>())
                {
                    MarineLibraryBuilder.CheckMesh(r.GetComponent<MeshFilter>().sharedMesh);
                    if (r.sharedMaterial.GetFloat("_SurfaceType") != 0 || r.sharedMaterial.GetFloat("_AlphaCutoffEnable") != 0)
                        throw new Exception("Non-opaque model: " + key);
                }

                if (root.GetComponentsInChildren<SkinnedMeshRenderer>().Length > 0 || root.GetComponentsInChildren<Camera>().Length > 0)
                    throw new Exception("Source scene components leaked: " + key);
                Debug.Log("[Open Objects] PASS " + key + " opaque meshes, colliders, kinematic root, credits");
            }
        }

        [MenuItem("LOTUSim/Models/External objects CC-BY/3 - Open inspection scene")]
        public static void Open()
        {
            if (EditorApplication.isPlayingOrWillChangePlaymode)
                throw new InvalidOperationException("Quit Play first.");
            if (!EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo())
                return;
            CreateShowcase();
            EditorSceneManager.OpenScene(Scene);
        }

        static void CreateShowcase()
        {
            if (File.Exists(Scene))
                return;
            MarineLibraryBuilder.CreateShowcase();
            var prior = SceneManager.GetActiveScene();
            var scene = EditorSceneManager.OpenScene(MarineLibraryBuilder.ShowcaseScene, OpenSceneMode.Additive);
            try
            {
                var old = scene.GetRootGameObjects().SelectMany(r => r.GetComponentsInChildren<MarineLibraryShowcase>()).Single();
                var host = old.gameObject.AddComponent<DatasetAssetShowcase>();
                host.prefabs = DatasetExternalAssetCatalog.Models.Select(n => AssetDatabase.LoadAssetAtPath<GameObject>("Assets/Prefabs/" + n + ".prefab")).ToArray();
                host.viewCamera = old.viewCamera;
                host.ocean = old.ocean;
                host.sun = old.sun;
                host.environment = old.environment;
                host.waterPipeline = old.waterPipeline;
                Object.DestroyImmediate(old);
                if (!EditorSceneManager.SaveScene(scene, Scene, true))
                    throw new IOException("Cannot save external-object showcase");
            }
            finally
            {
                EditorSceneManager.CloseScene(scene, true);
                if (prior.IsValid() && prior.isLoaded)
                    SceneManager.SetActiveScene(prior);
            }
        }
    }
}
