#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "speed_accel_audit.h"
#include "speed_scurve.h"
#define FOC_ACCEL_FF_AUDIT 1
#define SPEED_ACCEL_EFFECTIVE_KA speed_accel_audit_ka
#define taskENTER_CRITICAL() ((void)0)
#define taskEXIT_CRITICAL() ((void)0)
#define TIM_BDTR_MOE 0x8000U
#define TIM_BDTR_AOE 0x4000U
#define DRIVER_SD_Pin 64U
#define MOTOR_MODE_IDLE 0U
static struct { unsigned ODR; } gpio;
static struct { unsigned BDTR,CCER; } timer;
#define DRIVER_SD_GPIO_Port (&gpio)
#define TIM1 (&timer)
static unsigned busy,tightening_start_request,tightening_stop_request,motor_control_mode;
static unsigned Tightening_IsBusy(void) {return busy;}
static unsigned speed_accel_ff_enabled=1U;
static float speed_accel_audit_ka=.0001875f;
static SpeedAccelAudit speed_accel_audit;
static SpeedAccelFfStats speed_accel_ff_stats;
static SpeedAccelFfFrame speed_accel_ff_frame;
void SpeedAccelAudit_Log(const SpeedAccelAuditFrame *f) {(void)f;}
#include "../firmware_common/speed_accel_feedforward_binding.inc"
int main(void)
{
    char out[256];
    const char *values[]={"0","25","50","100"};
    for (unsigned i=0;i<4;++i) {
        char cmd[64];snprintf(cmd,sizeof(cmd),"MOTOR TEST FF GAIN %s",values[i]);
        assert(SpeedAccelFf_Command(cmd,out,sizeof(out))==1U);
        assert(strstr(out,"OK AFF ON=1"));
        float ka=speed_accel_audit_ka;
        assert(ka>=0 && ka<=.0001875f);
        unsigned *guards[]={&busy,&tightening_start_request,&tightening_stop_request,
            &motor_control_mode,&gpio.ODR,&timer.BDTR,&timer.CCER};
        for (unsigned j=0;j<7;++j) {
            *guards[j]=(j==4)?DRIVER_SD_Pin:(j==5)?TIM_BDTR_MOE:1U;
            assert(SpeedAccelFf_Command("MOTOR TEST FF GAIN 0",out,sizeof(out)));
            assert(strstr(out,"ERR AFF BUSY_OR_OUTPUT_ENABLED"));
            assert(speed_accel_audit_ka==ka);
            *guards[j]=0;
        }
    }
    const char *bad[]={"-50","200","nan","25x","25 ","025",""};
    for (unsigned i=0;i<7;++i) {
        char cmd[64];snprintf(cmd,sizeof(cmd),"MOTOR TEST FF GAIN %s",bad[i]);
        assert(SpeedAccelFf_Command(cmd,out,sizeof(out)));
        assert(strstr(out,"ERR AFF GAIN"));
        assert(speed_accel_audit_ka==.0001875f);
    }
    SpeedAccelFf_Monitor();
    assert(!gpio.ODR && !timer.BDTR && !timer.CCER);
    puts("PASS: bounded idle-only gain selector, guards, status, no gate writes");
    return 0;
}
