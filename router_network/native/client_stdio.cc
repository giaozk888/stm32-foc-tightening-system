#include "transfer_client.h"
#include "router_network.h"
#include <chrono>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <string>
static uint32_t now() {
    return uint32_t(std::chrono::duration_cast<std::chrono::milliseconds>(
                        std::chrono::steady_clock::now().time_since_epoch())
                        .count());
}
int main(int argc, char **argv) {
    if (argc != 3) {
        std::cerr << "Usage: router_transfer_client NODE RESOURCE (stdin R1/TICK)\n";
        return 2;
    }
    unsigned node = unsigned(std::strtoul(argv[1], nullptr, 10));
    unsigned resource = unsigned(std::strtoul(argv[2], nullptr, 10));
    if (node < 3 || node >= 65535 || (resource != 3 && resource != 4))
        return 2;
    RouterTransferClient client{uint16_t(node)};
    if (!client.begin(resource))
        return 3;
    const uint32_t started = now();
    std::string line;
    while (std::getline(std::cin, line)) {
        rn_frame_t wire{};
        RouterPacket_t f{};
        if (line != "TICK" && rn_parse(line.c_str(), &wire) &&
            rn_allowed(wire.src, wire.dst, wire.type, wire.ttl, wire.payload)) {
            f.src = wire.src;
            f.dst = wire.dst;
            f.type = wire.type;
            f.seq = wire.seq;
            f.ttl = wire.ttl;
            f.length = wire.length;
            std::memcpy(f.payload, wire.payload, wire.length + 1);
            (void)client.receive(f, now());
        }
        while (client.pop(f)) {
            wire = {};
            wire.src = f.src;
            wire.dst = f.dst;
            wire.type = f.type;
            wire.seq = f.seq;
            wire.ttl = f.ttl;
            wire.length = f.length;
            std::memcpy(wire.payload, f.payload, f.length + 1);
            char text[321];
            if (!rn_format(&wire, text, sizeof(text)))
                return 4;
            std::cout << text << std::endl;
        }
        if (client.done()) {
            if (!client.success()) {
                std::cout << "RESULT ERROR\n" << std::flush;
                return 5;
            }
            const auto data = client.data();
            static constexpr char hex[] = "0123456789ABCDEF";
            std::cout << "RESULT OK ";
            for (std::byte byte : data) {
                unsigned value = unsigned(byte);
                std::cout << hex[value >> 4] << hex[value & 15];
            }
            std::cout << std::endl;
            return 0;
        }
        if (uint32_t(now() - started) >= 30000U) {
            std::cout << "RESULT TIMEOUT\n" << std::flush;
            return 6;
        }
    }
    return 7;
}
