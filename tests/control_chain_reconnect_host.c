/* Execute the actual request/task adapter. Peripherals and original task
 * setters are mocks; this is NOT a motor, RTOS scheduling or electrical test. */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <math.h>
#include <stdlib.h>
typedef uint32_t TickType_t;
#define pdMS_TO_TICKS(x) (x)
#define PREFLIGHT_CHAIN_MAX_STALE_MS 50U
#define TIGHTEN_REPEAT_RESTART_MAX_RPM 2.0f
#define MOTOR_MODE_IDLE 0U
#define MOTOR_MODE_SPEED 1U
#define MOTOR_MODE_IQ 2U
#define FOC_OC_CLEAR 0U
static uint32_t clock_ms, clock_us, mask_value;
static uint32_t preflight_adc_progress_tick, preflight_foc_progress_tick;
static uint8_t bench_active, lock, encoder_valid, adc_fault, foc_fault, run_zero_cal_done;
static uint8_t trial, uart_ready, timer_ready, busy;
static struct { uint8_t active; } fw_update;
static uint8_t foc_feedback_armed, foc_feedback_zero_ready, motor_control_mode;
static uint32_t foc_feedback_work_n, foc_feedback_last_us, foc_control_count;
static struct { struct { uint8_t result; } protection; } foc_feedback_safety;
static uint8_t tightening_start_request, tightening_stop_request, tightening_start_request_routed;
static uint32_t tightening_start_request_id, tightening_stop_request_id;
static uint16_t tightening_start_request_source_node;
static float foc_iq_ref_A, encoder_speed_rpm, command_rpm, command_iq;
static uint32_t xTaskGetTickCount(void) { return clock_ms; }
static uint32_t HAL_GetTick(void) { return clock_ms; }
static uint32_t AS5047P_DmaNowUs(void) { return clock_us; }
static uint32_t __get_PRIMASK(void) { return mask_value; }
static void __disable_irq(void) { mask_value=1U; }
static void __set_PRIMASK(uint32_t value) { mask_value=value; }
static void __DMB(void) { }
static int IsolatedBench_Active(void) { return bench_active; }
static int IsolatedBench_Locked(void) { return lock; }
static int BootHealth_IsCurrentTrial(void) { return trial; }
static int UART_Async_IsReady(void) { return uart_ready; }
static int FocFeedbackBinding_TimerHealthy(void) { return timer_ready; }
static int Tightening_IsBusy(void) { return busy; }
static void MotorControl_SetIdle(void) { motor_control_mode=0U; command_rpm=command_iq=0.0f; }
static void MotorControl_SetSpeed(float rpm) { motor_control_mode=1U; command_rpm=rpm; }
static void MotorControl_SetIq(float iq) { motor_control_mode=2U; command_iq=iq; }
#include "control_chain_reconnect.inc"

static void reset(void)
{
    clock_ms=1000U; clock_us=1000000U; mask_value=0U;
    preflight_adc_progress_tick=preflight_foc_progress_tick=clock_ms;
    bench_active=lock=encoder_valid=run_zero_cal_done=uart_ready=timer_ready=1U;
    adc_fault=foc_fault=trial=busy=fw_update.active=0U;
    foc_feedback_armed=foc_feedback_zero_ready=1U; foc_feedback_work_n=20U;
    foc_feedback_last_us=clock_us; foc_feedback_safety.protection.result=0U;
    motor_control_mode=0U; foc_control_count=40000U;
    tightening_start_request=tightening_stop_request=tightening_start_request_routed=0U;
    tightening_start_request_id=tightening_stop_request_id=tightening_start_request_source_node=0U;
    encoder_speed_rpm=foc_iq_ref_A=command_iq=command_rpm=0.0f;
    control_chain_request=control_chain_active=control_chain_used=control_chain_stop=0U;
    control_chain_kind=control_chain_start_pending=0U;
    control_chain_request_id=control_chain_start_id=0U;
    control_chain_deadline=control_chain_start_ms=0U;
    control_chain_outer_steps=control_chain_app_steps=0U;
    control_chain_start_foc=control_chain_end_foc=control_chain_end_ms=0U;
}
static int command(const char *value)
{
    char out[256]; ControlChain_Command(value,71U,out,sizeof(out));
    assert(mask_value==0U); return strncmp(out,"OK",2U)==0;
}
static void check_cancelled(void)
{
    assert(!control_chain_active && !control_chain_request && !control_chain_start_pending);
    assert(motor_control_mode==0U && foc_iq_ref_A==0.0f && !tightening_start_request);
}
int main(int argc,char **argv)
{
    assert(argc==2); int n=atoi(argv[1]); reset();
    if (n==0) {
        assert(command("BENCH CHAIN SPEED")); assert(motor_control_mode==0U);
        assert(!command("BENCH CHAIN IQ")); ControlChain_TaskService();
        assert(motor_control_mode==1U && command_rpm==20.0f && control_chain_active);
        assert(control_chain_app_steps==1U && control_chain_deadline==6000U);
        assert(!command("BENCH CHAIN SPEED"));
    } else if (n==1) {
        assert(command("BENCH CHAIN IQ")); ControlChain_TaskService();
        assert(motor_control_mode==2U && fabsf(command_iq-0.10f)<0.00001f);
        foc_iq_ref_A=0.10f; assert(command("BENCH CHAIN STOP")); assert(foc_iq_ref_A==0.0f);
        ControlChain_TaskService(); check_cancelled(); assert(tightening_stop_request);
        assert(!command("BENCH CHAIN IQ"));
    } else if (n==2) {
        assert(command("BENCH CHAIN TIGHTEN")); ControlChain_TaskService();
        assert(tightening_start_request && tightening_start_request_id==71U);
        assert(!tightening_start_request_routed && !tightening_start_request_source_node);
        assert(ControlChain_StartReady(71U)); assert(!ControlChain_StartReady(71U));
    } else if (n==3) {
        assert(command("BENCH CHAIN TIGHTEN")); ControlChain_TaskService();
        assert(!ControlChain_StartReady(72U)); assert(!ControlChain_StartReady(71U));
    } else if (n==4) {
        assert(command("BENCH CHAIN SPEED")); ControlChain_TaskService();
        clock_ms=6000U; foc_iq_ref_A=0.2f; ControlChain_TaskService();
        check_cancelled(); assert(tightening_stop_request && control_chain_used);
    } else if (n==5) {
        for (unsigned i=0;i<15U;++i) {
            reset();
            switch(i) {
            case 0:lock=0U;break; case 1:bench_active=0U;break;
            case 2:encoder_valid=0U;break; case 3:adc_fault=1U;break;
            case 4:foc_fault=1U;break; case 5:run_zero_cal_done=0U;break;
            case 6:trial=1U;break; case 7:fw_update.active=1U;break;
            case 8:foc_feedback_armed=0U;break; case 9:foc_feedback_zero_ready=0U;break;
            case 10:timer_ready=0U;break; case 11:foc_feedback_work_n=0U;break;
            case 12:foc_feedback_safety.protection.result=1U;break;
            case 13:foc_feedback_last_us-=101U;break; case 14:uart_ready=0U;break;
            }
            assert(!command("BENCH CHAIN SPEED") && !control_chain_request);
        }
    } else if (n==6) {
        for (unsigned i=0;i<6U;++i) {
            reset(); assert(command("BENCH CHAIN IQ"));
            switch(i) { case 0:busy=1U;break; case 1:encoder_speed_rpm=3.0f;break;
                case 2:foc_fault=1U;break; case 3:lock=0U;break;
                case 4:fw_update.active=1U;break; case 5:trial=1U;break; }
            ControlChain_TaskService(); check_cancelled(); assert(control_chain_used);
        }
    } else if (n==7) {
        for (unsigned i=0;i<5U;++i) {
            reset(); assert(command("BENCH CHAIN IQ")); ControlChain_TaskService();
            foc_iq_ref_A=0.1f;
            switch(i) { case 0:bench_active=0U;break; case 1:lock=0U;break;
                case 2:adc_fault=1U;break; case 3:fw_update.active=1U;break; case 4:trial=1U;break; }
            ControlChain_TaskService(); check_cancelled();
        }
    } else if (n==8) {
        assert(!command("BENCH CHAIN SPEED 100")); assert(!control_chain_used);
        assert(command("BENCH CHAIN STATUS"));
        clock_ms=UINT32_MAX-2000U; preflight_adc_progress_tick=preflight_foc_progress_tick=clock_ms;
        assert(command("BENCH CHAIN IQ")); ControlChain_TaskService();
        clock_ms=2999U; ControlChain_TaskService(); check_cancelled();
    } else if (n==9) {
        preflight_adc_progress_tick-=51U; assert(!command("BENCH CHAIN SPEED"));
        reset(); preflight_foc_progress_tick-=51U; assert(!command("BENCH CHAIN SPEED"));
        reset(); assert(command("BENCH CHAIN TIGHTEN")); ControlChain_TaskService();
        foc_fault=1U; assert(!ControlChain_StartReady(71U));
    } else if (n==10) {
        assert(command("BENCH CHAIN SPEED")); ControlChain_TaskService();
        assert(!ControlChain_DeadlineReached(clock_us+4999999U));
        assert(ControlChain_DeadlineReached(clock_us+5000000U));
        ControlChain_Cancel(); assert(!ControlChain_DeadlineReached(clock_us+9000000U));
    } else return 2;
    assert(mask_value==0U); return 0;
}
