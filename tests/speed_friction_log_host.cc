#define PW_LOG_TOKENIZED_FORMAT_STRING(module,message) message
#include "speed_friction_compensation_log.cc"
#include <cassert>
#include <cstdio>
#include <cstdint>
extern "C" void pw_log_tokenized_HandleLog(uint32_t,const uint8_t data[],size_t size)
{
    assert(size>=4 && size<=32); std::printf("%zu ",size);
    for(size_t i=0;i<size;++i) { std::printf("%02x",data[i]); }
    std::puts("");
}
int main()
{
    SpeedFrictionFrame f{};
    f.control.seq=UINT32_MAX;f.control.ms=UINT32_MAX;f.enabled=1;f.control.enabled=1;
    f.control.saturated=1;f.control.speed_ref_rpm=-240;f.control.speed_meas_rpm=-235;
    f.control.command_rpm=-240;f.control.accel_ref_rpm_s=-200;
    f.control.iq_pi_a=-.3f;f.control.iq_ff_a=-.0375f;f.iq_fric_a=-.2f;
    f.control.iq_raw_a=-.5375f;f.control.iq_ref_a=-.5f;
    f.control.speed_integrator_a=-.1f;f.control.iq_meas_a=-.48f;
    SpeedFriction_Log(&f);
}
