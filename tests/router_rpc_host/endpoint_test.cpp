#include "pw_router_rpc.h"
#include "router_network.h"
#include "pw_rpc/client.h"
#include "pw_rpc/raw/client_reader_writer.h"
#include "pw_rpc/internal/packet.h"
#include <cassert>
#include <cstring>
#include <deque>
#include <iostream>
#include <string>
#include <vector>

extern "C" unsigned router_rpc_test_snapshot_calls;
extern "C" uint32_t router_rpc_test_tick;
static std::deque<RouterPacket_t> replies;
static bool fail_transmit=false;
static uint8_t transmit(const RouterPacket_t *packet) {
  if (fail_transmit) return 0;
  replies.push_back(*packet); return 1;
}
class ClientOutput final : public pw::rpc::ChannelOutput {
 public:
  explicit ClientOutput(uint16_t id) : ChannelOutput("host-real-client"),peer(id) {}
  pw::Status Send(pw::ConstByteSpan bytes) override {
    RouterPacket_t f{}; f.src=peer; f.dst=1; f.type=RN_RPC_TYPE; f.ttl=8; f.seq=seq++;
    f.length=static_cast<uint16_t>(rn_rpc_hex(reinterpret_cast<const uint8_t*>(bytes.data()),bytes.size(),f.payload,sizeof(f.payload)));
    char line[321];
    if (!f.length || !Router_EncodeAsciiFrame(&f,line,sizeof(line)) ||
        !Router_SubmitAsciiLine(peer == 5 ? ROUTER_PORT_ESP32 : ROUTER_PORT_UART1,line))
      return pw::Status::Unavailable();
    return pw::OkStatus();
  }
  uint16_t peer,seq=1;
};
static void service()
{
  Router_Service(8); RouterPacket_t frame;
  while (Router_LocalReadPacket(&frame)) assert(PW_RouterRpc_Process(&frame,router_rpc_test_tick));
}
static void deliver(pw::rpc::Client& a,pw::rpc::Client& b)
{
  service();
  while (!replies.empty()) {
    auto f=replies.front(); replies.pop_front();
    if (f.type != RN_RPC_TYPE) continue;
    assert(f.src == 1 && (f.dst == 4 || f.dst == 5));
    uint8_t bytes[RN_RPC_MAX_PACKET]; auto size=rn_rpc_unhex(f.payload,bytes,sizeof(bytes));
    assert(size && rn_rpc_allowed(f.src,f.dst,f.payload));
    assert((f.dst == 4 ? a : b).ProcessPacket(pw::ConstByteSpan(reinterpret_cast<const std::byte*>(bytes),size)).ok());
  }
}
struct Completion {
  size_t expected;
  bool done=false;
};
static auto call(pw::rpc::Client& client,uint16_t peer,uint32_t method,Completion& completion)
{
  return pw::rpc::internal::UnaryResponseClientCall::Start<pw::rpc::RawUnaryReceiver>(
    client,RN_RPC_CHANNEL_BASE+peer,RN_RPC_SERVICE,method,
    [&completion](pw::ConstByteSpan data,pw::Status status) { assert(status.ok() && data.size() == completion.expected); completion.done=true; },
    [](pw::Status) { assert(false); },{});
}
static void peer_request(uint16_t peer,uint16_t sequence,bool accepted,bool response=true)
{
  // Official protobuf encoder, actual Router ingress and genuine server.
  pw::rpc::internal::Packet packet(pw::rpc::internal::pwpb::PacketType::REQUEST,
      RN_RPC_CHANNEL_BASE+peer,RN_RPC_SERVICE,RN_RPC_PING,sequence);
  std::byte bytes[RN_RPC_MAX_PACKET];
  auto encoded=packet.Encode(bytes); assert(encoded.ok());
  ClientOutput output(peer); output.seq=sequence;
  replies.clear(); assert(output.Send(encoded.value()).ok());
  Router_Service(8); RouterPacket_t frame;
  assert(Router_LocalReadPacket(&frame));
  assert(bool(PW_RouterRpc_Process(&frame,router_rpc_test_tick)) == accepted);
  assert(!Router_LocalReadPacket(&frame));
  unsigned count=0;
  for (const auto& reply : replies) if (reply.type == RN_RPC_TYPE) {
    ++count; assert(reply.src == 1 && reply.dst == peer);
    assert(rn_rpc_allowed(reply.src,reply.dst,reply.payload));
  }
  assert(count == unsigned(accepted && response));
}
int main(int argc,char **argv)
{
  assert(Router_Init(1));
  Router_RegisterPortTx(ROUTER_PORT_UART1,transmit);
  Router_RegisterPortTx(ROUTER_PORT_ESP32,transmit);
  if (argc == 2 && std::string(argv[1]) == "--probe") {
    std::string line;
    while (std::getline(std::cin,line)) {
      replies.clear();
      if (rn_line_allowed(line.c_str()) && Router_SubmitAsciiLine(ROUTER_PORT_ESP32,line.c_str())) service();
      bool sent=false;
      for (const auto& f : replies) if (f.type == RN_RPC_TYPE) {
        char text[321]; assert(Router_EncodeAsciiFrame(&f,text,sizeof(text)));
        std::cout << text << std::endl; sent=true;
      }
      if (!sent) std::cout << "REJECT" << std::endl;
    }
    return 0;
  }
  ClientOutput out4(4),out5(5);
  pw::rpc::Channel channels4[]={pw::rpc::Channel::Create<RN_RPC_CHANNEL_BASE+4>(&out4)};
  pw::rpc::Channel channels5[]={pw::rpc::Channel::Create<RN_RPC_CHANNEL_BASE+5>(&out5)};
  pw::rpc::Client client4(channels4),client5(channels5);
  const uint32_t methods[]={RN_RPC_PING,RN_RPC_STATUS,RN_RPC_PARAMS,RN_RPC_DIAGNOSTICS};
  const size_t sizes[]={16,32,76,40};
  for (unsigned i=0; i<4; ++i) {
    Completion done4{sizes[i]},done5{sizes[i]};
    auto a=call(client4,4,methods[i],done4);
    auto b=call(client5,5,methods[i],done5);
    deliver(client4,client5);
    assert(done4.done && done5.done && !a.active() && !b.active());
  }
  assert(router_rpc_test_snapshot_calls == 6);
  Completion c1{16},c2{32},c3{76},c4{40};
  auto call1=call(client4,4,RN_RPC_PING,c1);
  auto call2=call(client4,4,RN_RPC_STATUS,c2);
  auto call3=call(client4,4,RN_RPC_PARAMS,c3);
  auto call4=call(client4,4,RN_RPC_DIAGNOSTICS,c4);
  deliver(client4,client5);
  assert(c1.done && c2.done && c3.done && c4.done);
  assert(!call1.active() && !call2.active() && !call3.active() && !call4.active());
  assert(router_rpc_test_snapshot_calls == 9);
  // Changing this actual Router port epoch closes/reopens only that peer's RPC channel.
  Router_ForgetPort(ROUTER_PORT_UART1);
  Completion resumed{32}; auto resumedCall=call(client4,4,RN_RPC_STATUS,resumed);
  deliver(client4,client5); assert(resumed.done && !resumedCall.active());
  // Invalid packets never reach any service or the textual console.
  const unsigned snapshots=router_rpc_test_snapshot_calls;
  RouterPacket_t invalid{}; invalid.src=4; invalid.dst=1; invalid.type=RN_RPC_TYPE;
  invalid.ttl=8; std::strcpy(invalid.payload,"RPC 08021001"); invalid.length=12;
  assert(!PW_RouterRpc_Process(&invalid,0));
  std::strcpy(invalid.payload,"FW END"); invalid.length=6;
  assert(!PW_RouterRpc_Process(&invalid,0));
  assert(router_rpc_test_snapshot_calls == snapshots);
  // Existing peers 4/5 plus 6/7 fill all four static channels.
  peer_request(6,1,true); peer_request(7,1,true);
  peer_request(8,1,false);
  router_rpc_test_tick=30000;
  peer_request(8,2,false); // Exact idle boundary is not eligible for eviction.
  router_rpc_test_tick=30001;
  peer_request(8,3,true);
  fail_transmit=true; peer_request(8,4,true,false);
  fail_transmit=false; peer_request(8,5,true); // No hidden retry of failed reply.
  assert(router_rpc_test_snapshot_calls == snapshots);
  std::cout << "PASS: genuine Client/Server + actual Router; 4 methods x 2 peers, epoch, four-channel cap/idle eviction, TX failure, fail-closed input" << std::endl;
}
