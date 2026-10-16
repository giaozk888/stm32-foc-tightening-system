#include "firmware_transfer_client.h"
#include "pw_stream/memory_stream.h"
#include <chrono>
#include <fstream>
#include <iostream>
#include <iterator>
#include <string>
int main(int argc, char **argv) {
    if (argc != 2) {
        std::cerr << "Usage: firmware_transfer_client IMAGE (stdin RPC/TICK)\n";
        return 2;
    }
    std::ifstream file(argv[1], std::ios::binary);
    if (!file)
        return 2;
    std::vector<char> image((std::istreambuf_iterator<char>(file)), {});
    if (image.size() < 8 || image.size() > UART_FW_CAPACITY)
        return 2;
    pw::stream::MemoryReader reader(
        pw::ConstByteSpan(reinterpret_cast<const std::byte *>(image.data()), image.size()));
    FirmwareTransferClient client(reader);
    if (!client.begin())
        return 3;
    auto start = std::chrono::steady_clock::now();
    std::string line;
    while (std::getline(std::cin, line)) {
        if (line.rfind("RPC ", 0) == 0) {
            uint8_t bytes[UART_FW_PACKET];
            size_t n = PW_UartFirmwareTransfer_Unhex(line.c_str() + 4, bytes, sizeof(bytes));
            if (n)
                (void)client.receive(bytes, n);
        }
        std::vector<uint8_t> packet;
        while (client.pop(packet)) {
            static constexpr char hex[] = "0123456789ABCDEF";
            std::cout << "RPC ";
            for (auto b : packet)
                std::cout << hex[b >> 4] << hex[b & 15];
            std::cout << std::endl;
        }
        if (client.done()) {
            std::cout << "RESULT " << (client.status() == 0 ? "OK" : "ERROR") << " "
                      << client.status() << std::endl;
            return client.status() == 0 ? 0 : 4;
        }
        if (std::chrono::steady_clock::now() - start > std::chrono::minutes(15))
            return 5;
    }
    return 6;
}
