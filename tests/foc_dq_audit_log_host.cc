#define PW_LOG_TOKENIZED_FORMAT_STRING(module,message) message
#include "foc_dq_audit_log.cc"
#include <cassert>
#include <cstdio>
extern "C" void pw_log_tokenized_HandleLog(uint32_t,const uint8_t data[],size_t size)
{
    assert(size>=4 && size<=32);
    std::printf("%zu ",size);
    for(size_t i=0;i<size;++i)std::printf("%02x",data[i]);
    std::puts("");
}
int main()
{
    FocDqAuditFrame f{};f.seq=f.us=f.flags=f.elapsed_us=UINT32_MAX;
    f.mech_rpm=-240;f.we_rad_s=-251.3274f;f.id=.1f;f.iq=-.2f;
    f.vd_pi=.01f;f.vq_pi=.02f;f.vd_dec=-.003f;f.vq_dec=.004f;
    f.vd_cmd=.007f;f.vq_cmd=.024f;f.speed_ref=-240;f.speed_meas=-239.5f;
    FocDqAudit_LogFrame(&f);
    FocDqAuditStats s{};
    s.run_n=s.zero_n=s.start_n=s.cruise_n=s.sat_n=s.first_sat_us=UINT32_MAX;
    s.config_bad=s.nominal_d_bad=s.nominal_q_bad=s.invalid_n=UINT32_MAX;
    s.zero_d_max=.00001f;s.zero_q_max=.00002f;s.start_d_max=.001f;s.start_q_max=.002f;
    s.cruise_d_sum=-1;s.cruise_q_sum=2;s.we_abs_max=314.1593f;s.we_chain_error_max=.0001f;
    FocDqAudit_LogStats(&s);
}
