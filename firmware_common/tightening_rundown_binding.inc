/* 100 Hz application failure, not a new current/FOC protection threshold.
 * Reuse the existing process-fault latch/event/result path; no auto restart. */
__attribute__((noinline,cold,optimize("Os")))
static void Tightening_NoRotation(uint32_t elapsed_ms)
{
#if defined(FOC_PROTECTED_CLOSED_LOOP)
    /* Reuse the existing atomic gate closure/session stop. Do not leave a
     * RUNNING session with only SD low for TIM7 to mislabel as BAD_OUTPUT. */
    ProtectedLoop_Stop();
#else
    PowerStage_Disable();
#endif
    FaultDiag_Capture(FOC_DIAG_PROCESS,TIGHTEN_OUTCOME_NO_ROTATION,
        FOC_TO_NONE,elapsed_ms,RUNDOWN_START_TIMEOUT_MS);
    MotorControl_SetIdle();
    tightening_last_outcome=TIGHTEN_OUTCOME_NO_ROTATION;
    tightening_test_stage=TIGHTEN_STATE_FAULT;
    tightening_contact_candidate_ms=0U;
    tightening_contact_condition=0U;
    tightening_drive_iqref_A=0.0f;
    Protocol_SendCycleEvent("COMPLETE","NO_ROTATION");
    if (!tightening_result_printed) {
        tightening_result_printed=1U;
        TighteningResult_PrintSummary("NO_ROTATION");
    }
}
