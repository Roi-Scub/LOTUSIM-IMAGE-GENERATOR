using System;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;

namespace Lotusim.Dataset
{
    /// <summary>
    /// Kinematic, moored visual flotation, not a Gazebo hydrodynamics model.
    /// Only the visual child moves; ROS retains ownership of the root transform.
    /// </summary>
    public sealed class BuoyWaveMotion : MonoBehaviour
    {
        public const string VisualChildName = "MarineBuoyVisual_v1";
        const float QueryToleranceM = .01f, AcceptedErrorM = .05f;
        WaterSurface m_water;
        Transform m_visual;
        Camera m_camera;
        DatasetFlotationSettings m_settings;
        Vector3 m_restPosition;
        Quaternion m_restRotation;
        readonly Vector3[] m_candidates = new Vector3[5];
        readonly bool[] m_hasCandidate = new bool[5];
        readonly float[] m_heights = new float[5];
        bool m_configured, m_initialized;
        float m_heave;
        Quaternion m_tilt = Quaternion.identity;
        public bool HasValidSample
        {
            get; private set;
        }
        public int SampleUnityFrame { get; private set; } = -1;
        public float LastValidRealtime
        {
            get; private set;
        }
        public float CenterWaterHeightM
        {
            get; private set;
        }
        public float MeanWaterHeightM
        {
            get; private set;
        }
        public float MaxQueryErrorM
        {
            get; private set;
        }
        public float HeaveM => m_heave;
        public Vector3 SurfaceNormal { get; private set; } = Vector3.up;
        public float AppliedTiltDeg => Vector3.Angle(Vector3.up, m_tilt * Vector3.up);
        public string LastQueryFailure { get; private set; } = "Water simulation is warming up.";

        public void Configure(WaterSurface water, Transform visual, Camera camera, DatasetFlotationSettings settings)
        {
            if (water == null || visual == null || camera == null || settings == null)
                throw new ArgumentException("Flotation requires an ocean, visual child, camera and settings.");
            if (visual == transform || !visual.IsChildOf(transform))
                throw new ArgumentException("Flotation must not move the ROS-controlled root.");
            if (m_configured)
                throw new InvalidOperationException("Flotation has already been configured.");
            settings.Validate();
            m_water = water;
            m_visual = visual;
            m_camera = camera;
            m_settings = settings;
            m_restPosition = visual.localPosition;
            m_restRotation = visual.localRotation;
            m_configured = true;
            LastValidRealtime = Time.realtimeSinceStartup;
        }

        void OnEnable()
        {
            RenderPipelineManager.beginCameraRendering += BeforeCamera;
        }

        void OnDisable()
        {
            RenderPipelineManager.beginCameraRendering -= BeforeCamera;
            if (m_configured && m_visual != null)
            {
                m_visual.localPosition = m_restPosition;
                m_visual.localRotation = m_restRotation;
            }

            m_initialized = false;
            HasValidSample = false;
        }

        void BeforeCamera(ScriptableRenderContext context, Camera camera)
        {
            if (!m_configured || !m_settings.enabled || camera != m_camera || SampleUnityFrame == Time.frameCount)
                return;
            SampleUnityFrame = Time.frameCount;
            HasValidSample = false;
            if (m_water == null || m_visual == null)
            {
                LastQueryFailure = "The ocean or visual child disappeared.";
                return;
            }

            // HDRP 14 updates GPU/CPU water before beginCameraRendering and before
            // culling. Sample once, then render/capture that exact visual pose.
            Vector3 rest = m_visual.parent.TransformPoint(m_restPosition);
            float radius = m_settings.sampleRadiusM;
            MaxQueryErrorM = 0;
            for (int i = 0; i < 5; i++)
            {
                Vector3 offset = i == 1 ? Vector3.left * radius : i == 2 ? Vector3.right * radius : i == 3 ? Vector3.back * radius : i == 4 ? Vector3.forward * radius : Vector3.zero;
                Vector3 point = rest + offset;
                var query = new WaterSearchParameters
                {
                    targetPosition = point,
                    startPosition = m_hasCandidate[i] ? m_candidates[i] : point,
                    error = QueryToleranceM,
                    maxIterations = 16
                };
                bool available = m_water.FindWaterSurfaceHeight(query, out var result);
                if (!available || !Finite(result.height) || !Finite(result.error) || result.error > AcceptedErrorM)
                {
                    m_hasCandidate[i] = false;
                    LastQueryFailure = available ? "Water height search did not converge within 5 cm." : "HDRP CPU water data unavailable. Check Script Interactions.";
                    return;
                }

                m_candidates[i] = result.candidateLocation;
                m_hasCandidate[i] = true;
                m_heights[i] = result.height;
                MaxQueryErrorM = Mathf.Max(MaxQueryErrorM, result.error);
            }

            CenterWaterHeightM = m_heights[0];
            MeanWaterHeightM = (2 * m_heights[0] + m_heights[1] + m_heights[2] + m_heights[3] + m_heights[4]) / 6;
            SurfaceNormal = NormalFromHeights(m_heights[1], m_heights[2], m_heights[3], m_heights[4], radius);
            Vector3 normal = ClampNormal(SurfaceNormal, m_settings.maxTiltDeg);
            float desiredHeave = MeanWaterHeightM + m_settings.waterlineOffsetM - rest.y;
            Quaternion desiredTilt = Quaternion.FromToRotation(Vector3.up, normal);
            if (!m_initialized)
            {
                m_heave = desiredHeave;
                m_tilt = desiredTilt;
                m_initialized = true;
            }
            else
            {
                m_heave = Mathf.Lerp(m_heave, desiredHeave, ResponseBlend(m_settings.heightResponsePerSecond, Time.deltaTime));
                m_tilt = Quaternion.Slerp(m_tilt, desiredTilt, ResponseBlend(m_settings.tiltResponsePerSecond, Time.deltaTime));
            }

            Quaternion restWorld = m_visual.parent.rotation * m_restRotation;
            m_visual.SetPositionAndRotation(rest + Vector3.up * m_heave, m_tilt * restWorld);
            HasValidSample = true;
            LastValidRealtime = Time.realtimeSinceStartup;
            LastQueryFailure = "";
        }

        public static Vector3 NormalFromHeights(float left, float right, float back, float front, float radius)
        {
            if (radius <= 0)
                throw new ArgumentOutOfRangeException(nameof(radius));
            return new Vector3(-(right - left) / (2 * radius), 1, -(front - back) / (2 * radius)).normalized;
        }

        public static Vector3 ClampNormal(Vector3 normal, float maxTiltDeg)
        {
            normal = normal.normalized;
            float angle = Mathf.Clamp(maxTiltDeg, 0, 60) * Mathf.Deg2Rad;
            if (normal.y >= Mathf.Cos(angle))
                return normal;
            Vector3 horizontal = new Vector3(normal.x, 0, normal.z).normalized;
            return horizontal * Mathf.Sin(angle) + Vector3.up * Mathf.Cos(angle);
        }

        public static float ResponseBlend(float rate, float deltaTime) => 1 - Mathf.Exp(-rate * Mathf.Max(0, deltaTime));
        static bool Finite(float value) => !float.IsNaN(value) && !float.IsInfinity(value);
    }
}
