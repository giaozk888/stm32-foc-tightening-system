#ifndef FIRMWARE_TRANSFER_CLIENT_H
#define FIRMWARE_TRANSFER_CLIENT_H
#include "uart_firmware_transfer_wire.h"
#include "pw_rpc/client.h"
#include "pw_transfer/client.h"
#include <array>
#include <atomic>
#include <deque>
#include <mutex>
#include <thread>
#include <vector>
class FirmwareTransferClient {
  public:
    explicit FirmwareTransferClient(pw::stream::Reader &input);
    ~FirmwareTransferClient();
    bool begin();
    bool pop(std::vector<uint8_t> &packet);
    bool receive(const uint8_t *data, size_t size);
    bool done();
    int status() const {
        return terminal.load();
    }

  private:
    class Output final : public pw::rpc::ChannelOutput {
      public:
        explicit Output(FirmwareTransferClient &p) : ChannelOutput("uart-fw-host"), parent(p) {}
        size_t MaximumTransmissionUnit() override {
            return UART_FW_PACKET;
        }
        pw::Status Send(pw::ConstByteSpan data) override;

      private:
        FirmwareTransferClient &parent;
    } output;
    pw::stream::Reader &reader;
    std::array<std::byte, UART_FW_PACKET> chunk{}, encode{};
    pw::rpc::Channel channels[1];
    pw::rpc::Client rpc;
    pw::transfer::Thread<1, 0> thread;
    pw::transfer::Client transfer;
    std::mutex mutex;
    std::deque<std::vector<uint8_t>> queue;
    std::atomic<int> terminal{-1};
    std::atomic<uint32_t> call{0};
    std::atomic<bool> ackQueued{false};
    std::thread worker;
};
#endif
