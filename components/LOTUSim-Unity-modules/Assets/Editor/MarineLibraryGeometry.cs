using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;
using UnityEngine.Rendering;

namespace Lotusim.EditorTools
{
    public static partial class MarineLibraryBuilder
    {
        sealed class Geometry
        {
            public readonly List<Vector3> vertices = new List<Vector3>(), normals = new List<Vector3>();
            public readonly List<Vector2> uv = new List<Vector2>();
            public readonly Dictionary<int, List<int>> triangles = new Dictionary<int, List<int>>();
            public int parts;
            int V(Vector3 p, Vector3 n, Vector2 t)
            {
                int i = vertices.Count;
                vertices.Add(p);
                normals.Add(n.normalized);
                uv.Add(t);
                return i;
            }

            void F(int a, int b, int c, int material, Vector3 outward)
            {
                if (a < 0 || b < 0 || c < 0 || a >= vertices.Count || b >= vertices.Count || c >= vertices.Count)
                    throw new InvalidOperationException("Marine geometry index before vertex allocation.");
                var cross = Vector3.Cross(vertices[b] - vertices[a], vertices[c] - vertices[a]);
                if (cross.sqrMagnitude < 1e-17f)
                    return;
                if (!triangles.TryGetValue(material, out var faces))
                {
                    faces = new List<int>();
                    triangles.Add(material, faces);
                }

                if (Vector3.Dot(cross, outward) < 0)
                    faces.AddRange(new[] { a, c, b });
                else
                    faces.AddRange(new[] { a, b, c });
            }

            public void Quad(Vector3 a, Vector3 b, Vector3 c, Vector3 d, int mat, Vector3 normal)
            {
                int i = V(a, normal, Vector2.zero);
                V(b, normal, new Vector2(Vector3.Distance(a, b), 0));
                V(c, normal, new Vector2(Vector3.Distance(a, b), Vector3.Distance(b, c)));
                V(d, normal, new Vector2(0, Vector3.Distance(a, d)));
                F(i, i + 1, i + 2, mat, normal);
                F(i, i + 2, i + 3, mat, normal);
                parts++;
            }

            public void Box(Vector3 center, Vector3 size, int mat, float bevel = 0, Quaternion? rotation = null)
            {
                var q = rotation ?? Quaternion.identity;
                float x = size.x / 2, z = size.z / 2, y = size.y / 2;
                bevel = Mathf.Clamp(bevel, 0, Mathf.Min(x, z) * .7f);
                var outline = bevel < 1e-6f ? new[]
                {
                    new Vector2(-x, -z),
                    new Vector2(x, -z),
                    new Vector2(x, z),
                    new Vector2(-x, z)
                }

                : new[]
                {
                    new Vector2(-x + bevel, -z),
                    new Vector2(x - bevel, -z),
                    new Vector2(x, -z + bevel),
                    new Vector2(x, z - bevel),
                    new Vector2(x - bevel, z),
                    new Vector2(-x + bevel, z),
                    new Vector2(-x, z - bevel),
                    new Vector2(-x, -z + bevel)
                };
                for (int j = 0; j < outline.Length; j++)
                {
                    var a = outline[j];
                    var b = outline[(j + 1) % outline.Length];
                    var n = q * new Vector3(b.y - a.y, 0, a.x - b.x).normalized;
                    Quad(center + q * new Vector3(a.x, -y, a.y), center + q * new Vector3(b.x, -y, b.y), center + q * new Vector3(b.x, y, b.y), center + q * new Vector3(a.x, y, a.y), mat, n);
                }

                for (int end = -1; end <= 1; end += 2)
                {
                    var n = q * Vector3.up * end;
                    int baseIndex = vertices.Count;
                    V(center + q * Vector3.up * (y * end), n, Vector2.zero);
                    foreach (var p in outline)
                        V(center + q * new Vector3(p.x, y * end, p.y), n, new Vector2(p.x, p.y));
                    for (int i = 0; i < outline.Length; i++)
                        F(baseIndex, baseIndex + 1 + i, baseIndex + 1 + (i + 1) % outline.Length, mat, n);
                }

                parts++;
            }

            public void Tube(Vector3 a, Vector3 b, float radius, int mat, float endRadius = -1, int around = 12)
            {
                if (radius <= 0 || (b - a).sqrMagnitude < 1e-10f)
                    return;
                if (endRadius < 0)
                    endRadius = radius;
                endRadius = Mathf.Max(endRadius, .00005f);
                Vector3 axis = (b - a).normalized, u = Vector3.Cross(axis, Mathf.Abs(axis.y) > .9f ? Vector3.right : Vector3.up).normalized, v = Vector3.Cross(axis, u);
                int first = vertices.Count;
                float length = (b - a).magnitude;
                for (int ring = 0; ring < 2; ring++)
                    for (int j = 0; j <= around; j++)
                    {
                        float angle = j * Mathf.PI * 2 / around;
                        Vector3 radial = u * Mathf.Cos(angle) + v * Mathf.Sin(angle);
                        Vector3 normal = (radial + axis * ((radius - endRadius) / length)).normalized;
                        V((ring == 0 ? a : b) + radial * (ring == 0 ? radius : endRadius), normal, new Vector2(j / (float)around * 2 * Mathf.PI * radius, ring * length));
                    }

                for (int j = 0; j < around; j++)
                {
                    int x = first + j, n = x + around + 1;
                    Vector3 radial = normals[x] + normals[x + 1];
                    F(x, x + 1, n, mat, radial);
                    F(x + 1, n + 1, n, mat, radial);
                }

                for (int cap = 0; cap < 2; cap++)
                {
                    var normal = axis * (cap == 0 ? -1 : 1);
                    var center = cap == 0 ? a : b;
                    float r = cap == 0 ? radius : endRadius;
                    int start = V(center, normal, Vector2.zero);
                    for (int j = 0; j <= around; j++)
                    {
                        float angle = j * Mathf.PI * 2 / around;
                        V(center + (u * Mathf.Cos(angle) + v * Mathf.Sin(angle)) * r, normal, new Vector2(Mathf.Cos(angle) * r, Mathf.Sin(angle) * r));
                    }

                    for (int j = 0; j < around; j++)
                        F(start, start + j + 1, start + j + 2, mat, normal);
                }

                parts++;
            }

            public void Ellipsoid(Vector3 center, Vector3 radii, int mat, int around = 24, int rings = 14)
            {
                int first = vertices.Count;
                for (int row = 0; row <= rings; row++)
                    for (int j = 0; j <= around; j++)
                    {
                        float latitude = -Mathf.PI / 2 + row * Mathf.PI / rings, angle = j * 2 * Mathf.PI / around;
                        Vector3 n = new Vector3(Mathf.Cos(latitude) * Mathf.Cos(angle), Mathf.Sin(latitude), Mathf.Cos(latitude) * Mathf.Sin(angle));
                        var p = Vector3.Scale(n, radii);
                        V(center + p, new Vector3(n.x / radii.x, n.y / radii.y, n.z / radii.z), new Vector2(j / (float)around, row / (float)rings));
                    }

                for (int row = 0; row < rings; row++)
                    for (int j = 0; j < around; j++)
                    {
                        int x = first + row * (around + 1) + j, n = x + around + 1;
                        Vector3 expected = vertices[x] + vertices[n] + vertices[x + 1] - 3 * center;
                        F(x, x + 1, n, mat, expected);
                        F(x + 1, n + 1, n, mat, expected);
                    }

                parts++;
            }

            public void Ring(Vector3 center, Vector3 axis, float radius, float tube, int mat, int sides = 32)
            {
                axis = axis.normalized;
                var u = Vector3.Cross(axis, Mathf.Abs(axis.y) > .9f ? Vector3.right : Vector3.up).normalized;
                var v = Vector3.Cross(axis, u);
                for (int i = 0; i < sides; i++)
                {
                    float a = i * 2 * Mathf.PI / sides, b = (i + 1) * 2 * Mathf.PI / sides;
                    Tube(center + (u * Mathf.Cos(a) + v * Mathf.Sin(a)) * radius, center + (u * Mathf.Cos(b) + v * Mathf.Sin(b)) * radius, tube, mat, around: 8);
                }
            }

            public void Rope(Vector3 a, Vector3 b, float sag, float radius, int mat, int segments = 16)
            {
                Vector3 previous = a;
                for (int i = 1; i <= segments; i++)
                {
                    float t = i / (float)segments;
                    var next = Vector3.Lerp(a, b, t) - Vector3.up * (4 * sag * t * (1 - t));
                    Tube(previous, next, radius, mat, around: 8);
                    previous = next;
                }
            }

            public void Hull(float length, float beam, float draft, float freeboard, int above, int below, int deck, int stripe)
            {
                const int stations = 80;
                // Closed, symmetric hard-chine sections. Keel, waterline and
                // sheer are explicit rings, not a scaled primitive capsule.
                Vector2[] section =
                {
                    new Vector2(0, 1),
                    new Vector2(.5f, 1),
                    new Vector2(.90f, 1),
                    new Vector2(1, .96f),
                    new Vector2(.99f, .50f),
                    new Vector2(.97f, .04f),
                    new Vector2(.95f, 0),
                    new Vector2(.82f, -.55f),
                    new Vector2(.45f, -.91f),
                    new Vector2(0, -1),
                    new Vector2(-.45f, -.91f),
                    new Vector2(-.82f, -.55f),
                    new Vector2(-.95f, 0),
                    new Vector2(-.97f, .04f),
                    new Vector2(-.99f, .5f),
                    new Vector2(-1, .96f),
                    new Vector2(-.90f, 1),
                    new Vector2(-.5f, 1)
                };
                var points = new Vector3[stations + 1, section.Length];
                for (int i = 0; i <= stations; i++)
                {
                    float t = i / (float)stations, x = (t - .5f) * length, w = HullWidth(t) * beam / 2, sheer = freeboard * (1 + .35f * Mathf.Pow(t, 5));
                    for (int j = 0; j < section.Length; j++)
                    {
                        var s = section[j];
                        float y = s.y < 0 ? s.y * draft * (1 - .80f * Mathf.Pow(t, 7)) : s.y * sheer;
                        float rake = Mathf.Pow(t, 12) * (1 - Mathf.Clamp01(s.y)) * length * .025f;
                        points[i, j] = new Vector3(x - rake, y, s.x * w);
                    }
                }

                for (int i = 0; i < stations; i++)
                    for (int j = 0; j < section.Length; j++)
                    {
                        int next = (j + 1) % section.Length;
                        var a = points[i, j];
                        var b = points[i + 1, j];
                        var c = points[i + 1, next];
                        var d = points[i, next];
                        float y = (section[j].y + section[next].y) / 2;
                        int material = y > .98f ? deck : y < 0 ? below : y < .04f ? stripe : above;
                        Vector3 n = Vector3.Cross(b - a, d - a);
                        var mid = (a + b + c + d) / 4;
                        Vector3 outward = new Vector3(0, y > .98f ? 1 : y < -.9f ? -1 : 0, mid.z);
                        if (outward.sqrMagnitude < 1e-6f)
                            outward = Vector3.down;
                        if (Vector3.Dot(n, outward) < 0)
                            n = -n;
                        Quad(a, b, c, d, material, n.normalized);
                    }

                for (int end = 0; end < 2; end++)
                {
                    int index = end == 0 ? 0 : stations;
                    Vector3 center = Vector3.zero;
                    for (int j = 0; j < section.Length; j++)
                        center += points[index, j];
                    center /= section.Length;
                    Vector3 normal = end == 0 ? Vector3.left : Vector3.right;
                    for (int j = 0; j < section.Length; j++)
                    {
                        var a = points[index, j];
                        var b = points[index, (j + 1) % section.Length];
                        int start = V(center, normal, Vector2.zero);
                        V(a, normal, new Vector2(a.z, a.y));
                        V(b, normal, new Vector2(b.z, b.y));
                        F(start, start + 1, start + 2, above, normal);
                    }
                }

                parts++;
            }

            public void Sail(Vector3 a, Vector3 b, Vector3 c, float camber, int mat)
            {
                const int rows = 28;
                var normal = Vector3.Cross(b - a, c - a).normalized;
                for (int side = -1; side <= 1; side += 2)
                {
                    var indices = new int[rows + 1][];
                    for (int i = 0; i <= rows; i++)
                    {
                        indices[i] = new int[rows - i + 1];
                        float u = i / (float)rows;
                        for (int j = 0; j <= rows - i; j++)
                        {
                            float v = j / (float)rows;
                            Vector3 p = a * (1 - u - v) + b * u + c * v + normal * (camber * Mathf.Sin(Mathf.PI * u) * Mathf.Sin(Mathf.PI * v) + side * .004f);
                            indices[i][j] = V(p, normal * side, new Vector2(u, v));
                        }
                    }

                    for (int i = 0; i < rows; i++)
                        for (int j = 0; j < rows - i; j++)
                        {
                            F(indices[i][j], indices[i + 1][j], indices[i][j + 1], mat, normal * side);
                            if (j < rows - i - 1)
                                F(indices[i][j + 1], indices[i + 1][j], indices[i + 1][j + 1], mat, normal * side);
                        }
                }

                parts++;
            }

            public Mesh ToMesh(string name, out int[] materialSlots)
            {
                materialSlots = triangles.Keys.OrderBy(i => i).ToArray();
                var mesh = new Mesh
                {
                    name = name,
                    indexFormat = IndexFormat.UInt32
                };
                mesh.SetVertices(vertices);
                mesh.SetNormals(normals);
                mesh.SetUVs(0, uv);
                mesh.subMeshCount = materialSlots.Length;
                for (int i = 0; i < materialSlots.Length; i++)
                    mesh.SetTriangles(triangles[materialSlots[i]], i);
                mesh.RecalculateBounds();
                mesh.RecalculateTangents();
                return mesh;
            }
        }

        static float HullWidth(float t) => Mathf.Max(.012f, (.72f + .28f * Mathf.SmoothStep(0, 1, t * 5)) * Mathf.Pow(Mathf.Max(.0001f, 1 - Mathf.Pow(t, 4)), .66f));
    }
}
