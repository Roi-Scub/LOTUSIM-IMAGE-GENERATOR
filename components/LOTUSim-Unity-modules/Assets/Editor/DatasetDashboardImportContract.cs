using System;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using Lotusim.Dataset;

namespace Lotusim.EditorTools
{
    [Serializable]
    public sealed class DashboardMeshDimensions
    {
        public float lengthM, beamM, heightM, draftM;
    }

    [Serializable]
    public sealed class DashboardMeshProfile
    {
        public float maxSpeedMps, maxAltitudeM, bufferM;
    }

    [Serializable]
    public sealed class DashboardMeshFile
    {
        public string path, sha256;
        public long bytes;
    }

    [Serializable]
    public sealed class DashboardMeshRequest
    {
        public string schema, id, model, revisionSha256, category, domain, label, license, sourceUrl;
        public string bundleDirectory, geometryFile, infoFile;
        public int classId;
        public DashboardMeshDimensions dimensions;
        public DashboardMeshProfile profile;
        public DashboardMeshFile[] files;
    }

    [Serializable]
    public sealed class DashboardMeshResult
    {
        public string schema = "lotusim-unity-mesh-result-1", id, model, revisionSha256, requestSha256, status;
        public string prefabPath, prefabGuid, prefabSha256, addressableKey, geometrySha256, unityProjectPath, error, updatedAt;
    }

    [Serializable]
    public sealed class DashboardMeshInfo
    {
        public string key, category, title, author, source, license, licenseUrl;
        public float lengthM, beamM, heightM, draftM;
        public MarineOpenBoatsBuilder.MaterialInfo[] materials;
        public string[] changes;
    }

    // Pure request/file guards shared by the automatic watcher and tests.
    // No AssetDatabase, object creation, converter execution, ROS or HTTP here.
    public static class DatasetDashboardImportContract
    {
        public const long MaximumRequestBytes = 1024 * 1024, MaximumFileBytes = 256 * 1024 * 1024, MaximumBundleBytes = 256 * 1024 * 1024;
        public static string ImportId(string model)
        {
            if (!DatasetImportedAssetRegistry.ModelKey(model))
                throw new InvalidDataException("Invalid imported model key.");
            return "import-" + Guid.ParseExact(model.Substring(7), "N").ToString("D");
        }

        public static string Hash(byte[] data)
        {
            using (var sha = SHA256.Create())
                return BitConverter.ToString(sha.ComputeHash(data)).Replace("-", "").ToLowerInvariant();
        }

        public static string FileHash(string path)
        {
            NoLinks(path);
            using (var file = File.OpenRead(path))
            using (var sha = SHA256.Create())
                return BitConverter.ToString(sha.ComputeHash(file)).Replace("-", "").ToLowerInvariant();
        }

        public static void NoLinks(string path)
        {
            string current = Path.GetFullPath(path);
            while (!string.IsNullOrEmpty(current))
            {
                try
                {
                    if ((File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0)
                        throw new InvalidDataException("Symlink/reparse-point paths are not accepted.");
                }
                catch (FileNotFoundException)
                {
                }
                catch (DirectoryNotFoundException)
                {
                }

                string parent = Path.GetDirectoryName(current);
                if (parent == current)
                    break;
                current = parent;
            }
        }

        public static string SafeChild(string root, string relative)
        {
            RelativePath(relative);
            string basis = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
            string result = Path.GetFullPath(Path.Combine(basis, relative));
            if (!result.StartsWith(basis, StringComparison.Ordinal))
                throw new InvalidDataException("Import path escaped its root.");
            NoLinks(result);
            return result;
        }

        public static void RelativePath(string relative)
        {
            if (string.IsNullOrWhiteSpace(relative) || relative.Length > 220 || relative.Contains('\\') || Path.IsPathRooted(relative))
                throw new InvalidDataException("Unsafe import path.");
            var parts = relative.Split('/');
            if (parts.Any(p => p.Length == 0 || p == "." || p == ".." || p[0] == '.' || p.Any(c => !(c >= 'a' && c <= 'z') && !(c >= 'A' && c <= 'Z') && !(c >= '0' && c <= '9') && c != '_' && c != '-' && c != '.' && c != ' ')))
                throw new InvalidDataException("Unsafe import path.");
        }

        public static void Validate(DashboardMeshRequest request, string folderName)
        {
            if (request == null || request.schema != "lotusim-unity-mesh-import-1" || ImportId(request.model) != request.id || request.id != folderName || !DatasetImportedAssetRegistry.Hex(request.revisionSha256, 64) || request.bundleDirectory != "prepared/" + request.revisionSha256 || request.geometryFile != "geometry.bytes" || request.infoFile != "model-info.json" || request.classId != DatasetImportedAssetRegistry.ClassId(request.category) || request.classId == 0 || string.IsNullOrWhiteSpace(request.label) || request.label.Length > 150 || string.IsNullOrWhiteSpace(request.license) || request.license.Length > 2000 || request.dimensions == null || request.profile == null || request.files == null || request.files.Length < 4 || request.files.Length > 805)
                throw new InvalidDataException("Invalid dashboard import request.");
            string domain = request.classId == 1 || request.classId == 13 ? "moored" : request.classId >= 2 && request.classId <= 5 ? "air" : "sea";
            if (request.domain != domain)
                throw new InvalidDataException("Object category/domain mismatch.");
            var d = request.dimensions;
            var p = request.profile;
            if (!Range(d.lengthM, .001f, 1000) || !Range(d.beamM, .001f, 1000) || !Range(d.heightM, .001f, 1000) || !Range(d.draftM, 0, 25) || !Range(p.maxSpeedMps, 0, 350) || !Range(p.maxAltitudeM, 0, 15000) || !Range(p.bufferM, .1f, 200) || domain == "moored" && (p.maxSpeedMps != 0 || p.maxAltitudeM != 0) || domain == "sea" && p.maxAltitudeM != 0)
                throw new InvalidDataException("Invalid imported dimensions or declared capabilities.");
            long bytes = 0;
            foreach (var file in request.files)
            {
                if (file == null || !DatasetImportedAssetRegistry.Hex(file.sha256, 64) || file.bytes < 1 || file.bytes > MaximumFileBytes)
                    throw new InvalidDataException("Invalid prepared file record.");
                string extension = Path.GetExtension(file.path ?? "").ToLowerInvariant();
                if (file.path != request.geometryFile && file.path != request.infoFile && file.path != "gazebo.obj" && file.path != "gazebo.mtl" && !(extension == ".png" && file.path.Length > 4 && file.path.Substring(0, file.path.Length - 4).All(c => char.IsLetterOrDigit(c) && c < 128 || c == '_' || c == '-')))
                    throw new InvalidDataException("Only the fixed prepared geometry/metadata/Gazebo files and PNG textures may enter the bundle inventory.");
                if (file.path.Contains('/'))
                    throw new InvalidDataException("Prepared bundle files must be flat, canonical names.");
                RelativePath(file.path);
                bytes = checked(bytes + file.bytes);
            }

            if (bytes > MaximumBundleBytes || request.files.Select(f => f.path).Distinct(StringComparer.OrdinalIgnoreCase).Count() != request.files.Length || !request.files.Any(f => f.path == request.geometryFile) || !request.files.Any(f => f.path == request.infoFile) || !request.files.Any(f => f.path == "gazebo.obj") || !request.files.Any(f => f.path == "gazebo.mtl"))
                throw new InvalidDataException("Invalid prepared bundle inventory.");
        }

        public static void VerifyBundle(DashboardMeshRequest request, string directory)
        {
            NoLinks(directory);
            if (!Directory.Exists(directory))
                throw new DirectoryNotFoundException("Prepared import bundle missing.");
            foreach (var record in request.files)
            {
                string path = SafeChild(directory, record.path);
                if (!File.Exists(path) || new FileInfo(path).Length != record.bytes || FileHash(path) != record.sha256)
                    throw new InvalidDataException("Prepared import checksum mismatch.");
            }
        }

        public static byte[] ReadRequest(string path)
        {
            NoLinks(path);
            var info = new FileInfo(path);
            if (!info.Exists || info.Length < 2 || info.Length > MaximumRequestBytes)
                throw new InvalidDataException("Invalid request length.");
            byte[] data = File.ReadAllBytes(path);
            if (data.LongLength > MaximumRequestBytes)
                throw new InvalidDataException("Request exceeds its limit.");
            return data;
        }

        public static bool Range(float value, float min, float max) => !float.IsNaN(value) && !float.IsInfinity(value) && value >= min && value <= max;
        public static bool SupportsMarineWaveProxy(DashboardMeshDimensions dimensions) => dimensions != null && Range(dimensions.lengthM, 1, 400) && Range(dimensions.beamM, .5f, dimensions.lengthM) && Range(dimensions.draftM, 0, 25);
        public static bool CopyToUnity(DashboardMeshRequest request, DashboardMeshFile entry) => entry != null && (entry.path == request.geometryFile || entry.path == request.infoFile || entry.path.EndsWith(".png", StringComparison.Ordinal));
        public static DashboardMeshResult ReadyResult(DashboardMeshRequest request, string requestSha256, string prefabGuid, string prefabSha256, string geometrySha256, string project)
        {
            Validate(request, request.id);
            if (!DatasetImportedAssetRegistry.Hex(requestSha256, 64) || !DatasetImportedAssetRegistry.Hex(prefabGuid, 32) || !DatasetImportedAssetRegistry.Hex(prefabSha256, 64) || !DatasetImportedAssetRegistry.Hex(geometrySha256, 64) || geometrySha256 != request.files.Single(f => f.path == request.geometryFile).sha256 || string.IsNullOrEmpty(project) || !Path.IsPathRooted(project))
                throw new InvalidDataException("Invalid ready receipt identity.");
            return new DashboardMeshResult
            {
                status = "ready",
                id = request.id,
                model = request.model,
                requestSha256 = requestSha256,
                revisionSha256 = request.revisionSha256,
                prefabPath = "Assets/Prefabs/" + request.model + ".prefab",
                prefabGuid = prefabGuid,
                prefabSha256 = prefabSha256,
                addressableKey = request.model,
                geometrySha256 = geometrySha256,
                unityProjectPath = Path.GetFullPath(project),
                updatedAt = DateTime.UtcNow.ToString("o"),
                error = ""
            };
        }

        public static void AtomicResult(string path, DashboardMeshResult result)
        {
            NoLinks(path);
            string temporary = path + ".pending-" + Guid.NewGuid().ToString("N");
            try
            {
                // FileMode.CreateNew refuses any preexisting staging target.
                using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                {
                    byte[] data = new UTF8Encoding(false).GetBytes(UnityEngine.JsonUtility.ToJson(result, true));
                    stream.Write(data, 0, data.Length);
                    stream.Flush(true);
                }

                if (File.Exists(path))
                    File.Replace(temporary, path, null);
                else
                    File.Move(temporary, path);
            }
            finally
            {
                if (File.Exists(temporary))
                    File.Delete(temporary);
            }
        }
    }
}
