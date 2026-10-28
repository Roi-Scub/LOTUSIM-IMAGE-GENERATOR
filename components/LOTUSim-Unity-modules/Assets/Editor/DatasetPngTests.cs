using System;
using System.Linq;
using Lotusim.Dataset;
using UnityEditor;
using UnityEngine;

namespace Lotusim.EditorTools
{
    public static class DatasetPngTests
    {
        [MenuItem("LOTUSim/Dataset/Validate lossless synthetic PNG export")]
        public static void Check()
        {
            foreach (var size in new[]
            {
                new Vector2Int(5, 3),
                new Vector2Int(3840, 2160)
            }

            )
            {
                var image = new Texture2D(size.x, size.y, TextureFormat.RGB24, false, true);
                var decoded = new Texture2D(2, 2, TextureFormat.RGB24, false, true);
                try
                {
                    var values = new byte[size.x * size.y * 3];
                    for (int y = 0; y < size.y; y++)
                        for (int x = 0; x < size.x; x++)
                        {
                            int i = (y * size.x + x) * 3;
                            values[i] = (byte)(x * 7 + y);
                            values[i + 1] = (byte)(y * 13);
                            values[i + 2] = (byte)(x ^ y);
                        }

                    image.LoadRawTextureData(values);
                    image.Apply(false, false);
                    var png = DatasetRgbPng.Encode(image);
                    if (!ImageConversion.LoadImage(decoded, png, false) || decoded.width != size.x || decoded.height != size.y)
                        throw new Exception("Managed PNG dimensions/CRC/decompression failed");
                    var actual = decoded.GetPixels32();
                    for (int i = 0; i < actual.Length; i++)
                        if (actual[i].r != values[i * 3] || actual[i].g != values[i * 3 + 1] || actual[i].b != values[i * 3 + 2])
                            throw new Exception("PNG pixels or row orientation changed");
                }
                finally
                {
                    UnityEngine.Object.DestroyImmediate(image);
                    UnityEngine.Object.DestroyImmediate(decoded);
                }
            }

            Debug.Log("[Dataset PNG] PASS lossless RGB24 encode/decode, CRC, zlib and exact row orientation at 5x3 and native 4K.");
        }
    }
}
