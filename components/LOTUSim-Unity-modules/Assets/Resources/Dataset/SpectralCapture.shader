Shader "Hidden/LOTUSim/DatasetSyntheticSensors"
{
    HLSLINCLUDE
    #pragma target 4.5
    #pragma only_renderers d3d11 vulkan metal
    #pragma multi_compile_instancing
    #include "Packages/com.unity.render-pipelines.core/ShaderLibrary/Common.hlsl"
    #include "Packages/com.unity.render-pipelines.high-definition/Runtime/ShaderLibrary/ShaderVariables.hlsl"
    TEXTURE2D_X(_DatasetSensorDepth);
    TEXTURE2D_X(_DatasetSensorColor);
    float4 _DatasetThermalWindow, _DatasetSurfaceThermal, _DatasetNightParams, _DatasetNightTint;
    float _DatasetBlackHot, _DatasetSensorNoisePhase;
    struct ScreenVaryings
    {
        float4 positionCS : SV_POSITION;
        UNITY_VERTEX_OUTPUT_STEREO
    };
    ScreenVaryings ScreenVert(uint vertexID : SV_VertexID)
    {
        ScreenVaryings o;
        UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o);
        o.positionCS = GetFullScreenTriangleVertexPosition(vertexID);
        return o;
    }
    float Window(float c)
    {
        float v = saturate((c - _DatasetThermalWindow.x) /
                           (_DatasetThermalWindow.y - _DatasetThermalWindow.x));
        return lerp(v, 1 - v, _DatasetBlackHot);
    }
    float Greybody(float c, float emissivity, float reflectedC)
    {
        float t = c + 273.15, e = reflectedC + 273.15, t2 = t * t, e2 = e * e;
        return sqrt(sqrt(lerp(e2 * e2, t2 * t2, emissivity))) - 273.15;
    }
    float3 Reconstruct(uint2 pixel, float depth)
    {
        return ComputeWorldSpacePosition((float2(pixel) + .5) * _ScreenSize.zw, depth,
                                         UNITY_MATRIX_I_VP);
    }
    float4 ThermalBackground(ScreenVaryings i) : SV_Target
    {
        float depth = LOAD_TEXTURE2D_X(_DatasetSensorDepth, uint2(i.positionCS.xy)).r;
    #if UNITY_REVERSED_Z
        bool sky = depth <= 0.0000001;
    #else
        bool sky = depth >= 0.9999999;
    #endif
        float temperature = _DatasetThermalWindow.z;
        if (!sky)
        {
            uint2 pixel = uint2(i.positionCS.xy),
                  right = min(pixel + uint2(1, 0), uint2(_ScreenSize.xy) - 1),
                  up = min(pixel + uint2(0, 1), uint2(_ScreenSize.xy) - 1);
            float3 p = Reconstruct(pixel, depth);
            float3 dx = Reconstruct(right, LOAD_TEXTURE2D_X(_DatasetSensorDepth, right).r) - p;
            float3 dy = Reconstruct(up, LOAD_TEXTURE2D_X(_DatasetSensorDepth, up).r) - p;
            float3 n = cross(dy, dx);
            n = dot(n, n) > 1e-14 ? normalize(n) : float3(0, 1, 0);
            float incidence = abs(dot(n, GetWorldSpaceNormalizeViewDir(p)));
            // Heuristic directional sea emissivity, based on actual depth
            // slopes: preserves wave appearance without using RGB brightness.
            temperature = Greybody(_DatasetThermalWindow.w, lerp(.65, .985, saturate(incidence * 3)),
                                   _DatasetThermalWindow.z);
        }
        float v = Window(temperature);
        return float4(v, v, v, 1);
    }
    struct Attributes
    {
        float3 positionOS : POSITION;
        float3 normalOS : NORMAL;
        UNITY_VERTEX_INPUT_INSTANCE_ID
    };
    struct MeshVaryings
    {
        float4 positionCS : SV_POSITION;
        float3 normalWS : TEXCOORD0;
        UNITY_VERTEX_OUTPUT_STEREO
    };
    MeshVaryings MeshVert(Attributes i)
    {
        UNITY_SETUP_INSTANCE_ID(i);
        MeshVaryings o;
        UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o);
        o.positionCS = TransformWorldToHClip(TransformObjectToWorld(i.positionOS));
        o.normalWS = TransformObjectToWorldNormal(i.normalOS);
        return o;
    }
    float4 ThermalSurface(MeshVaryings i) : SV_Target
    {
        // Broadband grey-body T^4 proxy with directional environment reflection.
        // Not a Planck-band integration, radiance measurement or LWIR calibration.
        float environment = lerp(_DatasetSurfaceThermal.w, _DatasetSurfaceThermal.z,
                                 saturate(normalize(i.normalWS).y * .5 + .5));
        float apparent = Greybody(_DatasetSurfaceThermal.x, _DatasetSurfaceThermal.y, environment);
        float v = Window(apparent);
        return float4(v, v, v, 1);
    }
    float Noise(float2 p)
    {
        return frac(sin(dot(p, float2(12.9898, 78.233)) + _DatasetSensorNoisePhase) * 43758.5453);
    }
    float4 NightVision(ScreenVaryings i) : SV_Target
    {
        uint2 pixel = uint2(i.positionCS.xy);
        float3 scene = LOAD_TEXTURE2D_X(_DatasetSensorColor, pixel).rgb;
        float luminance = max(0, dot(scene, float3(.2126, .7152, .0722)));
        float signal =
            pow(saturate(1 - exp(-luminance * _DatasetNightParams.x)), _DatasetNightParams.y);
        float2 uv = (float2(pixel) + .5) / _ScreenSize.xy;
        signal *= 1 - _DatasetNightParams.w * saturate(dot(uv - .5, uv - .5) * 2);
        signal = saturate(signal + (Noise(pixel) - .5) * 2 * _DatasetNightParams.z);
        return float4(signal * _DatasetNightTint.rgb, 1);
    }
    ENDHLSL
    SubShader
    {
        Tags {"RenderPipeline"="HDRenderPipeline"}
        Pass
        {
            Name "SyntheticThermalBackground"
            Blend Off
            ZWrite Off
            ZTest Always
            Cull Off
            HLSLPROGRAM
            #pragma vertex ScreenVert
            #pragma fragment ThermalBackground
            ENDHLSL
        }
        Pass
        {
            Name "SyntheticThermalSurface"
            Blend Off
            ZWrite Off
            ZTest LEqual
            Cull Back
            HLSLPROGRAM
            #pragma vertex MeshVert
            #pragma fragment ThermalSurface
            ENDHLSL
        }
        Pass
        {
            Name "SyntheticNightVision"
            Blend Off
            ZWrite Off
            ZTest Always
            Cull Off
            HLSLPROGRAM
            #pragma vertex ScreenVert
            #pragma fragment NightVision
            ENDHLSL
        }
    }
}
