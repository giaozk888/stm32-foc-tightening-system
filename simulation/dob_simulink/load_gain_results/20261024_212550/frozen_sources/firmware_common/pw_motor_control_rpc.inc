#include "motor_rpc_wire.h"
namespace motor_control_rpc {
template <typename Impl> class ServiceBase : public pw::rpc::Service {
  public:
    ServiceBase() : Service(motor_rpc::service, methods) {}

  private:
    static constexpr std::array<pw::rpc::internal::RawMethodUnion, 4> methods = {
        pw::rpc::internal::RawMethod::AsynchronousUnary<&Impl::Arm>(motor_rpc::arm),
        pw::rpc::internal::RawMethod::AsynchronousUnary<&Impl::Start>(motor_rpc::start),
        pw::rpc::internal::RawMethod::AsynchronousUnary<&Impl::Stop>(motor_rpc::stop),
        pw::rpc::internal::RawMethod::AsynchronousUnary<&Impl::Status>(motor_rpc::status)};
};
class Service final : public ServiceBase<Service> {
  public:
    void Arm(pw::ConstByteSpan b, pw::rpc::RawUnaryResponder &r) {
        Handle(MOTOR_RPC_ARM, b, r);
    }
    void Start(pw::ConstByteSpan b, pw::rpc::RawUnaryResponder &r) {
        Handle(MOTOR_RPC_START, b, r);
    }
    void Stop(pw::ConstByteSpan b, pw::rpc::RawUnaryResponder &r) {
        Handle(MOTOR_RPC_STOP, b, r);
    }
    void Status(pw::ConstByteSpan b, pw::rpc::RawUnaryResponder &r) {
        Handle(MOTOR_RPC_STATUS, b, r);
    }

  private:
    void Handle(MotorControlOpcode op, pw::ConstByteSpan bytes, pw::rpc::RawUnaryResponder &r) {
        MotorControlRequest request{MOTOR_CONTROL_VERSION, 0, 0, 0, 0};
        if (op != MOTOR_RPC_STATUS) {
            if (bytes.size() != motor_rpc::requestSize) {
                r.Finish({}, pw::Status::InvalidArgument()).IgnoreError();
                return;
            }
            rpc_readonly::Packet p;
            p.payload = reinterpret_cast<const uint8_t *>(bytes.data());
            p.payload_size = bytes.size();
            request = motor_rpc::request(p);
        } else if (!bytes.empty()) {
            r.Finish({}, pw::Status::InvalidArgument()).IgnoreError();
            return;
        }
        MotorControlReply reply{};
        PW_MotorControl_Invoke(op, &request, &reply);
        std::array<uint8_t, motor_rpc::replySize> buffer{};
        motor_rpc::encodeReply(reply, buffer.data());
        const bool accepted = reply.decision <= MOTOR_RPC_DUPLICATE;
        r.Finish(
             pw::ConstByteSpan(reinterpret_cast<const std::byte *>(buffer.data()), buffer.size()),
             accepted ? pw::OkStatus() : pw::Status::FailedPrecondition())
            .IgnoreError();
    }
};
Service service;
} // namespace motor_control_rpc
