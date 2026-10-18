/* Actual production snapshot + protected binding, no serial/debugger/hardware. */
#define FOC_TIMEOUT_DIAGNOSTICS 1
#define FOC_PROTECTION_HOST_TEST 1
#define main legacy_cases_compiled_not_executed
#include "protected_closed_loop_host.c"
#undef main
#include "foc_encoder_timeout_diag.h"
#include "foc_current_protection_layers.h"

static void poll_sources(void)
{
    FocFilteredProtection p;
    FocFilteredProtectionConfig cfg={4.0f,100U,100U,6U,4U};
    FocFp_Begin(&p,cfg,UINT32_MAX-50U);
    assert(FocFp_Poll(&p,49U,0U)!=FOC_OC_TRIPPED);
    assert(FocFp_Poll(&p,50U,0U)==FOC_OC_TRIPPED);
    assert(p.timeout.reason==FOC_TO_CURRENT_FIRST_SAMPLE && p.timeout.reference_us==UINT32_MAX-50U);
    FocTimeoutLatch saved=p.timeout;
    FocFp_Poll(&p,500U,FOC_FP_HW_TRIP);
    assert(!memcmp(&saved,&p.timeout,sizeof saved));
    FocFp_Begin(&p,cfg,0U); p.seq_valid=1U; p.last_us=50U;
    assert(FocFp_Poll(&p,150U,0U)!=FOC_OC_TRIPPED);
    assert(FocFp_Poll(&p,151U,0U)==FOC_OC_TRIPPED);
    assert(p.timeout.reason==FOC_TO_CURRENT_SAMPLE);
    FocFp_Begin(&p,cfg,0U); p.seq_valid=1U; p.last_us=150U;
    p.pending=1U; p.pending_us=50U; p.misses=1U;
    assert(FocFp_Poll(&p,150U,0U)!=FOC_OC_TRIPPED);
    assert(FocFp_Poll(&p,151U,0U)!=FOC_OC_TRIPPED);
    assert(!p.timeout.reason && !p.confirm_cycles); /* Poll is not an ADC pair. */
    FocFp_Begin(&p,cfg,0U); p.seq_valid=p.pending=1U; p.last_us=p.pending_us=50U;
    FocFp_Poll(&p,151U,0U); assert(p.timeout.reason==FOC_TO_CURRENT_SAMPLE);
    FocFp_Begin(&p,cfg,0U); FocFp_Poll(&p,500U,FOC_FP_HW_TRIP);
    assert(p.reason==FOC_FP_HARDWARE && !p.timeout.reason);
    FocCurrentProtection legacy;
    FocOcConfirmConfig lc={4.0f,.01f,1551U,1551U};
    FocProtection_Begin(&legacy,FOC_PROTECT_STRICT_4A,lc,0U);
    FocProtection_Poll(&legacy,101U,0U);
    assert(legacy.core.timeout.reason==FOC_TO_CURRENT_FIRST_SAMPLE);
    FocProtection_Begin(&legacy,FOC_PROTECT_STRICT_4A,lc,0U);
    legacy.core.pending=1U; legacy.core.pending_us=0U;
    FocProtection_Poll(&legacy,101U,0U);
    assert(legacy.core.reason==FOC_OC_DEADLINE && legacy.core.timeout.reason==FOC_TO_CURRENT_CONFIRM);
}
static void encoder_sources(void)
{
    AsDmaCursor cursor={0};
    AsDmaSample s={.status=AS_DMA_PARITY};
    assert(FocEncoder_TimeoutReason(&cursor,&s,5000U)==FOC_TO_NONE);
    s.status=AS_DMA_TIMEOUT;
    assert(FocEncoder_TimeoutReason(&cursor,&s,0U)==FOC_TO_ENCODER_TRANSACTION);
    s.status=AS_DMA_CONTROL_STALE;
    assert(FocEncoder_TimeoutReason(&cursor,&s,0U)==FOC_TO_ENCODER_CONTROL);
    s.status=AS_DMA_SCHEDULE;
    assert(FocEncoder_TimeoutReason(&cursor,&s,0U)==FOC_TO_ENCODER_SCHEDULE);
    s.status=AS_DMA_IO;
    assert(FocEncoder_TimeoutReason(&cursor,&s,5000U)==FOC_TO_NONE);
    s.status=AS_DMA_OK; s.sample_us=100U;
    assert(FocEncoder_TimeoutReason(&cursor,&s,1601U)==FOC_TO_ENCODER_SAMPLE);
    s.elapsed_us=200U;
    assert(FocEncoder_TimeoutReason(&cursor,&s,100U)==FOC_TO_ENCODER_TRANSACTION);
    s.elapsed_us=199U; s.sample_us=3000U; cursor.valid=1U; cursor.sample_us=100U;
    assert(FocEncoder_TimeoutReason(&cursor,&s,3000U)==FOC_TO_ENCODER_INTERVAL);
    cursor.sample_us=s.sample_us;
    assert(FocEncoder_TimeoutReason(&cursor,&s,3000U)==FOC_TO_NONE);
}
/* Offline causal boundary replay, not the uncaptured first-hit amplitude.
 * The actual board latch was pending=1, misses=1, last=start+50, now=start+103.
 * Synthetic amplitudes merely establish that same legal pending state. */
static void raw_confirmation_boundary_replay(void)
{
    const uint32_t start=2449527U;
    FocFilteredProtection p;
    FocFilteredProtectionConfig cfg={4.0f,100U,100U,6U,4U};
    FocFp_Begin(&p,cfg,start);
    assert(FocFp_PushRawSafety(&p,1U,start,1400U,1560U,1563U,1560U,100U,0U)==FOC_OC_PENDING);
    assert(FocFp_PushRawSafety(&p,2U,start+50U,1563U,1560U,1563U,1560U,100U,0U)==FOC_OC_PENDING);
    FocFilteredProtection on_time=p;
    assert(FocFp_PushRawSafety(&on_time,3U,start+100U,1570U,1565U,1563U,1560U,100U,0U)==FOC_OC_CLEAR);
    assert(FocFp_PushRawSafety(&p,3U,start+103U,1570U,1565U,1563U,1560U,100U,0U)==FOC_OC_CLEAR);
    assert(!p.pending && !p.confirm_cycles && !p.good_samples && !p.timeout.reason);
    assert(p.cur_confirm_enter_count==1U && p.cur_confirm_clear_count==1U);
    assert(p.cur_confirm_max_cycles==2U && p.cur_confirm_max_elapsed_us==103U);
}
static void windows(void)
{
    FocHoldWindow w={0};
    FocHoldWindow_Update(&w,UINT32_MAX-500U,UINT32_MAX-3U,UINT32_MAX-100U);
    FocHoldWindow_Update(&w,498U,6U,19900U); assert(w.window_ms==0U);
    FocHoldWindow_Update(&w,499U,6U,19900U);
    assert(w.window_ms==1000U && w.count==10U && w.maximum==10U && w.rate_per_mille==0U);
    FocHoldWindow_Update(&w,1699U,26U,39900U);
    assert(w.window_ms==1200U && w.count==20U && w.maximum==20U && w.rate_per_mille==1U);
    FocHoldWindow_Update(&w,2699U,26U,39900U);
    assert(w.count==0U && w.maximum==20U && !w.rate_per_mille);
}
static void snapshots(void)
{
    ready(); cl_current_cycles=(FocCurrentCycleStats){0};
    tightening_test_stage=3U; tightening_test_elapsed_ms=123U;
    foc_iq_ref_A=.4f; encoder_speed_rpm=4.8f; position_target_deg=100.0f;
    uint32_t before=current_hold_total;
    assert(!pair(1650U,1551U) && current_hold_total==before+1U);
    assert(pair(1551U,1551U) && current_hold_total==before+1U);
    /* Real fresh-pair path exhausts the cycle budget; no synthetic wall trip. */
    for (unsigned i=0U;i<=CUR_CONFIRM_MAX_CYCLES;++i) {
        t2.CNT+=50U;
        FocFp_PushRawSafety(&cl_safety.protection,cl_safety.protection.last_seq+1U,
            t2.CNT,900U,1551U,1551U,1551U,595U,0U);
    }
    assert(cl_safety.protection.result==FOC_OC_TRIPPED);
    ProtectedLoop_EmergencyOff(0U); off();
    assert(foc_fault_snapshot.valid && foc_fault_snapshot.timeout_reason==FOC_TO_CURRENT_CONFIRM);
    assert(foc_fault_snapshot.timeout.elapsed_us==200U && foc_fault_snapshot.timeout.pending);
    assert(!foc_fault_snapshot.timeout.limit_us && cl_safety.protection.cur_confirm_fault_count==1U);
    assert(foc_fault_snapshot.iq_ref_A==.4f && foc_iq_ref_A==0.0f);
    assert(foc_fault_snapshot.state_elapsed_ms==123U && foc_fault_snapshot.current_suspect_total==1U);
    FocFaultSnapshot saved=foc_fault_snapshot;
    foc_iq_ref_A=1.0f; encoder_speed_rpm=9.0f; ProtectedLoop_EmergencyOff(CL_BAD_ADC);
    assert(!memcmp(&saved,(const void *)&foc_fault_snapshot,sizeof saved));
    snapshot_tx_budget=3U; FaultDiag_Monitor(); assert(fault_snapshot_print_index==3U);
    snapshot_tx_budget=1000U; FaultDiag_Monitor();
    assert(strstr(snapshot_log,"TIMEOUT_SUBREASON=CUR_CONFIRM"));
    assert(strstr(snapshot_log,"IqRef=400\r\n") && strstr(snapshot_log,"SPD_FILT=4800\r\n"));
    assert(strstr(snapshot_log,"PEND=1\r\n") && strstr(snapshot_log,"END CPU_HZ=170000000"));
    size_t n=snapshot_log_size; FaultDiag_Monitor(); assert(n==snapshot_log_size);
    FaultDiag_Clear(); assert(!foc_fault_snapshot.valid && !fault_snapshot_print_index);
    cl_safety.protection=(FocFilteredProtection){0}; cl_direct_timeout=(FocTimeoutEvidence){0};
    FaultDiag_Capture(FOC_DIAG_PROCESS,1U,FOC_TO_RUNDOWN,8001U,8000U);
    assert(foc_fault_snapshot.timeout.elapsed_us==8001000U && foc_fault_snapshot.timeout.limit_us==8000000U);
    assert(foc_fault_snapshot.state_elapsed_ms==123U);
    FaultDiag_Clear(); FaultDiag_Motor(3U); assert(foc_fault_snapshot.fault_reason==3U);
    /* Every printed word must have exactly one schema name, with no overrun. */
    unsigned fields=0U; for (const char *p=fault_diag_labels;*p;++p) fields+=*p=='|';
    assert(fields==sizeof(FocFaultSnapshot)/4U-1U);
    unsigned names=0U; for (const char *p=fault_timeout_names;*p;++p) names+=*p=='|';
    assert(names==(unsigned)FOC_TO_UNKNOWN+1U);
    printf("PASS timeout sources / wrap / first fault / gate off / real ISR hold / queue resume; snapshot=%u bytes\n",
        (unsigned)sizeof(FocFaultSnapshot));
}
static void other_shutdown_sources(void)
{
    ready(); cl_session.outer_us=t2.CNT-2001U;
    ProtectedLoop_EmergencyOff(CL_OUTER_STALE); off();
    assert(foc_fault_snapshot.timeout_reason==FOC_TO_OUTER_CONTROL);
    assert(foc_fault_snapshot.timeout.elapsed_us==2001U && foc_fault_snapshot.timeout.limit_us==2000U);
    assert(foc_fault_snapshot.protection_flags==CL_OUTER_STALE);
    assert(foc_fault_snapshot.fault_reason==FOC_FP_HEALTH);
    ready(); t2.CNT+=101U; t7.SR=TIM_SR_UIF; TIM7_DAC_IRQHandler(); off();
    assert(foc_fault_snapshot.timeout_reason==FOC_TO_ADC_GUARD && foc_fault_snapshot.timeout.elapsed_us==101U);
    ready(); ProtectedLoop_WorkEnd(t2.CNT-50U); off();
    assert(foc_fault_snapshot.timeout_reason==FOC_TO_COMPUTE_WALL && foc_fault_snapshot.timeout.elapsed_us==50U);
    ready(); cl_current_cycles=(FocCurrentCycleStats){0}; mock_dwt.CYCCNT=8500U;
    ProtectedLoop_AdcProfileEnd(0U); off();
    assert(foc_fault_snapshot.timeout_reason==FOC_TO_COMPUTE_DEADLINE && foc_fault_snapshot.foc_cycles_max==8500U);
    ready(); encoder_timeout_reason=FOC_TO_ENCODER_TRANSACTION;
    ProtectedLoop_EmergencyOff(CL_BAD_ENCODER); off();
    assert(foc_fault_snapshot.timeout_reason==FOC_TO_ENCODER_TRANSACTION);
}
int main(void) { (void)MotorControl_SetSpeed; ProtectedLoop_CurrentMonitor(); poll_sources(); encoder_sources(); raw_confirmation_boundary_replay(); windows(); snapshots(); other_shutdown_sources(); return 0; }
