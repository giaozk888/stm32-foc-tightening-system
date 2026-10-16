#ifndef ROUTER_NATIVE_TRANSFER_CLIENT_H
#define ROUTER_NATIVE_TRANSFER_CLIENT_H
#include "pw_router_transfer.h"
#include "pw_rpc/client.h"
#include "pw_stream/memory_stream.h"
#include "pw_transfer/client.h"
#include <atomic>
#include <deque>
#include <mutex>
#include <thread>

/* Host-side upstream Client/TransferThread; adapter owns all Router I/O.
 * Thread callbacks enqueue bounded owned frames, never operate the serial port. */
class RouterTransferClient {
  public:
    explicit RouterTransferClient(uint16_t peer);
    ~RouterTransferClient();
    bool begin(uint32_t resource);
    bool pop(RouterPacket_t &frame);
    bool receive(const RouterPacket_t &frame, uint32_t now);
    bool done();
    bool success() const {
        return terminal.load() == 0 && ackSeen;
    }
    pw::ConstByteSpan data() const {
        return writer.WrittenData();
    }

  private:
    class Output final : public pw::rpc::ChannelOutput {
      public:
        explicit Output(RouterTransferClient &parent)
            : ChannelOutput("router-transfer-client"), parent(parent) {}
        size_t MaximumTransmissionUnit() override {
            return 128;
        }
        pw::Status Send(pw::ConstByteSpan bytes) override;

      private:
        RouterTransferClient &parent;
    } output;
    uint16_t peer, sequence = 1;
    uint32_t packetId = 1;
    uint32_t lastSentMs = 0;
    bool hasSent = false;
    std::mutex mutex;
    std::deque<RouterPacket_t> queue;
    pw::rpc::Channel channels[1];
    pw::rpc::Client rpc;
    std::array<std::byte, 96> chunk{};
    std::array<std::byte, 128> encode{};
    pw::transfer::Thread<1, 0> thread;
    pw::transfer::Client transfer;
    pw::stream::MemoryWriterBuffer<3056> writer;
    std::atomic<int> terminal{-1};
    std::atomic<uint32_t> call{0}, completionSession{0};
    bool ackSeen = false;
    rn_transfer_receiver_t receiver{};
    std::thread worker;
};
#endif
