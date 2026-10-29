// Original, procedural visual assets for LOTUSim. Editor-only; no flight simulation.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.AddressableAssets;
using UnityEditor.AddressableAssets.Settings;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;
using UnityEngine.SceneManagement;
using Object = UnityEngine.Object;

namespace Lotusim.EditorTools
{
    [InitializeOnLoad]
    public static partial class AerialLibraryBuilder
    {
        const string LibraryPath = "Assets/models/aerial_library";
        const string Marker = "AerialModel_v1";
        static readonly string[] Names =
        {
            "small_drone",
            "helicopter",
            "airplane",
            "seagull"
        };
        static string meshDirectory;
        static bool attempted;
        static readonly Dictionary<string, Material> Palette = new Dictionary<string, Material>();
        static AerialLibraryBuilder()
        {
            EditorApplication.update += EnsureLibrary;
        }

        static void EnsureLibrary()
        {
            if (attempted || EditorApplication.isCompiling || EditorApplication.isUpdating || EditorApplication.isPlayingOrWillChangePlaymode)
                return;
            attempted = true;
            EditorApplication.update -= EnsureLibrary;
            if (Names.All(name =>
            {
                var asset = AssetDatabase.LoadAssetAtPath<GameObject>("Assets/Prefabs/" + name + ".prefab");
                return asset != null && asset.transform.Find(Marker) != null;
            }))
                return;
            try
            {
                BuildAll();
            }
            catch (Exception exception)
            {
                Debug.LogException(exception);
            }
        }

        [MenuItem("LOTUSim/Models/Build aerial library")]
        public static void BuildAll()
        {
            if (EditorApplication.isPlayingOrWillChangePlaymode)
                throw new InvalidOperationException("Stop Play before creating visual assets.");
            if (Shader.Find("HDRP/Lit") == null)
                throw new InvalidOperationException("HDRP/Lit is required.");
            int geometryChecks = CheckGeometryRegression();
            Debug.Log("[AerialLibrary] Geometry regression checks passed: " + geometryChecks);
            CheckAddresses();
            Folder("Assets/Prefabs");
            Folder(LibraryPath + "/Materials");
            Folder(LibraryPath + "/Textures");
            CreatePalette();
            for (int i = 0; i < Names.Length; i++)
                BuildOne(Names[i], i + 2);
            AssetDatabase.SaveAssets();
            Debug.Log("[AerialLibrary] READY: small_drone, helicopter, airplane, seagull. HDRP prefabs and matching LOTUSim visual models.");
        }

        static void BuildOne(string name, int classId)
        {
            meshDirectory = LibraryPath + "/" + name + "/Meshes";
            Folder(meshDirectory);
            string path = "Assets/Prefabs/" + name + ".prefab";
            bool existing = File.Exists(path);
            var root = existing ? PrefabUtility.LoadPrefabContents(path) : new GameObject(name);
            Scene previewScene = default(Scene);
            if (!existing)
            {
                previewScene = EditorSceneManager.NewPreviewScene();
                SceneManager.MoveGameObjectToScene(root, previewScene);
            }

            try
            {
                var old = root.transform.Find(Marker);
                if (old != null)
                    Object.DestroyImmediate(old.gameObject);
                var visual = new GameObject(Marker);
                visual.transform.SetParent(root.transform, false);
                // Geometry is authored with nose +Z; LOTUSim's existing pose adapter requires nose +X.
                visual.transform.localRotation = Quaternion.Euler(0, 90, 0);
                if (name == "small_drone")
                    BuildDrone(visual.transform);
                else if (name == "helicopter")
                    BuildHelicopter(visual.transform);
                else if (name == "airplane")
                    BuildAirplane(visual.transform);
                else
                    BuildSeagull(visual.transform);
                CombineMaterials(visual.transform);
                Validate(root, name);
                var prefab = PrefabUtility.SaveAsPrefabAsset(root, path);
                if (prefab == null)
                    throw new InvalidOperationException("Could not save " + path);
                RegisterAddress(path, name);
                WriteMetadata(prefab, name, classId);
                ExportLotusim(prefab, name, classId);
                QueuePreview(prefab, name);
                Debug.Log("[AerialLibrary] Saved " + path + "; Addressables=" + name);
            }
            finally
            {
                if (existing)
                    PrefabUtility.UnloadPrefabContents(root);
                else
                {
                    Object.DestroyImmediate(root);
                    if (previewScene.IsValid())
                        EditorSceneManager.ClosePreviewScene(previewScene);
                }
            }
        }

        static Material M(string name) => Palette[name];
        static void CreatePalette()
        {
            Palette.Clear();
            var paint = MicroTextures("Paint", false);
            var feathers = MicroTextures("Feathers", true);
            MakeMaterial("AirframeWhite", new Color(.82f, .83f, .81f), .05f, .52f, paint);
            MakeMaterial("RescueOrange", new Color(.93f, .19f, .025f), .06f, .50f, paint);
            MakeMaterial("AircraftBlue", new Color(.025f, .13f, .30f), .15f, .58f, paint);
            MakeMaterial("PolymerGrey", new Color(.36f, .39f, .40f), .04f, .39f, paint);
            MakeMaterial("BlackPlastic", new Color(.023f, .028f, .035f), .03f, .35f, paint);
            MakeMaterial("Rubber", new Color(.009f, .013f, .017f), 0, .24f, null);
            MakeMaterial("BrushedMetal", new Color(.42f, .45f, .48f), .86f, .53f, paint);
            MakeMaterial("DarkMetal", new Color(.068f, .082f, .098f), .78f, .50f, paint);
            MakeMaterial("TintedGlazing", new Color(.012f, .030f, .046f), .22f, .96f, null);
            MakeMaterial("RotorCarbon", new Color(.062f, .068f, .075f), .22f, .43f, paint);
            var carbon = CarbonTexture();
            M("RotorCarbon").SetTexture("_BaseColorMap", carbon);
            HDMaterial.ValidateMaterial(M("RotorCarbon"));
            EditorUtility.SetDirty(M("RotorCarbon"));
            MakeMaterial("SafetyYellow", new Color(.90f, .61f, .035f), .04f, .48f, paint);
            MakeMaterial("BirdWhite", new Color(.82f, .82f, .78f), 0, .20f, feathers);
            MakeMaterial("BirdGrey", new Color(.33f, .38f, .42f), 0, .20f, feathers);
            MakeMaterial("BirdBlack", new Color(.015f, .019f, .026f), 0, .21f, feathers);
            MakeMaterial("BirdBill", new Color(.93f, .56f, .055f), 0, .34f, null);
            MakeMaterial("BirdEye", new Color(.003f, .004f, .006f), 0, .97f, null);
            MakeMaterial("BillMark", new Color(.48f, .032f, .012f), 0, .32f, null);
            MakeMaterial("NavRed", new Color(.42f, .006f, .009f), .05f, .83f, null);
            MakeMaterial("NavGreen", new Color(.006f, .31f, .028f), .05f, .83f, null);
            M("NavRed").SetColor("_EmissiveColor", new Color(1, .005f, .01f) * 1.5f);
            M("NavGreen").SetColor("_EmissiveColor", new Color(.01f, 1, .03f) * 1.5f);
            foreach (var mat in Palette.Values)
            {
                HDMaterial.ValidateMaterial(mat);
                EditorUtility.SetDirty(mat);
            }
        }

        static void MakeMaterial(string name, Color color, float metallic, float smoothness, Texture2D[] maps)
        {
            string path = LibraryPath + "/Materials/" + name + ".mat";
            var material = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (material == null)
            {
                material = new Material(Shader.Find("HDRP/Lit"))
                {
                    name = name
                };
                AssetDatabase.CreateAsset(material, path);
            }

            material.SetColor("_BaseColor", color);
            material.SetFloat("_Metallic", metallic);
            material.SetFloat("_Smoothness", smoothness);
            material.SetFloat("_SurfaceType", 0);
            material.SetFloat("_AlphaCutoffEnable", 0);
            material.enableInstancing = true;
            if (maps != null)
            {
                material.SetTexture("_BaseColorMap", maps[0]);
                material.SetTexture("_NormalMap", maps[1]);
                material.SetFloat("_NormalScale", name.StartsWith("Bird") ? .23f : .12f);
            }

            HDMaterial.ValidateMaterial(material);
            EditorUtility.SetDirty(material);
            Palette.Add(name, material);
        }

        static Texture2D[] MicroTextures(string kind, bool feather)
        {
            const int size = 512;
            var colors = new Color32[size * size];
            var normals = new Color32[colors.Length];
            var heights = new float[colors.Length];
            for (int y = 0; y < size; y++)
                for (int x = 0; x < size; x++)
                {
                    float grain = Mathf.PerlinNoise(17 + x * .16f, 23 + y * .16f);
                    float height = grain * .065f;
                    if (feather)
                    {
                        float u = (float)x / size, v = (float)y / size;
                        float shaft = Mathf.Exp(-Mathf.Pow((Mathf.Repeat(u, .125f) - .0625f) * 180, 2));
                        float barbs = Mathf.Sin((v + Mathf.Abs(Mathf.Repeat(u, .125f) - .0625f) * .8f) * Mathf.PI * 220);
                        height += shaft * .035f + barbs * .015f;
                    }

                    float shade = feather ? .93f + height * .45f : .97f + grain * .025f;
                    int index = y * size + x;
                    colors[index] = new Color(shade, shade, shade, 1);
                    heights[index] = height;
                }

            for (int y = 0; y < size; y++)
                for (int x = 0; x < size; x++)
                {
                    float dx = heights[y * size + (x + size - 1) % size] - heights[y * size + (x + 1) % size];
                    float dy = heights[((y + size - 1) % size) * size + x] - heights[((y + 1) % size) * size + x];
                    var n = new Vector3(dx * 2, dy * 2, 1).normalized;
                    normals[y * size + x] = new Color(n.x * .5f + .5f, n.y * .5f + .5f, n.z * .5f + .5f, 1);
                }

            return new[]
            {
                Texture(kind + "_Base", colors, size, false),
                Texture(kind + "_Normal", normals, size, true)
            };
        }

        static Texture2D CarbonTexture()
        {
            const int size = 256;
            var pixels = new Color32[size * size];
            for (int y = 0; y < size; y++)
                for (int x = 0; x < size; x++)
                {
                    bool across = ((x / 12) + (y / 12)) % 2 == 0;
                    float stripe = across ? Mathf.Sin(x * .8f) : Mathf.Sin(y * .8f);
                    float value = .53f + stripe * .12f;
                    pixels[y * size + x] = new Color(value, value, value, 1);
                }

            return Texture("CarbonWeave_Base", pixels, size, false);
        }

        static Texture2D Texture(string name, Color32[] pixels, int size, bool normal)
        {
            string path = LibraryPath + "/Textures/" + name + ".png";
            var image = new Texture2D(size, size, TextureFormat.RGBA32, false, normal);
            image.SetPixels32(pixels);
            image.Apply();
            File.WriteAllBytes(path, image.EncodeToPNG());
            Object.DestroyImmediate(image);
            AssetDatabase.ImportAsset(path, ImportAssetOptions.ForceSynchronousImport);
            var importer = (TextureImporter)AssetImporter.GetAtPath(path);
            importer.textureType = normal ? TextureImporterType.NormalMap : TextureImporterType.Default;
            importer.sRGBTexture = !normal;
            importer.mipmapEnabled = true;
            importer.wrapMode = TextureWrapMode.Repeat;
            importer.anisoLevel = 4;
            importer.textureCompression = TextureImporterCompression.Uncompressed;
            importer.maxTextureSize = size;
            importer.SaveAndReimport();
            return AssetDatabase.LoadAssetAtPath<Texture2D>(path);
        }

        static void CheckAddresses()
        {
            var settings = AddressableAssetSettingsDefaultObject.Settings;
            if (settings == null)
                throw new InvalidOperationException("Existing Addressables settings are required.");
            foreach (var entry in settings.groups.Where(g => g != null).SelectMany(g => g.entries))
                if (Names.Contains(entry.address) && AssetDatabase.GUIDToAssetPath(entry.guid) != "Assets/Prefabs/" + entry.address + ".prefab")
                    throw new InvalidOperationException("Address already belongs to another asset: " + entry.address);
        }

        static void RegisterAddress(string path, string name)
        {
            var settings = AddressableAssetSettingsDefaultObject.Settings;
            var group = settings.FindGroup("SpawnInterface") ?? settings.DefaultGroup;
            var entry = settings.CreateOrMoveEntry(AssetDatabase.AssetPathToGUID(path), group);
            entry.address = name;
            settings.SetDirty(AddressableAssetSettings.ModificationEvent.EntryModified, entry, true, true);
            EditorUtility.SetDirty(group);
        }

        static void Folder(string path)
        {
            if (AssetDatabase.IsValidFolder(path))
                return;
            string parent = Path.GetDirectoryName(path).Replace('\\', '/');
            Folder(parent);
            AssetDatabase.CreateFolder(parent, Path.GetFileName(path));
        }
    }
}
