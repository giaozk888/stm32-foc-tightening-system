#include "load_gain_opt_policy.h"
#include <string.h>
static LoadGainScheduler s;
__declspec(dllexport) void gain_reset(void){memset(&s,0,sizeof s);}
__declspec(dllexport) void gain_step(const double *u,double *out){
    LoadGainEvidence e={(uint32_t)u[0],(uint32_t)u[1],(uint32_t)u[2],(uint32_t)u[3],
        (uint32_t)u[4],(uint32_t)u[5],(uint32_t)u[6],(uint32_t)u[7],(uint32_t)u[8],(uint32_t)u[9],(float)u[10],(float)u[11]};
    float g=LoadGainOpt_Step(&s,e,(uint32_t)u[12]);
    double y[]={g,s.requested,s.active,s.reason,s.high_us,s.release_us,s.credit_us,s.last_good_us,s.updates,s.transitions};
    memcpy(out,y,sizeof y);
}
