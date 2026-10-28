using System;
using System.IO;
using System.IO.Compression;
using UnityEngine;

namespace Lotusim.Dataset
{
    // The native Unity 2022 PNG encoder can spend minutes in deflate's match
    // search for some large flat thermal buffers. Use a bounded-work, filter-0
    // PNG path for the synthetic RGB24 outputs. Pixels are lossless and keep
    // the same top-left file convention as Unity's PNG encoder.
    public static class DatasetRgbPng
    {
        static readonly uint[] CrcTable=CreateCrcTable();
        public static byte[] Encode(Texture2D texture)
        {
            if(texture==null||texture.format!=TextureFormat.RGB24||texture.width<1||texture.height<1||texture.width>4096||texture.height>4096)
                throw new ArgumentException("Synthetic PNG export requires a readable RGB24 image, at most 4096 x 4096.");
            int width=texture.width,height=texture.height,stride=checked(width*3);
            var source=texture.GetRawTextureData<byte>();var rows=new byte[checked((stride+1)*height)];
            if(source.Length!=stride*height) throw new ArgumentException("RGB24 PNG input must not have mipmaps.");
            for(int y=0;y<height;y++) {
                int start=(height-1-y)*stride,target=y*(stride+1)+1;
                for(int x=0;x<stride;x++)rows[target+x]=source[start+x];
            }
            byte[] compressed;
            using(var zlib=new MemoryStream()) {
                zlib.WriteByte(0x78);zlib.WriteByte(0x01); // RFC 1950, fastest.
                using(var deflate=new DeflateStream(zlib,System.IO.Compression.CompressionLevel.Fastest,true))deflate.Write(rows,0,rows.Length);
                uint a=1,b=0;
                // Limit accumulator growth without a modulo per byte.
                for(int start=0;start<rows.Length;start+=5552) {
                    int end=Math.Min(rows.Length,start+5552);for(int i=start;i<end;i++){a+=rows[i];b+=a;}a%=65521;b%=65521;
                }
                UInt(zlib,b<<16|a);compressed=zlib.ToArray();
            }
            using(var png=new MemoryStream()) {
                png.Write(new byte[]{137,80,78,71,13,10,26,10},0,8);
                using(var header=new MemoryStream()) {UInt(header,(uint)width);UInt(header,(uint)height);header.Write(new byte[]{8,2,0,0,0},0,5);Chunk(png,"IHDR",header.ToArray());}
                Chunk(png,"IDAT",compressed);Chunk(png,"IEND",Array.Empty<byte>());return png.ToArray();
            }
        }
        static void UInt(Stream output,uint value) {output.WriteByte((byte)(value>>24));output.WriteByte((byte)(value>>16));output.WriteByte((byte)(value>>8));output.WriteByte((byte)value);}
        static void Chunk(Stream output,string type,byte[] data)
        {
            UInt(output,(uint)data.Length);uint crc=0xffffffff;
            foreach(char c in type){byte value=(byte)c;output.WriteByte(value);crc=Update(crc,value);}
            output.Write(data,0,data.Length);foreach(byte value in data)crc=Update(crc,value);UInt(output,crc^0xffffffff);
        }
        static uint Update(uint crc,byte value)=>CrcTable[(crc^value)&255]^(crc>>8);
        static uint[] CreateCrcTable()
        {
            var table=new uint[256];for(uint i=0;i<256;i++){uint crc=i;for(int bit=0;bit<8;bit++)crc=(crc&1)!=0?0xedb88320^(crc>>1):crc>>1;table[i]=crc;}return table;
        }
    }
}
