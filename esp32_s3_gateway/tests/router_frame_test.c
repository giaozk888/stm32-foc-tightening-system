#include <assert.h>
#include <string.h>

#include "router_frame.h"

int main(void)
{
    router_frame_t packet;
    char output[ROUTER_FRAME_MAX_LINE];

    assert(router_frame_parse("@R1 2 65535 3 1 8 5 HELLO", &packet));
    assert(packet.src == 2U && packet.dst == 65535U);
    assert(packet.type == 3U && packet.seq == 1U && packet.ttl == 8U);
    assert(strcmp(packet.payload, "HELLO") == 0);
    assert(router_frame_format(&packet, output, sizeof(output)) != 0U);
    assert(strcmp(output, "@R1 2 65535 3 1 8 5 HELLO") == 0);

    assert(router_frame_parse("@R1 1 2 1 42 8 9 2000 PING", &packet));
    assert(strcmp(packet.payload, "2000 PING") == 0);
    assert(!router_frame_parse("@R1 1 2 1 42 0 9 2000 PING", &packet));
    assert(!router_frame_parse("@R1 1 2 1 42 8 8 2000 PING", &packet));
    assert(!router_frame_parse("@R1 1 2 1 42 8 225 X", &packet));
    assert(!router_frame_parse("@R1 1 2 1 42 8 9 2000 PING extra", &packet));
    assert(!router_frame_parse("@R1 -1 2 1 42 8 5 HELLO", &packet));
    assert(router_frame_format(&packet, output, 2U) == 0U);
    return 0;
}
