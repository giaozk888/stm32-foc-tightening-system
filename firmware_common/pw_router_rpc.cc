#include "pw_router_rpc.h"
#include "rpc_readonly.h"
#include "pw_rpc/channel.h"
#include "pw_rpc/server.h"
#include "pw_rpc/service.h"
#include "pw_rpc/raw/internal/method.h"
#include "pw_rpc/raw/internal/method_union.h"
#include "pw_rpc/raw/server_reader_writer.h"
#include "pw_rpc/internal/hash.h"
#include <array>
#include <cstring>

namespace router_rpc {
static_assert(RN_RPC_SERVICE == pw::rpc::internal::Hash("foc.ReadOnly"));
static_assert(RN_RPC_PING == pw::rpc::internal::Hash("Ping"));
static_assert(RN_RPC_STATUS == pw::rpc::internal::Hash("GetStatus"));
static_assert(RN_RPC_PARAMS == pw::rpc::internal::Hash("GetParams"));
static_assert(RN_RPC_DIAGNOSTICS == pw::rpc::internal::Hash("GetDiagnostics"));
static_assert(RPC_READONLY_STATUS_WORDS*4U == 32U && RPC_READONLY_PARAMS_WORDS*4U == 76U &&
              RPC_READONLY_DIAG_WORDS*4U == 40U, "Update wire whitelist before changing snapshot ABI");
class Output final : public pw::rpc::ChannelOutput {
 public:
  Output() : ChannelOutput("router-readonly-hex") {}
  size_t MaximumTransmissionUnit() override { return RN_RPC_MAX_PACKET; }
  pw::Status Send(pw::ConstByteSpan bytes) override {
    char text[225];
    if (!rn_rpc_hex(reinterpret_cast<const uint8_t*>(bytes.data()),bytes.size(),text,sizeof(text)) ||
        !rn_rpc_allowed(1,peer,text)) return pw::Status::InvalidArgument();
    return Router_SendText(peer,RN_RPC_TYPE,text,nullptr) ? pw::OkStatus() : pw::Status::Unavailable();
  }
  uint16_t peer=0;
  uint8_t port=0;
  uint32_t epoch=0, last=0;
};
template <typename Impl> class ServiceBase : public pw::rpc::Service {
 public:
  ServiceBase() : Service(RN_RPC_SERVICE,methods) {}
 private:
  static constexpr std::array<pw::rpc::internal::RawMethodUnion,4> methods = {
    pw::rpc::internal::RawMethod::AsynchronousUnary<&Impl::Ping>(RN_RPC_PING),
    pw::rpc::internal::RawMethod::AsynchronousUnary<&Impl::Status>(RN_RPC_STATUS),
    pw::rpc::internal::RawMethod::AsynchronousUnary<&Impl::Params>(RN_RPC_PARAMS),
    pw::rpc::internal::RawMethod::AsynchronousUnary<&Impl::Diagnostics>(RN_RPC_DIAGNOSTICS)};
};
class Service final : public ServiceBase<Service> {
 public:
  void Ping(pw::ConstByteSpan request,pw::rpc::RawUnaryResponder& reply) {
    static constexpr char alive[]="ROUTER_RPC_ALIVE";
    reply.Finish(request.empty() ? pw::ConstByteSpan(reinterpret_cast<const std::byte*>(alive),sizeof(alive)-1) : request,
                 pw::OkStatus()).IgnoreError();
  }
  void Status(pw::ConstByteSpan,pw::rpc::RawUnaryResponder& r) { Snapshot(1,r); }
  void Params(pw::ConstByteSpan,pw::rpc::RawUnaryResponder& r) { Snapshot(2,r); }
  void Diagnostics(pw::ConstByteSpan,pw::rpc::RawUnaryResponder& r) { Snapshot(3,r); }
 private:
  void Snapshot(uint32_t kind,pw::rpc::RawUnaryResponder& reply) {
    std::array<uint8_t,RPC_READONLY_PAYLOAD_MAX> data{};
    size_t size=PW_Rpc_ReadOnlySnapshot(kind,data.data(),data.size());
    reply.Finish(pw::ConstByteSpan(reinterpret_cast<const std::byte*>(data.data()),size),
                 size ? pw::OkStatus() : pw::Status::Unavailable()).IgnoreError();
  }
};
Output outputs[4];
pw::rpc::Channel channels[4];
pw::rpc::Server server(channels);
Service service;
bool initialized=false;
}
extern "C" int PW_RouterRpc_Process(const RouterPacket_t *frame,uint32_t now)
{
  using namespace router_rpc;
  if (!frame || frame->type != RN_RPC_TYPE || frame->dst != 1 ||
      frame->length > 224 || std::memchr(frame->payload,'\0',sizeof(frame->payload)) != frame->payload+frame->length ||
      !rn_rpc_allowed(frame->src,frame->dst,frame->payload)) return 0;
  uint8_t bytes[RN_RPC_MAX_PACKET]; rn_rpc_packet_t packet;
  size_t size=rn_rpc_unhex(frame->payload,bytes,sizeof(bytes));
  if (!size || !rn_rpc_decode(bytes,size,&packet) || packet.type != 0) return 0;
  if (!initialized) { server.RegisterService(service); initialized=true; }
  Output *selected=nullptr;
  for (auto& out : outputs) if (out.peer == frame->src) { selected=&out; break; }
  if (!selected) for (auto& out : outputs) if (!out.peer || uint32_t(now-out.last) > 30000U) { selected=&out; break; }
  if (!selected) return 0; // Bounded, no fifth peer allocation or hidden queue.
  if (selected->peer != frame->src || selected->port != uint8_t(frame->ingress_port) ||
      selected->epoch != frame->ingress_epoch) {
    if (selected->peer) server.CloseChannel(RN_RPC_CHANNEL_BASE+selected->peer).IgnoreError();
    selected->peer=frame->src; selected->port=uint8_t(frame->ingress_port); selected->epoch=frame->ingress_epoch;
    if (!server.OpenChannel(packet.channel,*selected).ok()) { selected->peer=0; return 0; }
  }
  selected->last=now;
  return server.ProcessPacket(pw::ConstByteSpan(reinterpret_cast<const std::byte*>(bytes),size)).ok();
}
