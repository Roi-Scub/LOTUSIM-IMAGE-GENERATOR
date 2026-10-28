using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Lotusim.Dataset;
using UnityEditor;
using UnityEditor.AddressableAssets;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.SceneManagement;
using Object = UnityEngine.Object;

namespace Lotusim.EditorTools
{
    public static class DatasetDashboardMeshBuilder
    {
        public const string RegistryPath = "Assets/Resources/DatasetImportedAssets.json";
        public static string PrefabPath(string model) => "Assets/Prefabs/" + model + ".prefab";
        public static DashboardMeshResult Build(DashboardMeshRequest request, string importDirectory, string requestSha256)
        {
            if (EditorApplication.isPlayingOrWillChangePlaymode || EditorApplication.isCompiling || EditorApplication.isUpdating)
                throw new InvalidOperationException("Wait until Unity is idle outside Play.");
            DatasetDashboardImportContract.Validate(request, Path.GetFileName(importDirectory));
            if (!DatasetImportedAssetRegistry.Hex(requestSha256, 64))
                throw new InvalidDataException("Invalid request digest.");
            string bundle = DatasetDashboardImportContract.SafeChild(importDirectory, request.bundleDirectory);
            DatasetDashboardImportContract.VerifyBundle(request, bundle);
            string prefabPath = PrefabPath(request.model);
            var old = AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath);
            if (File.Exists(prefabPath) && (old == null || old.GetComponent<DatasetImportedAsset>()?.importId != request.id))
                throw new IOException("An unrelated prefab already owns this model path.");
            var addressables = AddressableAssetSettingsDefaultObject.Settings;
            string priorGuid = AssetDatabase.AssetPathToGUID(prefabPath);
            if (addressables != null && addressables.groups.Where(g => g != null).SelectMany(g => g.entries).Any(e => e.address == request.model && e.guid != priorGuid))
                throw new InvalidOperationException("An unrelated Addressable already owns this model key.");
            var info = JsonUtility.FromJson<DashboardMeshInfo>(File.ReadAllText(Path.Combine(bundle, request.infoFile)));
            ValidateInfo(request, info);
            // Every attempt owns a fresh immutable asset folder. Never rewrite
            // source assets, existing materials, or a user's edited mesh asset.
            string folder = "Assets/models/dashboard_imports/" + request.model + "/" + requestSha256.Substring(0, 16) + "_" + Guid.NewGuid().ToString("N").Substring(0, 8);
            MarineOpenBoatsBuilder.Folder(folder);
            foreach (var entry in request.files)
            {
                // Hash-check the entire cross-engine inventory above, but do
                // not feed Gazebo OBJ/MTL sidecars to Unity's native importer.
                if (!DatasetDashboardImportContract.CopyToUnity(request, entry))
                    continue;
                string destination = DatasetDashboardImportContract.SafeChild(Path.GetFullPath(folder), entry.path);
                Directory.CreateDirectory(Path.GetDirectoryName(destination));
                File.Copy(DatasetDashboardImportContract.SafeChild(bundle, entry.path), destination, false);
                if (DatasetDashboardImportContract.FileHash(destination) != entry.sha256)
                    throw new InvalidDataException("Prepared file changed while copying into Unity.");
            }

            AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
            var materials = info.materials.Select((material, index) => MarineOpenBoatsBuilder.Material(folder, material, index)).ToArray();
            MarineOpenBoatsBuilder.Folder(folder + "/Meshes");
            var scene = EditorSceneManager.NewPreviewScene();
            var root = new GameObject(request.model);
            SceneManager.MoveGameObjectToScene(root, scene);
            try
            {
                var visual = new GameObject(request.domain == "sea" ? MarineVesselWaveMotion.VisualChildName : request.domain == "moored" ? BuoyWaveMotion.VisualChildName : "AerialModel_v1").transform;
                visual.SetParent(root.transform, false);
                Bounds bounds = ReadGeometry(Path.Combine(folder, request.geometryFile), folder, visual, materials, request.model);
                var d = request.dimensions;
                if (!Close(bounds.size.x, d.lengthM) || !Close(bounds.size.y, d.heightM) || !Close(bounds.size.z, d.beamM))
                    throw new InvalidDataException("Prepared mesh bounds differ from the declared normalized dimensions.");
                var collider = visual.gameObject.AddComponent<BoxCollider>();
                collider.center = bounds.center;
                collider.size = new Vector3(Mathf.Max(.001f, bounds.size.x), Mathf.Max(.001f, bounds.size.y), Mathf.Max(.001f, bounds.size.z));
                var body = root.AddComponent<Rigidbody>();
                body.useGravity = false;
                body.isKinematic = true;
                bool waveResponse = request.domain == "sea" && DatasetDashboardImportContract.SupportsMarineWaveProxy(d);
                if (waveResponse)
                {
                    var wave = root.AddComponent<MarineVesselWaveMotion>();
                    wave.visual = visual;
                    wave.parameters = new MarineVesselParameters
                    {
                        lengthM = d.lengthM,
                        beamM = d.beamM,
                        draftM = Mathf.Max(.05f, d.draftM),
                        blockCoefficient = .4f,
                        maxRollDeg = 20,
                        maxPitchDeg = 12
                    };
                    wave.parameters.Validate();
                    body.mass = wave.parameters.MassKg;
                }
                else if (request.domain == "air")
                {
                    root.AddComponent<DatasetAerialResponse>().visual = visual;
                    // An uploaded shape does not prove navigation-light anchors.
                    // Empty authored-light state prevents the legacy hardcoded
                    // aircraft helper from inventing or demanding source lamps.
                }

                if (request.domain != "moored")
                    root.AddComponent<DatasetAssetLights>();
                var marker = root.AddComponent<DatasetImportedAsset>();
                marker.importId = request.id;
                marker.model = request.model;
                marker.requestSha256 = requestSha256;
                marker.revisionSha256 = request.revisionSha256;
                marker.category = request.category;
                marker.domain = request.domain;
                marker.classId = request.classId;
                marker.lengthM = d.lengthM;
                marker.beamM = d.beamM;
                marker.heightM = d.heightM;
                marker.draftM = d.draftM;
                marker.maxSpeedMps = request.profile.maxSpeedMps;
                marker.maxAltitudeM = request.profile.maxAltitudeM;
                marker.visualWaveResponse = waveResponse;
                marker.visualDraftProxyM = waveResponse ? Mathf.Max(.05f, d.draftM) : 0;
                root.AddComponent<OpenBoatAssetCredit>().credit = new OpenBoatCredit
                {
                    model = request.model,
                    title = request.label,
                    author = info.author,
                    source = request.sourceUrl,
                    license = request.license,
                    licenseUrl = info.licenseUrl,
                    sha256 = request.revisionSha256,
                    changes = (info.changes ?? Array.Empty<string>()).Concat(new[] { "Local dashboard import; static baked meshes; source scripts/animations are never imported", "Attribution sha256 identifies this prepared revision; original per-file digests remain in the local import receipt", "Opaque HDRP materials and bounding-box collision; visual wave response is approximate, not validated hydrodynamics", "No navigation lamps invented from an unknown source; ROS retains root trajectory ownership", request.domain != "sea" ? "No marine hydrostatic-response parameters claimed for this object" : !waveResponse ? "Marine visual wave response skipped: measured length/beam are outside this approximate response model's supported range; collider and kinematic pose remain available" : d.draftM < .05f ? "Tirant d’eau de réponse visuelle minimal .05 m; non calibré. Declared draft and geometry are unchanged; this proxy is not a measured physical draft or mass" : "Marine visual response uses declared dimensions; hydrostatic mass/response remains an uncalibrated approximation" }).ToArray()
                };
                if (PrefabUtility.SaveAsPrefabAsset(root, prefabPath) == null)
                    throw new IOException("Cannot save the generated prefab.");
                MarineOpenBoatsBuilder.Register(prefabPath, request.model);
                AssetDatabase.SaveAssets();
                var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath);
                if (prefab == null || prefab.GetComponent<DatasetImportedAsset>()?.requestSha256 != requestSha256 || prefab.GetComponentsInChildren<MeshRenderer>(true).Length == 0)
                    throw new InvalidDataException("Unity did not retain the imported prefab.");
                string guid = AssetDatabase.AssetPathToGUID(prefabPath);
                if (!DatasetImportedAssetRegistry.Hex(guid, 32) || AddressableAssetSettingsDefaultObject.Settings?.FindAssetEntry(guid)?.address != request.model)
                    throw new InvalidDataException("Addressable registration is incomplete.");
                PublishRegistry(prefabPath, prefab.GetComponent<DatasetImportedAsset>(), guid);
                AssetDatabase.SaveAssets();
                return DatasetDashboardImportContract.ReadyResult(request, requestSha256, guid, DatasetDashboardImportContract.FileHash(prefabPath), request.files.Single(f => f.path == request.geometryFile).sha256, Path.GetFullPath(Path.Combine(Application.dataPath, "..")));
            }
            finally
            {
                Object.DestroyImmediate(root);
                EditorSceneManager.ClosePreviewScene(scene);
            }
        }

        static bool Close(float actual, float expected) => Mathf.Abs(actual - expected) <= Mathf.Max(.005f, expected * .001f);
        static void ValidateInfo(DashboardMeshRequest request, DashboardMeshInfo info)
        {
            if (info == null || info.key != request.model || info.category != request.category || info.license != request.license || info.materials == null || info.materials.Length < 1 || info.materials.Length > 200)
                throw new InvalidDataException("Prepared material metadata does not match its request.");
            foreach (var material in info.materials)
            {
                if (material == null || material.color?.Length != 4 || material.emission?.Length != 3 || material.color.Any(v => !DatasetDashboardImportContract.Range(v, 0, 1)) || material.emission.Any(v => !DatasetDashboardImportContract.Range(v, 0, 100000)) || !DatasetDashboardImportContract.Range(material.metallic, 0, 1) || !DatasetDashboardImportContract.Range(material.smoothness, 0, 1) || !DatasetDashboardImportContract.Range(material.normalScale, 0, 10) || !DatasetDashboardImportContract.Range(material.coat, 0, 1))
                    throw new InvalidDataException("Prepared material values are invalid.");
                foreach (string texture in new[]
                {
                    material.baseMap,
                    material.normalMap,
                    material.maskMap,
                    material.emissionMap
                }

                )
                    if (!string.IsNullOrEmpty(texture) && !request.files.Any(f => f.path == texture && (f.path.EndsWith(".png", StringComparison.OrdinalIgnoreCase) || f.path.EndsWith(".jpg", StringComparison.OrdinalIgnoreCase) || f.path.EndsWith(".jpeg", StringComparison.OrdinalIgnoreCase))))
                        throw new InvalidDataException("A prepared material references an undeclared texture.");
            }
        }

        static Bounds ReadGeometry(string source, string folder, Transform visual, Material[] materials, string model)
        {
            var bounds = new Bounds();
            bool first = true;
            long totalVertices = 0, totalIndices = 0;
            using (var file = new BinaryReader(File.OpenRead(source)))
            {
                if (file.ReadUInt32() != 0x4C424D31)
                    throw new InvalidDataException("Unsupported prepared mesh header.");
                int parts = file.ReadInt32();
                if (parts < 1 || parts > 200)
                    throw new InvalidDataException("Prepared mesh batch limit exceeded.");
                for (int part = 0; part < parts; part++)
                {
                    int material = file.ReadInt32(), count = file.ReadInt32(), indexCount = file.ReadInt32();
                    if (material < 0 || material >= materials.Length || count < 3 || count > 2000000 || indexCount < 3 || indexCount % 3 != 0 || indexCount > 6000000 || (totalVertices += count) > 2000000 || (totalIndices += indexCount) > 6000000 || 32L * count + 4L * indexCount > file.BaseStream.Length - file.BaseStream.Position)
                        throw new InvalidDataException("Invalid prepared mesh allocation.");
                    var vertices = new Vector3[count];
                    var normals = new Vector3[count];
                    var uv = new Vector2[count];
                    for (int i = 0; i < count; i++)
                    {
                        vertices[i] = new Vector3(file.ReadSingle(), file.ReadSingle(), file.ReadSingle());
                        normals[i] = new Vector3(file.ReadSingle(), file.ReadSingle(), file.ReadSingle());
                        uv[i] = new Vector2(file.ReadSingle(), file.ReadSingle());
                        if (!Finite(vertices[i]) || !Finite(normals[i]) || !DatasetDashboardImportContract.Range(uv[i].x, -1000000, 1000000) || !DatasetDashboardImportContract.Range(uv[i].y, -1000000, 1000000) || normals[i].sqrMagnitude < .000001f || normals[i].sqrMagnitude > 4)
                            throw new InvalidDataException("Non-finite prepared vertex/normal/UV.");
                    }

                    var triangles = new int[indexCount];
                    for (int i = 0; i < indexCount; i++)
                    {
                        triangles[i] = file.ReadInt32();
                        if (triangles[i] < 0 || triangles[i] >= count)
                            throw new InvalidDataException("Prepared index is outside its mesh.");
                    }

                    var mesh = new Mesh
                    {
                        name = model + "_" + part,
                        indexFormat = IndexFormat.UInt32,
                        vertices = vertices,
                        normals = normals,
                        uv = uv,
                        triangles = triangles
                    };
                    mesh.RecalculateBounds();
                    mesh.RecalculateTangents();
                    AssetDatabase.CreateAsset(mesh, folder + "/Meshes/batch_" + part.ToString("D4") + ".asset");
                    var batch = new GameObject("Source material " + part);
                    batch.transform.SetParent(visual, false);
                    batch.AddComponent<MeshFilter>().sharedMesh = mesh;
                    batch.AddComponent<MeshRenderer>().sharedMaterial = materials[material];
                    if (first)
                    {
                        bounds = mesh.bounds;
                        first = false;
                    }
                    else
                        bounds.Encapsulate(mesh.bounds);
                }

                if (file.BaseStream.Position != file.BaseStream.Length)
                    throw new InvalidDataException("Trailing prepared mesh data.");
            }

            return bounds;
        }

        static bool Finite(Vector3 v) => DatasetDashboardImportContract.Range(v.x, -1000000, 1000000) && DatasetDashboardImportContract.Range(v.y, -1000000, 1000000) && DatasetDashboardImportContract.Range(v.z, -1000000, 1000000);
        static void PublishRegistry(string path, DatasetImportedAsset marker, string guid)
        {
            DatasetDashboardImportContract.NoLinks(Path.GetFullPath(RegistryPath));
            var registry = File.Exists(RegistryPath) ? JsonUtility.FromJson<DatasetImportedAssetRegistry.Manifest>(File.ReadAllText(RegistryPath)) : new DatasetImportedAssetRegistry.Manifest();
            if (registry?.schema != "lotusim-unity-imported-registry-1" || registry.assets == null)
                throw new InvalidDataException("An unrelated Resources registry already exists.");
            var entries = new List<DatasetImportedAssetRegistry.Entry>();
            foreach (var item in registry.assets)
            {
                if (item == null || item.model == marker.model || !DatasetImportedAssetRegistry.ModelKey(item.model) || item.prefabPath != PrefabPath(item.model))
                    continue;
                var prior = AssetDatabase.LoadAssetAtPath<GameObject>(item.prefabPath)?.GetComponent<DatasetImportedAsset>();
                if (prior != null && prior.model == item.model && prior.category == item.category && prior.importId == item.importId && prior.requestSha256 == item.requestSha256 && prior.revisionSha256 == item.revisionSha256 && AssetDatabase.AssetPathToGUID(item.prefabPath) == item.prefabGuid)
                    entries.Add(item);
            }

            entries.Add(new DatasetImportedAssetRegistry.Entry { model = marker.model, category = marker.category, classId = marker.classId, importId = marker.importId, requestSha256 = marker.requestSha256, revisionSha256 = marker.revisionSha256, prefabPath = path, prefabGuid = guid });
            registry.assets = entries.OrderBy(e => e.model, StringComparer.Ordinal).ToArray();
            MarineOpenBoatsBuilder.Folder("Assets/Resources");
            string temporary = RegistryPath + ".pending-" + Guid.NewGuid().ToString("N");
            try
            {
                File.WriteAllText(temporary, JsonUtility.ToJson(registry, true));
                if (File.Exists(RegistryPath))
                    File.Replace(temporary, RegistryPath, null);
                else
                    File.Move(temporary, RegistryPath);
            }
            finally
            {
                if (File.Exists(temporary))
                    File.Delete(temporary);
            }

            AssetDatabase.ImportAsset(RegistryPath, ImportAssetOptions.ForceSynchronousImport);
        }
    }
}
