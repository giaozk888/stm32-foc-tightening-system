/* Exercise the actual two-message frontend and official 32-byte codec. */
#define PW_LOG_TOKENIZED_FORMAT_STRING(module, message) message
#include "speed_accel_feedforward_log.cc"
#include <cassert>
#include <cstdio>
#include <cstdint>
extern "C" void pw_log_tokenized_HandleLog(uint32_t, const uint8_t data[],size_t size)
{
    assert(size>=4 && size<=32);
    std::printf("%zu ",size);
    for(size_t i=0;i<size;++i) std::printf("%02x",data[i]);
    std::puts("");
}
int main()
{
    SpeedAccelFfFrame f{};
    f.seq=UINT32_MAX; f.ms=UINT32_MAX; f.enabled=1; f.saturated=1;
    f.command_rpm=240; f.speed_ref_rpm=123.25f; f.speed_meas_rpm=-12.5f;
    f.accel_ref_rpm_s=-200; f.iq_pi_a=-.25f; f.iq_ff_a=-.0375f;
    f.iq_raw_a=-.2875f; f.iq_ref_a=-.2875f; f.speed_integrator_a=-.1f;
    SpeedAccelFf_Log(&f);
}
