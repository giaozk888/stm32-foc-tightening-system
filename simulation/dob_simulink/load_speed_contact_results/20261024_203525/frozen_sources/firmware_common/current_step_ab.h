#ifndef CURRENT_STEP_AB_H
#define CURRENT_STEP_AB_H
#include <stdint.h>

/* Diagnostic timing/quality only; NEVER controller or protection thresholds. */
#define CS_STEPS 10U
#define CS_EVENTS 6U
#define CS_PRE_US 20000U
#define CS_ON_US 30000U
#define CS_POST_US 30000U
#define CS_SEGMENT_US (CS_PRE_US+CS_ON_US+CS_POST_US)
#define CS_MAX_US (CS_STEPS*CS_SEGMENT_US)
#define CS_STEADY_US 5000U
#define CS_MAX_MA 300U
#define CS_POS_OVERSHOOT_PERCENT 20U
#define CS_RING_CROSSINGS 4U
#define CS_MIN_TAIL_SAMPLES 80U

enum { CS_IDLE,CS_QUEUED,CS_ACTIVE,CS_DONE,CS_POS_QUALITY_STOP,CS_ABORT };
enum { CS_OK,CS_PROTECTION,CS_CANCELLED,CS_NOT_READY,CS_TIME,CS_BAD_DATA };
enum { CS_BASELINE,CS_T10,CS_T90,CS_PEAK,CS_STEADY,CS_ZERO_END };
/* All current/voltage int16 fields: 1e-4 A / 1e-4 V; omega: 0.01 rad/s.
 * flags bit0 valid, bit1 new PI, bit2 voltage saturated, bit3 quantization clip.
 * bits4..5 phase (0 pre/1 pulse/2 zero), bits8..11 step index. */
typedef struct {
    uint32_t us,seq;
    int16_t iq_ref,iq,id,vq,vd,int_q,int_d,out_q,out_d,omega;
    uint16_t flags,fault;
} CurrentStepFrame;
_Static_assert(sizeof(CurrentStepFrame)==32U,"Step trace binary ABI");
typedef struct {
    int32_t baseline_sum,baseline,tail_sum,peak;
    uint32_t baseline_n,tail_n,high_n,t10_us,t90_us,settle_us;
    uint32_t gaps,last_seq,crossings,valid_mask;
    int8_t last_side;
    uint8_t clipped,reserved[2];
} CurrentStepMetric;
typedef struct {
    CurrentStepFrame rows[CS_STEPS][CS_EVENTS],failure;
    CurrentStepMetric metrics[CS_STEPS];
    uint32_t start_us,encoder_before,last_us;
    volatile uint8_t state;
    uint8_t reason,used,prepared,admitting,step,phase,reset_pi;
    uint8_t positive_pass,completed,failure_valid,reserved;
} CurrentStepAB;
_Static_assert(sizeof(CurrentStepMetric)==60U,"Step metric binary ABI");
_Static_assert(sizeof(CurrentStepAB)==2576U,"Step capture binary ABI");

int16_t CurrentStep_TargetMa(unsigned step);
unsigned CurrentStep_NewPi(unsigned step);
int CurrentStep_Queue(CurrentStepAB *s,int ready,unsigned limit_ma);
void CurrentStep_Begin(CurrentStepAB *s,uint32_t now);
void CurrentStep_End(CurrentStepAB *s,uint8_t state,uint8_t reason);
int CurrentStep_Reference(CurrentStepAB *s,uint32_t now,int *new_pi,float *iq);
void CurrentStep_Record(CurrentStepAB *s,uint32_t now,uint32_t seq,
    float iq_ref,float iq,float id,float vq,float vd,float int_q,float int_d,
    float out_q,float out_d,float omega,unsigned saturated,uint16_t fault);
int CurrentStep_PositivePass(const CurrentStepAB *s);
#endif
