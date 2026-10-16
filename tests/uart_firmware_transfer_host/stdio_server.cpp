// Offline UART adapter for the actual firmware transfer module. RAM stands in for Flash.
#include "uart_firmware_transfer.h"
#include <atomic>
#include <cassert>
#include <chrono>
#include <cstring>
#include <deque>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <iterator>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <vector>
static std::vector<uint8_t> image, flash;
static std::mutex outputMutex, inputMutex;
static std::deque<std::string> input;
static std::atomic<bool> eof{false};
static bool active = false;
static uint32_t programmed = 0;
static std::thread::id ioOwner;
static void emit(const std::string &s) {
    std::lock_guard<std::mutex> lock(outputMutex);
    std::cout << s << std::endl;
}
extern "C" int PW_UartFirmwareTransfer_Send(const uint8_t *p, size_t n) {
    static constexpr char hex[] = "0123456789ABCDEF";
    std::string line = "0 EVT FWTRANSFER RPC ";
    for (size_t i = 0; i < n; ++i) {
        line += hex[p[i] >> 4];
        line += hex[p[i] & 15];
    }
    emit(line);
    return 1;
}
extern "C" int PW_UartFirmwareTransfer_Port(uint32_t op, uint32_t offset, const uint8_t *p,
                                            size_t n, uint32_t *value) {
    assert(std::this_thread::get_id() == ioOwner);
    if (!active)
        return 0;
    if (op == UART_FW_PREPARE) {
        *value = image.size();
        return programmed == 0;
    }
    if (op == UART_FW_WRITE) {
        if (offset != programmed || offset + n > image.size() ||
            (n != 32 && offset + n != image.size()))
            return 0;
        std::memcpy(flash.data() + offset, p, n);
        programmed += n;
        return 1;
    }
    if (op == UART_FW_COMPARE)
        return offset <= programmed && n <= programmed - offset &&
               !std::memcmp(flash.data() + offset, p, n);
    if (op == UART_FW_VERIFY)
        return programmed == image.size() && flash == image;
    return 0;
}
int main(int argc, char **argv) {
    if (argc != 3)
        return 2;
    std::ifstream file(argv[1], std::ios::binary);
    image.assign(std::istreambuf_iterator<char>(file), {});
    if (image.size() < 8 || image.size() > UART_FW_CAPACITY)
        return 2;
    flash.assign(image.size(), 255);
    ioOwner = std::this_thread::get_id();
    PW_UartFirmwareTransfer_Init();
    std::thread server([] { PW_UartFirmwareTransfer_Run(); });
    std::thread reader([] {
        std::string line;
        while (std::getline(std::cin, line)) {
            if (!line.empty() && line.back() == '\r')
                line.pop_back();
            std::lock_guard<std::mutex> lock(inputMutex);
            if (input.size() >= 32) {
                eof.store(true);
                return;
            }
            input.push_back(line);
        }
        eof.store(true);
    });
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::minutes(3);
    while (!eof.load() && std::chrono::steady_clock::now() < deadline) {
        PW_UartFirmwareTransfer_Service();
        std::string line;
        {
            std::lock_guard<std::mutex> lock(inputMutex);
            if (!input.empty()) {
                line = std::move(input.front());
                input.pop_front();
            }
        }
        if (line.empty()) {
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
            continue;
        }
        const size_t space = line.find(' ');
        if (space == std::string::npos)
            continue;
        const auto id = line.substr(0, space), cmd = line.substr(space + 1);
        if (cmd == "FW STATUS")
            emit(id + " OK FW CURRENT=A CONFIRMED=A TARGET=B PENDING=- ACTIVE=" +
                 (active ? "1" : "0") + " SIZE=" + std::to_string(image.size()) +
                 " RX=" + std::to_string(programmed) + " EXPECT=0x" + argv[2]);
        else if (cmd == "ANALOG SAFE STATUS")
            emit(id + " OK SAFE LATCHED=1 SD=0 MOE=0 FOC=0");
        else if (cmd == "XFER ENGINE STATUS") {
            UartFirmwareTransferDiagnostics d{};
            PW_UartFirmwareTransfer_GetDiagnostics(&d);
            emit(id + " OK FWTRANSFER ENGINE=OFFICIAL READY=" + std::to_string(d.ready) +
                 " BUSY=" + std::to_string(d.busy) + " PHASE=" + std::to_string(d.phase) +
                 " RESULT=" + std::to_string(d.result) + " RX=" + std::to_string(d.received) +
                 " CH=3 RESOURCE=2 MTU=96");
        } else if (cmd.rfind("FW BEGIN ", 0) == 0 && !active) {
            active = true;
            emit(id + " OK FW BEGIN (RAM MOCK)");
        } else if (cmd == "XFER ENGINE CLOSE") {
            PW_UartFirmwareTransfer_Close();
            emit(id + " OK CLOSING");
        } else if (cmd.rfind("XFER ENGINE ", 0) == 0) {
            uint8_t bytes[UART_FW_PACKET];
            size_t n = PW_UartFirmwareTransfer_Unhex(cmd.c_str() + 12, bytes, sizeof(bytes));
            bool ok = n && PW_UartFirmwareTransfer_Process(bytes, n, 1);
            emit(id + (ok ? " OK ACCEPTED" : " ERR REJECTED"));
        } else
            emit(id + " ERR NO_RESET_OR_MOTION_IN_OFFLINE_TEST");
    }
    PW_UartFirmwareTransfer_Close();
    PW_UartFirmwareTransfer_Service();
    PW_UartFirmwareTransfer_Stop();
    server.join();
    reader.join();
    return 0;
}
