using System;
using Unity.Robotics.ROSTCPConnector.MessageGeneration;

namespace Lotusim.Dataset
{
    // Wire schema matches interfaces/lotusim_msgs/srv/String.srv exactly.
    // Service messages share the ROS name; the registry separates responses.
    [Serializable]
    public sealed class DatasetStringRequest : Message
    {
        public const string RosName = "lotusim_msgs/String";
        public override string RosMessageName => RosName;

        public string data = "";
        public DatasetStringRequest()
        {
        }

        public DatasetStringRequest(string value)
        {
            data = value;
        }

        public override void SerializeTo(MessageSerializer serializer)
        {
            serializer.Write(data);
        }

        public static DatasetStringRequest Deserialize(MessageDeserializer d)
        {
            var r = new DatasetStringRequest();
            d.Read(out r.data);
            return r;
        }
    }

    [Serializable]
    public sealed class DatasetStringResponse : Message
    {
        public override string RosMessageName => DatasetStringRequest.RosName;

        public bool success;
        public string message = "";
        public override void SerializeTo(MessageSerializer serializer)
        {
            serializer.Write(success);
            serializer.Write(message);
        }

        public static DatasetStringResponse Deserialize(MessageDeserializer d)
        {
            var r = new DatasetStringResponse();
            d.Read(out r.success);
            d.Read(out r.message);
            return r;
        }
    }

    // ROS 2 empty structs still serialize a dummy uint8. The connector's
    // generated TriggerRequest omits it, producing a header-only CDR payload
    // that Fast DDS cannot deserialize. The extra zeros are trailing padding.
    [Serializable]
    public sealed class DatasetTriggerRequest : Message
    {
        public const string RosName = "std_srvs/Trigger";
        public override string RosMessageName => RosName;

        public override void SerializeTo(MessageSerializer serializer)
        {
            serializer.Write((byte)0);
            serializer.Write((byte)0);
            serializer.Write((byte)0);
            serializer.Write((byte)0);
        }

        public static DatasetTriggerRequest Deserialize(MessageDeserializer d)
        {
            d.Read(out byte ignored);
            return new DatasetTriggerRequest();
        }
    }
}
