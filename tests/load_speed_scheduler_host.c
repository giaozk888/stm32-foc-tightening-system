#include "load_speed_scheduler.h"
#include "speed_scurve.h"
static LoadSpeedScheduler policy;
static SpeedScurve path;
__declspec(dllexport) void schedule_reset(void){policy=(LoadSpeedScheduler){0};SpeedScurve_Reset(&path,240);}
__declspec(dllexport) void schedule_step(const double *u,double *y){
    float target=LoadSpeed_Step(&policy,(LoadSpeedEvidence){(uint32_t)u[0],(uint32_t)u[1],(uint32_t)u[2],
        (uint32_t)u[3],(uint32_t)u[4],(uint32_t)u[5],(uint32_t)u[6],(float)u[7],(float)u[8],(float)u[9]});
    float ref=SpeedScurve_Step(&path,target,.001f);
    double out[]={target,policy.slow,policy.reason,policy.transitions,policy.high_us,policy.release_us,ref,path.acceleration_rpm_s};
    for(unsigned k=0;k<8;++k)y[k]=out[k];
}
