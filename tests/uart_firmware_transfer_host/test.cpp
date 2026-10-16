#include "firmware_transfer_client.h"
#include "pw_stream/memory_stream.h"
#include "pw_transfer/internal/chunk.h"
#include <cassert>
#include <chrono>
#include <cstring>
#include <iostream>
#include <mutex>
#include <string>
#include <thread>
static std::mutex outputMutex;
static std::deque<std::vector<uint8_t>> replies;
static std::vector<uint8_t> image, flash;
static bool armed = true, crcValid = true, failWrite = false;
static uint32_t programmed, writeCalls, verifyCalls;
static std::thread::id ioOwner;
extern "C" int PW_UartFirmwareTransfer_Send(const uint8_t *p, size_t n) {
    std::lock_guard<std::mutex> lock(outputMutex);
    replies.emplace_back(p, p + n);
    return 1;
}
extern "C" int PW_UartFirmwareTransfer_Port(uint32_t op, uint32_t offset, const uint8_t *p,
                                            size_t n, uint32_t *value) {
    assert(std::this_thread::get_id() == ioOwner); // no Flash calls from the transfer worker
    if (!armed)
        return 0;
    if (op == UART_FW_PREPARE) {
        *value = image.size();
        return programmed == 0;
    }
    if (op == UART_FW_WRITE) {
        ++writeCalls;
        if (failWrite || offset != programmed || offset + n > image.size() ||
            (n != 32 && offset + n != image.size()))
            return 0;
        std::memcpy(flash.data() + offset, p, n);
        programmed += n;
        return 1;
    }
    if (op == UART_FW_COMPARE)
        return offset <= programmed && n <= programmed - offset &&
               !std::memcmp(flash.data() + offset, p, n);
    if (op == UART_FW_VERIFY) {
        ++verifyCalls;
        return crcValid && programmed == image.size() && flash == image;
    }
    return 0;
}
static UartFirmwareTransferDiagnostics diag() {
    UartFirmwareTransferDiagnostics d{};
    PW_UartFirmwareTransfer_GetDiagnostics(&d);
    return d;
}
static bool popReply(std::vector<uint8_t> &p) {
    std::lock_guard<std::mutex> lock(outputMutex);
    if (replies.empty())
        return false;
    p = std::move(replies.front());
    replies.pop_front();
    return true;
}
static void close() {
    assert(PW_UartFirmwareTransfer_Close());
    PW_UartFirmwareTransfer_Service();
    assert(!diag().busy);
}
static void wireGuards() {
    uint8_t out[2]{};
    assert(PW_UartFirmwareTransfer_Unhex("A001", out, 2) == 2 && out[0] == 0xA0 && out[1] == 1);
    assert(!PW_UartFirmwareTransfer_Unhex("A", out, 2));
    assert(!PW_UartFirmwareTransfer_Unhex("XX", out, 2));
    assert(!PW_UartFirmwareTransfer_Unhex("a0", out, 2));
    assert(!PW_UartFirmwareTransfer_Unhex("A001FF", out, 2));
    using B = std::byte;
    const std::array<B, 9> start{B{0x50}, B{1}, B{0x58}, B{2}, B{0x68}, B{2}, B{0x70}, B{1}, B{0}};
    assert(uart_fw::validChunk(pw::ConstByteSpan(start.data(), 8)));
    assert(!uart_fw::validChunk(start)); // field zero
    const B wrongResource[]{B{0x50}, B{1}, B{0x58}, B{1}, B{0x68}, B{2}, B{0x70}, B{1}};
    assert(!uart_fw::validChunk(wrongResource));
    const B duplicated[]{B{0x50}, B{0}, B{0x50}, B{0}, B{0x60}, B{1}};
    assert(!uart_fw::validChunk(duplicated));
    const B tooLargeOffset[]{B{0x50}, B{0}, B{0x60}, B{1}, B{0x28}, B{0xff}, B{0xff}, B{0x7f}};
    assert(!uart_fw::validChunk(tooLargeOffset));
}
int main(int argc, char **argv) {
    assert(argc == 2);
    const std::string test = argv[1];
    wireGuards();
    ioOwner = std::this_thread::get_id();
    size_t size = test == "full" ? UART_FW_CAPACITY : test == "tail" ? 65 : 256;
    image.resize(size);
    for (size_t i = 0; i < size; ++i)
        image[i] = uint8_t(i * 37 + 19);
    flash.assign(size, 255);
    PW_UartFirmwareTransfer_Init();
    std::thread server([] { PW_UartFirmwareTransfer_Run(); });
    crcValid = test != "wrong_crc";
    failWrite = test == "write_failure";
    armed = test != "not_prepared";
    {
        pw::stream::MemoryReader reader(
            pw::ConstByteSpan(reinterpret_cast<const std::byte *>(image.data()), size));
        FirmwareTransferClient client(reader);
        assert(client.begin());
        auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(35);
        bool dropped = false, injected = false, cancelled = false;
        while (!client.done() && std::chrono::steady_clock::now() < deadline) {
            PW_UartFirmwareTransfer_Service();
            std::vector<uint8_t> p;
            while (client.pop(p)) {
                auto packet = pw::rpc::internal::Packet::FromBuffer(
                    pw::ConstByteSpan(reinterpret_cast<const std::byte *>(p.data()), p.size()));
                assert(packet.ok());
                auto chunk = pw::transfer::internal::Chunk::Parse(packet->payload());
                if (test == "local_only" || test == "not_prepared") {
                    assert(!PW_UartFirmwareTransfer_Process(p.data(), p.size(),
                                                            test == "not_prepared"));
                    assert(programmed == 0 && writeCalls == 0);
                    // malformed/non-local requests cannot reserve an upgrade.
                    assert(!diag().busy);
                    cancelled = true;
                    break;
                }
                if (test == "drop_data" && !dropped && chunk.ok() &&
                    chunk->type() == pw::transfer::internal::Chunk::Type::kData) {
                    dropped = true;
                    continue;
                }
                assert(PW_UartFirmwareTransfer_Process(p.data(), p.size(), 1));
                if (test == "malformed" && !injected &&
                    packet->type() == pw::rpc::internal::pwpb::PacketType::REQUEST) {
                    using P = pw::rpc::internal::Packet;
                    using T = pw::rpc::internal::pwpb::PacketType;
                    assert(!PW_UartFirmwareTransfer_Process(p.data(), p.size(),
                                                            1)); // no stream reopening
                    for (auto payload : {std::vector<std::byte>{std::byte{0x60}, std::byte{1}},
                                         std::vector<std::byte>{std::byte{0x60}, std::byte{1},
                                                                std::byte{0x50}, std::byte{4}}}) {
                        std::array<std::byte, 96> encoded{};
                        P bad(T::CLIENT_STREAM, UART_FW_CHANNEL, uart_fw::service, uart_fw::write,
                              packet->call_id(), pw::ConstByteSpan(payload.data(), payload.size()));
                        auto e = bad.Encode(encoded);
                        assert(e.ok());
                        assert(!PW_UartFirmwareTransfer_Process(
                            reinterpret_cast<const uint8_t *>(e->data()), e->size(), 1));
                    }
                    std::array<std::byte, 96> encoded{};
                    P read(T::REQUEST, UART_FW_CHANNEL, uart_fw::service,
                           pw::rpc::internal::Hash("Read"), 99, {});
                    auto e = read.Encode(encoded);
                    assert(e.ok());
                    assert(!PW_UartFirmwareTransfer_Process(
                        reinterpret_cast<const uint8_t *>(e->data()), e->size(), 1));
                    P wrongCall(T::CLIENT_STREAM, UART_FW_CHANNEL, uart_fw::service, uart_fw::write,
                                packet->call_id() + 1, {});
                    e = wrongCall.Encode(encoded);
                    assert(e.ok());
                    assert(!PW_UartFirmwareTransfer_Process(
                        reinterpret_cast<const uint8_t *>(e->data()), e->size(), 1));
                    injected = true;
                }
            }
            if (cancelled)
                break;
            if (test == "close_active" && diag().phase == UART_FW_RECEIVING) {
                close();
                cancelled = true;
                break;
            }
            while (popReply(p)) {
                if (test == "drop_reply" && !dropped) {
                    dropped = true;
                    continue;
                }
                assert(client.receive(p.data(), p.size()));
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(test == "full" ? 0 : 1));
        }
        if (!cancelled) {
            assert(client.done());
            PW_UartFirmwareTransfer_Service();
            if (test == "wrong_crc" || test == "write_failure") {
                assert(client.status() != 0 && diag().phase == UART_FW_FAILED);
            } else {
                assert(client.status() == 0 && diag().phase == UART_FW_COMPLETE);
                assert(flash == image && programmed == size && verifyCalls == 1);
                assert(writeCalls == (size + 31) / 32);
            }
            if (test == "drop_data" || test == "drop_reply")
                assert(dropped);
            if (test == "malformed")
                assert(injected && diag().rejected >= 5);
            close();
        }
    }
    close();
    PW_UartFirmwareTransfer_Stop();
    server.join();
    std::cout << "PASS " << test << " programmed=" << programmed << " writes=" << writeCalls
              << '\n';
}
