#define PW_LOG_TOKENIZED_FORMAT_STRING(module,message) message
#include "speed_accel_audit_log.cc"
#include <cassert>
#include <cstdio>
extern "C" void pw_log_tokenized_HandleLog(uint32_t,const uint8_t data[],size_t size)
{
    assert(size>=4 && size<=32);std::printf("%zu ",size);
    for(size_t i=0;i<size;++i) std::printf("%02x",data[i]);
    std::puts("");
}
int main()
{
    SpeedAccelAuditFrame f{};f.seq=f.ms=f.trajectory_update=f.trajectory_phase=f.flags=UINT32_MAX;
    f.speed_ref=240;f.speed_meas=230;f.speed_error=10;f.accel_ref=200;f.dt_s=.001f;
    f.iq_pi=.12f;f.iq_acc_ff=.0375f;f.iq_fric=.105f;f.iq_raw=f.iq_cmd=.2625f;f.integrator=.1f;
    SpeedAccelAudit_Log(&f);
}
