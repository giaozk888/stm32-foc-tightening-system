#include "router_rpc_wire.h"
#include <string.h>

static bool varint(const uint8_t *data, size_t size, size_t *pos, uint32_t *out)
{
    *out = 0;
    for (unsigned n=0; n<5; ++n) {
        if (*pos == size) return false;
        uint8_t value = data[(*pos)++];
        if (n == 4 && (value & 0xF0U)) return false;
        *out |= (uint32_t)(value & 127U) << (7U*n);
        if (!(value & 128U)) return true;
    }
    return false;
}
bool rn_rpc_decode(const uint8_t *data, size_t size, rn_rpc_packet_t *out)
{
    if (!data || !out || !size || size > RN_RPC_MAX_PACKET) return false;
    rn_rpc_packet_t p = {0}; size_t pos=0; unsigned seen=0;
    while (pos < size) {
        uint32_t key, value=0;
        if (!varint(data,size,&pos,&key)) return false;
        unsigned field=key >> 3, wire=key & 7U;
        if (!field || field > 7 || (seen & (1U << field))) return false;
        seen |= 1U << field;
        if (field == 3 || field == 4) {
            if (wire != 5 || size-pos < 4) return false;
            for (unsigned n=0; n<4; ++n) value |= (uint32_t)data[pos++] << (8U*n);
        } else if (field == 5) {
            if (wire != 2 || !varint(data,size,&pos,&value) || value > size-pos) return false;
            p.payload=data+pos; p.payload_size=value; pos+=value;
        } else if (wire != 0 || !varint(data,size,&pos,&value)) return false;
        switch (field) {
        case 1: p.type=value; break;
        case 2: p.channel=value; break;
        case 3: p.service=value; break;
        case 4: p.method=value; break;
        case 6: p.status=value; break;
        case 7: p.call=value; break;
        default: break;
        }
    }
    if ((seen & 0x9CU) != 0x9CU || !p.call) return false;
    *out=p; return true;
}
static int nibble(char c)
{
    if (c >= '0' && c <= '9') return c-'0';
    if (c >= 'A' && c <= 'F') return c-'A'+10;
    return -1; /* One canonical wire representation. */
}
size_t rn_rpc_unhex(const char *text, uint8_t *out, size_t capacity)
{
    if (!text || !out || strncmp(text,"RPC ",4)) return 0;
    size_t length=0;
    while (length <= 2U*RN_RPC_MAX_PACKET && text[4U+length]) ++length;
    if (!length || length > 2U*RN_RPC_MAX_PACKET || (length & 1U) || length/2 > capacity) return 0;
    for (size_t i=0; i<length/2; ++i) {
        int hi=nibble(text[4U+2*i]), lo=nibble(text[5U+2*i]);
        if (hi < 0 || lo < 0) return 0;
        out[i]=(uint8_t)((unsigned)hi*16U+(unsigned)lo);
    }
    return length/2;
}
size_t rn_rpc_hex(const uint8_t *data, size_t size, char *out, size_t capacity)
{
    if (!data || !out || !size || size > RN_RPC_MAX_PACKET || capacity < 5U+2U*size) return 0;
    static const char digits[]="0123456789ABCDEF";
    memcpy(out,"RPC ",4);
    for (size_t i=0; i<size; ++i) {
        out[4U+2*i]=digits[data[i] >> 4]; out[5U+2*i]=digits[data[i] & 15U];
    }
    out[4U+2U*size]='\0'; return 4U+2U*size;
}
bool rn_rpc_allowed(uint16_t src, uint16_t dst, const char *text)
{
    if (!src || src == 65535U || !dst || dst == 65535U) return false;
    uint8_t bytes[RN_RPC_MAX_PACKET]; rn_rpc_packet_t p;
    size_t size=rn_rpc_unhex(text,bytes,sizeof(bytes));
    if (!size || !rn_rpc_decode(bytes,size,&p) || p.service != RN_RPC_SERVICE) return false;
    size_t expected;
    switch (p.method) {
    case RN_RPC_PING: expected=16; break;
    case RN_RPC_STATUS: expected=32; break;
    case RN_RPC_PARAMS: expected=76; break;
    case RN_RPC_DIAGNOSTICS: expected=40; break;
    default: return false;
    }
    if (p.type == 0) return dst == 1 && src != 1 && !p.status &&
        p.channel == RN_RPC_CHANNEL_BASE+src &&
        (p.method == RN_RPC_PING ? p.payload_size <= 16 : p.payload_size == 0);
    if (src != 1 || dst == 1 || p.channel != RN_RPC_CHANNEL_BASE+dst || p.status > 16) return false;
    if (p.type == 5) return p.status != 0 && p.payload_size == 0;
    return p.type == 1 && (p.status ? p.payload_size == 0 :
        (p.method == RN_RPC_PING ? p.payload_size <= expected : p.payload_size == expected));
}
