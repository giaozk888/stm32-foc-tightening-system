/* Compile the production manual owner and admission with fake registers.
 * This executes no hardware and never represents a real torque measurement. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <math.h>
#include "as5047p_protocol.h"
#define FOC_TORQUE_CHAIN_DIAG 1
#define FOC_PROTECTED_CLOSED_LOOP 1
#define FOC_CURRENT_TREND4 1
#define FOC_CURRENT_SPIKE_ONLY 1
#define AS5047P_SPI_DMA 1
#define FOC_ADC_WINDOW 1
#define FOC_ADC_SENSE_TOPOLOGY 2
#define FOC_PWM_PIPELINE_CLOSED_LOOP 1
#define FOC_RUNDOWN_DIAGNOSTIC 1
#if defined(FOC_BREAKAWAY_CURRENT_TEST)
#define MOTOR_DIRECT_IQ_LIMIT_A 0.20f
#endif
#include "protected_closed_loop.h"
#include "foc_startup_trace.h"
static ClSession cl_session;
static FocTorqueChainDiag torque_diag;
#if defined(FOC_ANGLE_CHAIN_DIAG)
static FocAngleHand angle_hand;
#endif
static struct { unsigned CCER,BDTR; } timer;
static struct { unsigned BSRR,ODR; } gpio;
#define TIM1 (&timer)
#define DRIVER_SD_GPIO_Port (&gpio)
#define DRIVER_SD_Pin 64U
#define TIM_BDTR_AOE 0x4000U
#define TIM_BDTR_MOE 0x8000U
typedef struct { int unused; } FocWindowPlan;
typedef unsigned FocWindowStatus;
#define FOC_WINDOW_OK 0U
#define MOTOR_MODE_IDLE 0U
#define MOTOR_MODE_IQ 3U
#if defined(FOC_SPEED_DYNAMIC_DIAG)
#define MOTOR_MODE_SPEED 1U
static float requested_speed;
#endif
static unsigned motor_control_mode,adc_fault,foc_fault;
static unsigned analog_safe_latched,tightening_start_request,tightening_stop_request;
static unsigned cl_outer_n,now_us,healthy=1,mask_depth,busy,invalidations,stops;
static unsigned fault_in_prepare,stop_in_prepare;
static unsigned speed_pi_calls;
static float foc_int_d_V,foc_int_q_V,foc_id_ref_A,foc_iq_ref_A,foc_vd_V,foc_vq_V;
static unsigned __get_PRIMASK(void) { return mask_depth; }
static void __disable_irq(void) { mask_depth=1; }
static void __set_PRIMASK(unsigned v) { mask_depth=v; }
static void __DSB(void) { }
static unsigned AS5047P_DmaNowUs(void) { return now_us; }
static unsigned Tightening_IsBusy(void) { return busy; }
static unsigned ProtectedLoop_Ready(void) { return healthy && !adc_fault && !foc_fault && cl_session.state==CL_READY; }
static unsigned FocAdcTiming_FastCanStart(void) { return healthy; }
static FocWindowStatus FocAdcTiming_Prepare(float a,float b,float c,FocWindowPlan *p)
{ (void)a;(void)b;(void)c;(void)p; assert(!mask_depth);
  if (fault_in_prepare) foc_fault=1;
  if (stop_in_prepare) tightening_stop_request=1;
  return 0; }
static void FocAdcTiming_PlanFailed(unsigned x) { (void)x; }
static void ProtectedLoop_PwmInvalidate(void) { ++invalidations; }
static void FocCurrentPi_Reset(float *d,float *q) { *d=*q=0; }
#if defined(FOC_SPEED_DYNAMIC_DIAG)
static void MotorControl_SetSpeed(float rpm)
{ assert(!(timer.BDTR & TIM_BDTR_MOE)); motor_control_mode=MOTOR_MODE_SPEED; requested_speed=rpm; }
#else
static void MotorControl_SetIq(float iq)
{ assert(!(timer.BDTR & TIM_BDTR_MOE)); motor_control_mode=MOTOR_MODE_IQ; foc_iq_ref_A=iq; }
#endif
static void MotorControl_SetIdle(void) { motor_control_mode=MOTOR_MODE_IDLE; foc_iq_ref_A=0; }
static void ProtectedLoop_Stop(void)
{ ++stops; timer.CCER=timer.BDTR=gpio.BSRR=0; ClSession_Stop(&cl_session); }
#include "latest_original_fsm.inc"
static void reset(void)
{
    cl_session=(ClSession){.state=CL_READY}; torque_diag=(FocTorqueChainDiag){0};
#if defined(FOC_ANGLE_CHAIN_DIAG)
    angle_hand=(FocAngleHand){0};
#endif
    timer.CCER=timer.BDTR=gpio.BSRR=0;
    cl_outer_n=1; healthy=1; busy=adc_fault=foc_fault=analog_safe_latched=0;
    tightening_start_request=tightening_stop_request=0; mask_depth=0;
    fault_in_prepare=stop_in_prepare=0;
    now_us=1000; cl_session.outer_us=1000; MotorControl_SetIdle();
}
#if !defined(FOC_SPEED_DYNAMIC_DIAG) && !defined(FOC_ANGLE_CHAIN_DIAG)
static void start(const char *cmd,float iq,int offset)
{
    char out[256]; reset();
    assert(!LatestOriginal_Admit()); /* ordinary START cannot enable */
    assert(TorqueChain_Command(cmd,out,sizeof out)); assert(strstr(out,"QUEUED"));
    assert(torque_diag.offset_deg==offset && !torque_diag.active);
    TorqueChain_Service(); assert(!torque_diag.active);
    TorqueChain_Service(); assert(!torque_diag.active); /* no fresh encoder */
    ++cl_outer_n; TorqueChain_Service();
    assert(torque_diag.active && cl_session.state==CL_RUNNING);
    assert(motor_control_mode==MOTOR_MODE_IQ && foc_id_ref_A==0);
    assert(fabsf(foc_iq_ref_A-iq)<1e-7f);
#if defined(FOC_TORQUE450_FIVE_SECOND)
    TorqueChain_Command("MOTOR TEST TORQUE450 STATUS",out,sizeof out);
    assert(strstr(out,"IQ_MA=450 LIMIT_MA=450 ID_MA=0 LEASE_US=5000000"));
    assert(torque_diag.iq_mA==450U);
#elif defined(FOC_TORQUE350_FIVE_SECOND)
    TorqueChain_Command("MOTOR TEST TORQUE350 STATUS",out,sizeof out);
    assert(strstr(out,"IQ_MA=350 LIMIT_MA=350 ID_MA=0 LEASE_US=5000000"));
    assert(torque_diag.iq_mA==350U);
#elif defined(FOC_BREAKAWAY_CURRENT_TEST)
    TorqueChain_Command("MOTOR TEST BREAKAWAY STATUS",out,sizeof out);
    assert(strstr(out,"LIMIT_MA=200 ID_MA=0"));
    assert(torque_diag.iq_mA==(unsigned)(fabsf(iq)*1000.0f+0.5f));
#else
    TorqueChain_Command("MOTOR TEST TORQUE STATUS",out,sizeof out);
    assert(strstr(out,"IQ_MA=" FOC_TORQUE_CHAIN_IQ_TEXT " ID_MA=0"));
#endif
    assert(timer.BDTR & TIM_BDTR_MOE); assert(gpio.BSRR==64);
    LatestOriginal_FsmService(); assert(cl_session.state==CL_RUNNING);
    assert(!speed_pi_calls);
}
#endif
int main(void)
{
#if defined(FOC_ANGLE_CHAIN_DIAG)
    char out[256]; const char *cmd="MOTOR TEST ANGLE OFFSET +20 CONFIRM";
    (void)speed_pi_calls;
    (void)foc_int_d_V; (void)foc_int_q_V; (void)foc_id_ref_A; (void)foc_vd_V; (void)foc_vq_V;
    LatestOriginal_FsmService();
    reset(); TorqueChain_Command(cmd,out,sizeof out); assert(!torque_diag.used);
    assert(!LatestOriginal_Admit());
    TorqueChain_Command("MOTOR TEST ANGLE BEGIN",out,sizeof out); assert(strstr(out,"OK ANGLE BEGIN"));
    unsigned raw=1234; int counts=0;
    for(unsigned i=0;i<=2048;++i) {
        if(i) { int step=i<=1024 ? -16 : 16; raw=(raw+step)&16383; counts-=step; }
        FocAngleHand_Observe(&angle_hand,1000+i*1000,raw,
            AS5047P_ElectricalAngleRad(raw,10507,10,-1),counts*360.0f/16384,1,1);
    }
    TorqueChain_Command("MOTOR TEST ANGLE END",out,sizeof out); assert(strstr(out,"PASS=1"));
    TorqueChain_Command("MOTOR TEST ANGLE READ 0",out,sizeof out); assert(strstr(out,"MISSING"));
    char read[80]; snprintf(read,sizeof read,"MOTOR TEST ANGLE READ %u",angle_hand.records-1);
    TorqueChain_Command(read,out,sizeof out); assert(strstr(out,"OK ANGLE ROW="));
    healthy=0; TorqueChain_Command(cmd,out,sizeof out); assert(!torque_diag.used); healthy=1;
#if !defined(FOC_ANGLE_HAND_ONLY)
    const char *angles[]={"-30","-20","-10","0","+10","+20","+30"};
    for(unsigned i=0;i<7;++i) {
        FocTorqueChainDiag single={0}; char choice[96];
        snprintf(choice,sizeof choice,"MOTOR TEST ANGLE OFFSET %s CONFIRM",angles[i]);
        assert(FocTorqueChain_Queue(&single,choice,1));
        assert(single.iq_mA==350 && single.sign==1 && FocAngleOffset_Allowed(single.offset_deg));
        assert(!FocTorqueChain_Queue(&single,choice,1));
    }
#endif
    TorqueChain_Command(cmd,out,sizeof out);
#if defined(FOC_ANGLE_HAND_ONLY)
    assert(strstr(out,"HAND_ONLY") && !torque_diag.used && !LatestOriginal_Admit());
    assert(!(timer.BDTR & TIM_BDTR_MOE));
#else
    assert(strstr(out,"QUEUED") && torque_diag.offset_deg==20 && torque_diag.iq_mA==350);
    assert(CL_MAX_US==400000U && FOC_STARTUP_PERIOD_US==12000U);
    TorqueChain_Service(); ++cl_outer_n; TorqueChain_Service();
    assert(torque_diag.active && motor_control_mode==MOTOR_MODE_IQ && foc_id_ref_A==0);
    assert(fabsf(foc_iq_ref_A-.35f)<1e-7f);
    assert(!ClSession_Expired(&cl_session,cl_session.start_us+399999U));
    assert(ClSession_Expired(&cl_session,cl_session.start_us+400000U));
    ProtectedLoop_Stop(); TorqueChain_Service(); assert(!torque_diag.active);
    TorqueChain_Command(cmd,out,sizeof out); assert(!torque_diag.queued);
    assert(!LatestOriginal_Admit());
#endif
    assert(!speed_pi_calls);
    return 0;
#elif defined(FOC_TORQUE450_FIVE_SECOND)
    char out[256]; const char *cmd="MOTOR TEST TORQUE450 CONFIRM";
#if defined(FOC_TORQUE450_150RPM)
    assert(CL_OVERSPEED_RPM==150U);
#else
    assert(CL_OVERSPEED_RPM==60U);
#endif
    assert(CL_MAX_US==5000000U && FOC_STARTUP_PERIOD_US==200000U);
    start(cmd,.45f,0);
    TorqueChain_Command("MOTOR TEST TORQUE450 STATUS",out,sizeof out);
    assert(strstr(out,"RPM_LIMIT=" CL_OVERSPEED_TEXT));
    assert(!ClSession_Expired(&cl_session,cl_session.start_us+4999999U));
    assert(ClSession_Expired(&cl_session,cl_session.start_us+5000000U));
    ProtectedLoop_Stop(); TorqueChain_Service(); assert(!torque_diag.active);
    assert(motor_control_mode==MOTOR_MODE_IDLE && !(timer.BDTR & TIM_BDTR_MOE));
    TorqueChain_Command(cmd,out,sizeof out); assert(!torque_diag.queued);
    const char *bad[]={"MOTOR TEST TORQUE350 CONFIRM","MOTOR TEST TORQUE450 NEG CONFIRM",
        "MOTOR TEST TORQUE450 CONFIRM extra","MOTOR TEST SPEED500 CONFIRM","START"};
    for(unsigned i=0;i<sizeof bad/sizeof bad[0];++i) {
        reset(); TorqueChain_Command(bad[i],out,sizeof out); assert(!torque_diag.used);
    }
    for(unsigned race=0;race<2;++race) {
        reset(); TorqueChain_Command(cmd,out,sizeof out); TorqueChain_Service(); ++cl_outer_n;
        if(race) stop_in_prepare=1; else fault_in_prepare=1;
        TorqueChain_Service(); assert(torque_diag.denied && !torque_diag.active && !(timer.BDTR & TIM_BDTR_MOE));
    }
    start(cmd,.45f,0); foc_fault=1; ProtectedLoop_Stop(); cl_session.state=CL_FAULT;
    TorqueChain_Service(); assert(!torque_diag.active && !LatestOriginal_Admit());
    return 0;
#elif defined(FOC_TORQUE350_FIVE_SECOND)
    char out[256]; const char *cmd="MOTOR TEST TORQUE350 CONFIRM";
    assert(CL_MAX_US==5000000U && FOC_STARTUP_PERIOD_US==200000U);
    start(cmd,.35f,0);
    assert(!ClSession_Expired(&cl_session,cl_session.start_us+4999999U));
    assert(ClSession_Expired(&cl_session,cl_session.start_us+5000000U));
    ProtectedLoop_Stop(); TorqueChain_Service(); assert(!torque_diag.active);
    assert(motor_control_mode==MOTOR_MODE_IDLE && !(timer.BDTR & TIM_BDTR_MOE));
    TorqueChain_Command(cmd,out,sizeof out); assert(!torque_diag.queued);
    const char *bad[]={"MOTOR TEST TORQUE NEG ZERO CONFIRM","MOTOR TEST TORQUE POS ZERO CONFIRM",
        "MOTOR TEST BREAKAWAY POS 350 CONFIRM","MOTOR TEST SPEED500 CONFIRM",
        "MOTOR TEST TORQUE350 CONFIRM extra","MOTOR TEST TORQUE350 NEG CONFIRM"};
    for(unsigned i=0;i<sizeof bad/sizeof bad[0];++i) {
        reset(); TorqueChain_Command(bad[i],out,sizeof out); assert(!torque_diag.used);
    }
    for(unsigned race=0;race<2;++race) {
        reset(); TorqueChain_Command(cmd,out,sizeof out); TorqueChain_Service(); ++cl_outer_n;
        if(race) stop_in_prepare=1; else fault_in_prepare=1;
        TorqueChain_Service(); assert(torque_diag.denied && !torque_diag.active && !(timer.BDTR & TIM_BDTR_MOE));
    }
    start(cmd,.35f,0); foc_fault=1; ProtectedLoop_Stop(); cl_session.state=CL_FAULT;
    TorqueChain_Service(); assert(!torque_diag.active && !LatestOriginal_Admit());
    FocBreakawayMotion motion={0};
    for(unsigned i=0;i<5000U;++i)
        FocBreakaway_Observe(&motion,i*1000U,(uint16_t)((17000U-i)&16383U),1,1,1,1);
    assert(motion.count==5000U && motion.net_counts==4999 && motion.absolute_counts==4999U);
    assert(motion.tail_net_counts>1600 && !motion.bad_ref && !motion.bad_gates);
    return 0;
#elif defined(FOC_SPEED_DYNAMIC_DIAG)
    char out[256]; const char *cmd="MOTOR TEST SPEED500 CONFIRM";
    (void)speed_pi_calls;
    assert(CL_MAX_US==5000000U && FOC_STARTUP_PERIOD_US==200000U);
    reset(); assert(!LatestOriginal_Admit());
    assert(TorqueChain_Command("MOTOR TEST SPEED500 STATUS",out,sizeof out));
    assert(strstr(out,"DYNAMIC_IQ=1") && !torque_diag.used);
    assert(TorqueChain_Command(cmd,out,sizeof out) && strstr(out,"QUEUED"));
    TorqueChain_Service(); TorqueChain_Service(); assert(!torque_diag.active);
    ++cl_outer_n; TorqueChain_Service();
    assert(torque_diag.active && cl_session.state==CL_RUNNING);
    assert(motor_control_mode==MOTOR_MODE_SPEED && requested_speed==20.0f);
    assert(!foc_iq_ref_A && !foc_id_ref_A && !torque_diag.iq_mA);
    assert(timer.BDTR & TIM_BDTR_MOE);
    LatestOriginal_FsmService(); assert(cl_session.state==CL_RUNNING);
    assert(!ClSession_Expired(&cl_session,cl_session.start_us+4999999U));
    assert(ClSession_Expired(&cl_session,cl_session.start_us+5000000U));
    ProtectedLoop_Stop(); TorqueChain_Service(); assert(!torque_diag.active);
    assert(motor_control_mode==MOTOR_MODE_IDLE && !(timer.BDTR & TIM_BDTR_MOE));
    TorqueChain_Command(cmd,out,sizeof out); assert(!torque_diag.queued);
    const char *bad[]={"MOTOR TEST TORQUE POS ZERO CONFIRM","MOTOR TEST BREAKAWAY POS 200 CONFIRM",
        "MOTOR TEST SPEED500 CONFIRM extra","MOTOR TEST SPEED500 500 CONFIRM"};
    for(unsigned i=0;i<sizeof bad/sizeof bad[0];++i) {
        reset(); TorqueChain_Command(bad[i],out,sizeof out); assert(!torque_diag.used);
    }
    reset(); healthy=0; TorqueChain_Command(cmd,out,sizeof out); assert(!torque_diag.used);
    for(unsigned race=0;race<2;++race) {
        reset(); TorqueChain_Command(cmd,out,sizeof out); TorqueChain_Service(); ++cl_outer_n;
        if(race) stop_in_prepare=1; else fault_in_prepare=1;
        TorqueChain_Service(); assert(torque_diag.denied && !torque_diag.active && !(timer.BDTR & TIM_BDTR_MOE));
    }
    reset(); TorqueChain_Command(cmd,out,sizeof out); TorqueChain_Service(); ++cl_outer_n;
    TorqueChain_Service(); foc_fault=1; ProtectedLoop_Stop(); cl_session.state=CL_FAULT;
    TorqueChain_Service(); assert(!torque_diag.active && motor_control_mode==MOTOR_MODE_IDLE);
    assert(!LatestOriginal_Admit());
    return 0;
#elif defined(FOC_BREAKAWAY_CURRENT_TEST)
    const unsigned candidates[]={100,120,150,180,200}; char cmd[96],out[256];
    for (unsigned i=0;i<5;++i) for (unsigned neg=0;neg<2;++neg) {
        snprintf(cmd,sizeof cmd,"MOTOR TEST BREAKAWAY %s %u CONFIRM",neg ? "NEG" : "POS",candidates[i]);
        start(cmd,(neg ? -1.0f : 1.0f)*(float)candidates[i]*0.001f,0);
        assert(ClSession_Expired(&cl_session,cl_session.start_us+BREAKAWAY_TEST_DURATION_US));
        assert(!ClSession_Expired(&cl_session,cl_session.start_us+BREAKAWAY_TEST_DURATION_US-1U));
        assert(!FocBreakaway_Queue(&torque_diag,cmd,1,200));
        ProtectedLoop_Stop(); TorqueChain_Service();
        assert(!torque_diag.active && motor_control_mode==MOTOR_MODE_IDLE && foc_iq_ref_A==0);
        assert(!(timer.BDTR & TIM_BDTR_MOE));
    }
    for(unsigned neg=0;neg<2;++neg) {
        reset(); snprintf(cmd,sizeof cmd,"MOTOR TEST BREAKAWAY %s 250 CONFIRM",neg ? "NEG" : "POS");
        TorqueChain_Command(cmd,out,sizeof out); assert(strstr(out,"LIMIT_BLOCKED"));
        assert(!torque_diag.used && !torque_diag.queued && !(timer.BDTR & TIM_BDTR_MOE));
    }
    const char *bad[]={"MOTOR TEST BREAKAWAY POS 251 CONFIRM","MOTOR TEST BREAKAWAY POS 201 CONFIRM",
        "MOTOR TEST BREAKAWAY POS 0.2 CONFIRM","MOTOR TEST BREAKAWAY POS 100", "MOTOR TEST BREAKAWAY POS 100 CONFIRM extra",
        "MOTOR TEST TORQUE POS ZERO CONFIRM","START","MOTOR TEST BREAKAWAY POS 999 CONFIRM"};
    for(unsigned i=0;i<sizeof bad/sizeof bad[0];++i) {
        reset(); TorqueChain_Command(bad[i],out,sizeof out);
        assert(!torque_diag.used && !(timer.BDTR & TIM_BDTR_MOE));
    }
    strcpy(cmd,"MOTOR TEST BREAKAWAY POS 100 CONFIRM");
    reset(); healthy=0; TorqueChain_Command(cmd,out,sizeof out); assert(!torque_diag.used);
    reset(); TorqueChain_Command(cmd,out,sizeof out); tightening_stop_request=1;
    TorqueChain_Service(); assert(torque_diag.denied && !torque_diag.active);
    start(cmd,0.1f,0); foc_fault=1; ProtectedLoop_Stop(); cl_session.state=CL_FAULT;
    TorqueChain_Service(); assert(!torque_diag.active && !(timer.BDTR & TIM_BDTR_MOE));
    for(unsigned race=0;race<2;++race) {
        reset(); TorqueChain_Command(cmd,out,sizeof out); TorqueChain_Service(); ++cl_outer_n;
        if(race) stop_in_prepare=1; else fault_in_prepare=1;
        TorqueChain_Service(); assert(torque_diag.denied && !torque_diag.active && !(timer.BDTR & TIM_BDTR_MOE));
    }
    reset(); TorqueChain_Command(cmd,out,sizeof out); TorqueChain_Service(); ++cl_outer_n;
    torque_diag.iq_mA=250; TorqueChain_Service();
    assert(torque_diag.denied && !(timer.BDTR & TIM_BDTR_MOE));
    assert(breakaway_capture_tag==BREAKAWAY_CAPTURE_TAG && !speed_pi_calls);
#if defined(FOC_BREAKAWAY_FIVE_SECOND)
    assert(CL_MAX_US==5000000U && FOC_STARTUP_PERIOD_US==200000U);
    FocStartupTrace capture={0}; FocStartup_Begin(&capture,1000U);
    for(unsigned t=1000;t<5000000U;t+=1000U)
        FocStartup_Push(&capture,(FocStartupFrame){.us=1000U+t});
    assert(capture.total==25U && capture.rows[24].us>=4800000U);
    FocBreakawayMotion motion={0};
    for(unsigned i=0;i<5000U;++i)
        FocBreakaway_Observe(&motion,i*1000U,(uint16_t)((17000U-i)&16383U),1,1,1,1);
    assert(motion.count==5000U && motion.net_counts==4999 && motion.absolute_counts==4999U);
    assert(motion.forward==4999U && !motion.backward && !motion.bad_ref);
    assert(motion.max_gap_us==1000U && motion.tail_net_counts>1600);
    FocBreakaway_Observe(&motion,5000000U,motion.last_raw,1,0,0,0);
    assert(motion.bad_ref==1 && motion.bad_gates==1 && motion.bad_encoder==1);
#endif
    return 0;
#else
    char out[256]; int32_t s,o;
    assert(!FocTorqueChain_Parse("MOTOR TEST TORQUE POS PLUS90 CONFIRM",&s,&o));
    assert(!FocTorqueChain_Parse("MOTOR TEST TORQUE POS ZERO",&s,&o));
    assert(!FocTorqueChain_Parse("MOTOR TEST TORQUE POS ZERO CONFIRM extra",&s,&o));
    start("MOTOR TEST TORQUE POS ZERO CONFIRM",FOC_TORQUE_CHAIN_IQ_A,0);
#if FOC_TORQUE_CHAIN_IQ_MA != 50
    assert(torque_diag.iq_mA==FOC_TORQUE_CHAIN_IQ_MA);
    assert(!FocTorqueChain_Parse("MOTOR TEST TORQUE POS PLUS5 CONFIRM",&s,&o));
    assert(!FocTorqueChain_Parse("MOTOR TEST TORQUE NEG MINUS5 CONFIRM",&s,&o));
#endif
    assert(!FocTorqueChain_Queue(&torque_diag,"MOTOR TEST TORQUE NEG ZERO CONFIRM",1));
    assert(!ClSession_Expired(&cl_session,cl_session.start_us+199999));
    assert(ClSession_Expired(&cl_session,cl_session.start_us+200000));
    /* Existing guard invokes STOP; task cannot restart after expiry. */
    ProtectedLoop_Stop(); TorqueChain_Service(); assert(!torque_diag.active);
    assert(!LatestOriginal_Admit()); assert(!(timer.BDTR & TIM_BDTR_MOE));
#if FOC_TORQUE_CHAIN_IQ_MA != 200
    start("MOTOR TEST TORQUE NEG ZERO CONFIRM",-FOC_TORQUE_CHAIN_IQ_A,0);
#else
    reset(); assert(!FocTorqueChain_Queue(&torque_diag,"MOTOR TEST TORQUE NEG ZERO CONFIRM",1));
    assert(!torque_diag.used && !torque_diag.queued);
    start("MOTOR TEST TORQUE POS ZERO CONFIRM",FOC_TORQUE_CHAIN_IQ_A,0);
#endif
    tightening_stop_request=1; TorqueChain_Service(); assert(!torque_diag.active);
    assert(!(timer.BDTR & TIM_BDTR_MOE));
    start("MOTOR TEST TORQUE POS ZERO CONFIRM",FOC_TORQUE_CHAIN_IQ_A,0);
    foc_fault=1; ProtectedLoop_Stop(); cl_session.state=CL_FAULT;
    TorqueChain_Service(); assert(!torque_diag.active && cl_session.state==CL_FAULT);
    reset(); healthy=0; TorqueChain_Command("MOTOR TEST TORQUE POS ZERO CONFIRM",out,sizeof out);
    assert(!torque_diag.used && !torque_diag.queued);
    reset(); TorqueChain_Command("MOTOR TEST TORQUE POS ZERO CONFIRM",out,sizeof out);
    tightening_start_request=1; TorqueChain_Service(); assert(torque_diag.denied);
    assert(!LatestOriginal_Admit());
    reset(); TorqueChain_Command("MOTOR TEST TORQUE POS ZERO CONFIRM",out,sizeof out);
    TorqueChain_Service(); ++cl_outer_n; foc_fault=1; TorqueChain_Service();
    assert(torque_diag.denied && !(timer.BDTR & TIM_BDTR_MOE));
    for (unsigned race=0;race<2;++race) {
        reset(); TorqueChain_Command("MOTOR TEST TORQUE POS ZERO CONFIRM",out,sizeof out);
        TorqueChain_Service(); ++cl_outer_n;
        if (race) stop_in_prepare=1; else fault_in_prepare=1;
        TorqueChain_Service();
        assert(torque_diag.denied && !torque_diag.active && !(timer.BDTR & TIM_BDTR_MOE));
    }
    assert(FocTorqueChain_Angle(.01f,-5)>6.0f);
    assert(FocTorqueChain_Angle(6.28f,5)<.1f);
    assert(AS5047P_InstantRpm(1,-1,.001f)<0.0f);
    assert(AS5047P_InstantRpm(-1,-1,.001f)>0.0f);
    assert(AS5047P_ElectricalAngleRad(10507,10507,10,-1)==0.0f);
    assert(AS5047P_ElectricalAngleRad(10506,10507,10,-1)>0.0f);
    FocStartupTrace trace={0}; FocStartup_Begin(&trace,100);
    for (unsigned t=0;t<200000;t+=1000) {
        FocStartupFrame row={.us=100+t}; FocStartup_Push(&trace,row);
    }
    assert(trace.total==25 && trace.rows[24].us==192000);
    FocStartup_Stop(&trace);
    FocStartup_RundownEnd(&trace,(FocStartupFrame){.us=200100});
    assert(trace.terminal_valid && trace.fault.us==200000);
    assert(stops && invalidations); return 0;
#endif
}
