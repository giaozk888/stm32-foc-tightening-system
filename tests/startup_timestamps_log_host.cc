#define PW_LOG_TOKENIZED_FORMAT_STRING(module,message) message
#include "startup_timestamps_log.cc"
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
    StartupTimestamps s{};
    s.observations=s.valid=s.t0_us=s.t_iq_us=s.t_motion_us=s.t_speed_us=s.t_stable_us=s.motion_begin_us=UINT32_MAX;
    s.iq_at_event_a=-.105f;StartupTimes_Log(&s);
}
