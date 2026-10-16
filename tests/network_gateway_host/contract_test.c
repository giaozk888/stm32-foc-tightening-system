#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "network_v1.h"
#include "modbus_ro.h"
#include "router_frame.h"

static void protocol_test(void)
{
    assert(net_crc32("123456789", 9) == UINT32_C(0xcbf43926));
    net_sample_t s = {.seq = UINT32_MAX, .uptime_ms = UINT32_MAX, .run = UINT32_MAX,
        .cycle = 5, .stage = 11, .outcome = 6, .flags = 127, .fault = UINT16_MAX,
        .position_cdeg = INT32_MIN, .speed_drpm = INT32_MAX, .iq_ma = -100,
        .vbus_mv = 100000, .vbus_quality = 31, .contact_cdeg = INT32_MIN,
        .post_cdeg = INT32_MAX, .kind = 1}, parsed;
    char text[225];
    size_t n = net_sample_format(&s, text, sizeof(text));
    assert(n && n <= 224 && net_sample_parse(text, &parsed));
    assert(parsed.seq == s.seq && parsed.position_cdeg == s.position_cdeg &&
           parsed.post_cdeg == s.post_cdeg && parsed.kind == 1);
    assert(net_sample_format(&s, text, 5) == 0);
    n = net_sample_format(&s, text, sizeof(text));
    text[6] ^= 1; assert(!net_sample_parse(text, &parsed));
    text[6] ^= 1; text[n] = ' '; text[n+1] = 0; assert(!net_sample_parse(text, &parsed));
    assert(!net_sample_parse(NULL, &parsed));
    s.kind = 2; assert(!net_sample_valid(&s));
    s.kind = 1; s.run = 0; assert(!net_sample_valid(&s));
    s.kind = 0; s.vbus_mv = 100001; assert(!net_sample_valid(&s));
    s.vbus_mv = 12000; s.vbus_quality = 32; assert(!net_sample_valid(&s));
    s.vbus_quality = 1; assert(net_sample_format(&s, text, sizeof(text)));
    router_frame_t f = {.src=1, .dst=2, .type=2, .seq=1, .ttl=8}, got;
    strcpy(f.payload, text); f.length = (uint16_t)strlen(text);
    char line[321]; assert(router_frame_format(&f, line, sizeof(line)));
    assert(router_frame_parse(line, &got)); assert(net_sample_parse(got.payload, &parsed));
    for (unsigned i=0; i<1000; ++i) {
        s.seq=i; s.position_cdeg=(int32_t)i*321-12345;
        assert(net_sample_format(&s, text, sizeof(text)));
        assert(net_sample_parse(text, &parsed));
        assert(parsed.position_cdeg == s.position_cdeg);
    }
}
static void modbus_test(void)
{
    uint8_t q[12] = {0x12,0x34,0,0,0,6,1,4,0,0,0,40}, r[260];
    mb_observation_t s = {.available=true, .wifi=true, .age_ms=5,
        .sample={.position_cdeg=-12345, .speed_drpm=123, .vbus_quality=1}, .uploaded=300};
    size_t n=mb_readonly_reply(q,12,&s,r,sizeof(r));
    assert(n == 89 && r[0]==0x12 && r[1]==0x34 && r[8]==80);
    assert(r[13]==0 && r[14]==0); /* Register 2: no control. */
    assert(r[45]==0xff && r[46]==0xff && r[47]==0xcf && r[48]==0xc7);
    assert(r[69]==0 && r[70]==0 && r[71]==1 && r[72]==44);
    for(unsigned fc=0;fc<256;++fc) if(fc!=4) {
        q[7]=(uint8_t)fc; n=mb_readonly_reply(q,12,&s,r,sizeof(r));
        assert(n==9 && r[7]==(uint8_t)(fc|0x80) && r[8]==1);
    }
    q[7]=4; s.age_ms=3001;
    assert(mb_readonly_reply(q,12,&s,r,sizeof(r))==9 && r[8]==4);
    q[11]=8; assert(mb_readonly_reply(q,12,&s,r,sizeof(r))==25); /* Gateway status remains queryable. */
    q[11]=0; assert(mb_readonly_reply(q,12,&s,r,sizeof(r))==9 && r[8]==3);
    q[11]=1; q[9]=40; assert(mb_readonly_reply(q,12,&s,r,sizeof(r))==9 && r[8]==2);
    q[9]=0; q[3]=1; assert(!mb_readonly_reply(q,12,&s,r,sizeof(r)));
    q[3]=0; q[6]=2; assert(!mb_readonly_reply(q,12,&s,r,sizeof(r)));
    q[6]=1; q[5]=5; assert(!mb_readonly_reply(q,12,&s,r,sizeof(r)));
    q[5]=6; assert(!mb_readonly_reply(q,12,&s,r,8));
    assert(!mb_readonly_reply(q,7,&s,r,sizeof(r)));
    srand(17);
    for (unsigned i=0;i<10000;++i) {
        uint8_t noise[260]; for(unsigned j=0;j<260;++j)noise[j]=(uint8_t)rand();
        n=mb_readonly_reply(noise,(size_t)(rand()%261),&s,r,sizeof(r));
        assert(n <= sizeof(r));
    }
}
int main(void) { protocol_test(); modbus_test(); puts("NET1 CRC/ranges/router and read-only Modbus contracts PASS"); return 0; }
