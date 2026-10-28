// RGB-only Gazebo Transport boundary. No simulator/scene/pose dependencies.
#include <gz/transport/Node.hh>
#include <gz/msgs/image.pb.h>
#include <atomic>
#include <chrono>
#include <functional>
#include <iostream>
#include <iterator>
#include <string>
#include <thread>

int main(int argc,char **argv)
{
  if(argc!=5){std::cerr<<"usage: relay roundtrip|send|receive /dataset/rgb_observer/topic width height\n";return 2;}
  const std::string mode=argv[1],topic=argv[2];
  if(topic.rfind("/dataset/rgb_observer/",0)!=0||(mode!="roundtrip"&&mode!="send"&&mode!="receive")){std::cerr<<"RGB observer namespace/mode required\n";return 2;}
  const int width=std::stoi(argv[3]),height=std::stoi(argv[4]);
  if(width<1||height<1||width>8192||height>8192){std::cerr<<"invalid dimensions\n";return 2;}
  const size_t size=static_cast<size_t>(width)*height*3;
  std::string input,received;
  if(mode!="receive"){
    input.assign(std::istreambuf_iterator<char>(std::cin),{});
    if(input.size()!=size){std::cerr<<"invalid RGB byte count\n";return 2;}
  }
  gz::transport::Node node;std::atomic<bool> done{false},bad{false};
  std::function<void(const gz::msgs::Image&)> callback=[&](const gz::msgs::Image &image){
    if(done.load())return;
    if(image.width()!=static_cast<unsigned>(width)||image.height()!=static_cast<unsigned>(height)||image.step()!=static_cast<unsigned>(width*3)||image.pixel_format_type()!=gz::msgs::RGB_INT8||image.data().size()!=size){bad=true;done=true;return;}
    received=image.data();done=true;
  };
  if(mode!="send"&&!node.Subscribe(topic,callback)){std::cerr<<"subscribe failed\n";return 3;}
  if(mode!="receive"){
    auto publisher=node.Advertise<gz::msgs::Image>(topic);
    if(!publisher){std::cerr<<"advertise failed\n";return 3;}
    const auto start=std::chrono::steady_clock::now();
    while(!publisher.HasConnections()){
      if(std::chrono::steady_clock::now()-start>std::chrono::seconds(10)){std::cerr<<"no RGB subscriber\n";return 4;}
      std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }
    gz::msgs::Image image;image.set_width(width);image.set_height(height);image.set_step(width*3);image.set_pixel_format_type(gz::msgs::RGB_INT8);image.set_data(input);
    if(!publisher.Publish(image)){std::cerr<<"publish failed\n";return 3;}
    if(mode=="send"){std::this_thread::sleep_for(std::chrono::milliseconds(200));return 0;}
    while(!done&&std::chrono::steady_clock::now()-start<std::chrono::seconds(10))std::this_thread::sleep_for(std::chrono::milliseconds(10));
  }else{
    const auto start=std::chrono::steady_clock::now();
    while(!done&&std::chrono::steady_clock::now()-start<std::chrono::seconds(15))std::this_thread::sleep_for(std::chrono::milliseconds(10));
  }
  if(!done||bad){std::cerr<<"invalid RGB message or timeout\n";return 4;}
  if(mode=="roundtrip"&&input!=received){std::cerr<<"Gazebo RGB pixel mismatch\n";return 5;}
  std::cout.write(received.data(),received.size());
  return 0;
}
