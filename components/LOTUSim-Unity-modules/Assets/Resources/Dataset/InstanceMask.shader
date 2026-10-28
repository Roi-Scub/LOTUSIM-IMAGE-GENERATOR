Shader "Hidden/LOTUSim/DatasetInstanceMask"
{
    HLSLINCLUDE
    #pragma target 4.5
    #pragma only_renderers d3d11 vulkan metal
    #pragma multi_compile_instancing
    #include "Packages/com.unity.render-pipelines.core/ShaderLibrary/Common.hlsl"
    #include "Packages/com.unity.render-pipelines.high-definition/Runtime/ShaderLibrary/ShaderVariables.hlsl"
    struct Attributes
    {
        float3 positionOS : POSITION;
        UNITY_VERTEX_INPUT_INSTANCE_ID
    };
    struct Varyings
    {
        float4 positionCS : SV_POSITION;
        UNITY_VERTEX_OUTPUT_STEREO
    };
    Varyings Vert(Attributes input)
    {
        UNITY_SETUP_INSTANCE_ID(input);
        Varyings output;
        UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(output);
        output.positionCS = TransformWorldToHClip(TransformObjectToWorld(input.positionOS));
        return output;
    }
    float4 Frag(Varyings input) : SV_Target
    {
        return float4(1, 1, 1, 1);
    }
    ENDHLSL
    SubShader
    {
        Tags { "RenderPipeline"="HDRenderPipeline" }
        Pass
        {
            Name "VisibleMask"
            Blend Off
            ZWrite Off
            ZTest LEqual
            Cull Back
            HLSLPROGRAM
            #pragma vertex Vert
            #pragma fragment Frag
            ENDHLSL
        }
        Pass
        {
            Name "AmodalMaskInFrame"
            Blend Off
            ZWrite Off
            ZTest Always
            Cull Back
            HLSLPROGRAM
            #pragma vertex Vert
            #pragma fragment Frag
            ENDHLSL
        }
    }
}
