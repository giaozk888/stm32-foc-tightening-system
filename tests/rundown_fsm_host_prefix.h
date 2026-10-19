/* Minimal ports around the ACTUAL firmware switch extracted by the Python
 * regression. No motor model; no rewritten application transition logic. */
#include <math.h>
#include <stdint.h>
#include <string.h>
#include "tightening_rundown_guard.h"
typedef uint32_t TickType_t;
#define TIGHTEN_DIRECTION 1.0f
#define TIGHTEN_STOP_MAX_RPM 2.0f
#define TIGHTEN_STOP_CONFIRM_MS 150U
#define TIGHTEN_STOP_TIMEOUT_MS 2000U
#define FOC_DIAG_PROCESS 0
#define FOC_TO_NONE 0
#define FOC_TO_RUNDOWN 1
#define FOC_TO_STOP_SETTLE 2
#define FaultDiag_Capture(domain,reason,timeout,elapsed,limit) ((void)(elapsed))
#define UART_SendLiteral(...) ((void)0)
#define TighteningResult_Sample(...) ((void)0)
#define TighteningResult_Reset(...) ((void)0)
#define TighteningResult_PrintSummary(...) ((void)0)
#define TighteningRepeat_StoreCurrentCycle(...) ((void)0)
static TightenRundownGuard tightening_rundown;
static uint32_t tightening_test_elapsed_ms,tightening_contact_candidate_ms;
static uint8_t tightening_contact_condition,tightening_contact_confirmed,tightening_result_printed;
static float tightening_drive_iqref_A,tightening_post_contact_travel_deg;
static float tightening_contact_position_deg,encoder_position_deg,encoder_speed_rpm,foc_iq_ref_A;
static uint8_t encoder_valid=1;
static struct { struct {
    uint32_t rundown_rpm, contact_rpm, contact_iq_mA, contact_ms;
    uint32_t rundown_timeout_ms,max_travel_deg,seating_iq_mA,t1_iq_mA,t2_iq_mA,t3_iq_mA,hold_iq_mA;
    uint32_t seating_ms,t1_ms,t2_ms,t3_ms,hold_ms,torque_abort_rpm,post_travel_max_deg;
} params; } recipe_state;
static unsigned power_off,ok_events,contact_seen,iq_stages;
static void PowerStage_Disable(void) { ++power_off; }
#if defined(FOC_PROTECTED_CLOSED_LOOP)
static void ProtectedLoop_Stop(void) { ++power_off; foc_iq_ref_A=0; }
#endif
static void MotorControl_SetIdle(void) { }
static void MotorControl_SetIq(float x) { (void)x; ++iq_stages; }
static void Protocol_SendCycleEvent(const char *a,const char *b)
{ (void)a; if (!strcmp(b,"OK")) ++ok_events; }
