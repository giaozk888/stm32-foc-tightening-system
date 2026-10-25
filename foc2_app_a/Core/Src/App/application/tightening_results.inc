/* App A application/tightening_results.inc: private binding, included once by main.c.
 * Keep the declared include order and original control/IRQ ownership. */
/*
 * First application-layer TighteningTask.
 *
 * This is NOT yet the final tightening algorithm.  Its purpose is to validate
 * the new separation between:
 *
 *   application command
 *        ->
 *   1 kHz motor-control service
 *        ->
 *   20 kHz current loop
 *
 * Tightening application:
 *   RUNDOWN -> CONTACT -> STOP -> SEATING -> TIGHTENING -> HOLD -> DONE
 *   Each post-contact IQ stage is sampled at 100 Hz for a final result report.
 */

static void TighteningResult_Reset(TighteningStageResult_t *r,
                                   float command_A)
{
    if (r == NULL)
    {
        return;
    }

    r->command_A = command_A;
    r->iq_sum_A = 0.0f;
    r->iq_max_A = 0.0f;
    r->ctrl_max_abs_rpm = 0.0f;
    r->det_sum_abs_rpm = 0.0f;
    r->start_position_deg = encoder_position_deg;
    r->end_position_deg = encoder_position_deg;
    r->sample_count = 0U;
}


static void TighteningResult_Sample(TighteningStageResult_t *r)
{
    float iq_drive_A;
    float ctrl_abs_rpm;
    float det_abs_rpm;

    if (r == NULL)
    {
        return;
    }

    iq_drive_A = TIGHTEN_DIRECTION * foc_iq_A;
    ctrl_abs_rpm = fabsf(encoder_speed_rpm);
    det_abs_rpm = fabsf(encoder_speed_detect_rpm);

    r->iq_sum_A += iq_drive_A;

    if ((r->sample_count == 0U) ||
        (iq_drive_A > r->iq_max_A))
    {
        r->iq_max_A = iq_drive_A;
    }

    if (ctrl_abs_rpm > r->ctrl_max_abs_rpm)
    {
        r->ctrl_max_abs_rpm = ctrl_abs_rpm;
    }

    r->det_sum_abs_rpm += det_abs_rpm;
    r->end_position_deg = encoder_position_deg;
    r->sample_count++;
}


#if defined(FOC_PWM_COMMON_MODE_ENABLE)
__attribute__((optimize("Oz"))) /* Cold result formatting only. */
#endif
static void TighteningResult_PrintStage(const char *name,
                                       const TighteningStageResult_t *r)
{
    char msg[256];
    float iq_avg_A = 0.0f;
    float det_avg_abs_rpm = 0.0f;
    float delta_deg = 0.0f;
    uint32_t duration_ms = 0U;

    int32_t cmd_mA;
    int32_t iq_avg_mA;
    int32_t iq_max_mA;
    int32_t ctrl_max_x10;
    int32_t det_avg_x10;
    int32_t delta_x100;

    if ((name == NULL) || (r == NULL))
    {
        return;
    }

    if (r->sample_count > 0U)
    {
        iq_avg_A =
            r->iq_sum_A / (float)r->sample_count;
        det_avg_abs_rpm =
            r->det_sum_abs_rpm / (float)r->sample_count;
        duration_ms = r->sample_count * 10U;
    }

    delta_deg =
        TIGHTEN_DIRECTION *
        (r->end_position_deg - r->start_position_deg);

    cmd_mA = (int32_t)(r->command_A * 1000.0f);
    iq_avg_mA = (int32_t)(iq_avg_A * 1000.0f);
    iq_max_mA = (int32_t)(r->iq_max_A * 1000.0f);
    ctrl_max_x10 = (int32_t)(r->ctrl_max_abs_rpm * 10.0f);
    det_avg_x10 = (int32_t)(det_avg_abs_rpm * 10.0f);
    delta_x100 = (int32_t)(delta_deg * 100.0f);

    UART_SendFormatted(
        msg,
        sizeof(msg),
        "%-10s Cmd=%ldmA IqAvg=%ldmA IqMax=%ldmA "
        "CtrlMax=%ld.%01ldrpm DetAvg=%ld.%01ldrpm "
        "dAng=%ld.%02lddeg T=%lums N=%lu\r\n",
        name,
        (long)cmd_mA,
        (long)iq_avg_mA,
        (long)iq_max_mA,
        (long)(ctrl_max_x10 / 10),
        (long)labs(ctrl_max_x10 % 10),
        (long)(det_avg_x10 / 10),
        (long)labs(det_avg_x10 % 10),
        (long)(delta_x100 / 100),
        (long)labs(delta_x100 % 100),
        (unsigned long)duration_ms,
        (unsigned long)r->sample_count);
}


#if defined(ESP_NETWORK_OBSERVER)
#include "network_observer.inc"
#endif
#if defined(FOC_PWM_COMMON_MODE_ENABLE)
__attribute__((optimize("Oz"))) /* Cold report only; no control/ISR optimization change. */
#endif
static void TighteningResult_PrintSummary(const char *result_text)
{
    char msg[256];
#if defined(ESP_NETWORK_OBSERVER)
    NetworkObserver_Publish(NET_KIND_RESULT);
#endif
#if defined(FOC_INTENT_FSM_CANDIDATE)
    UART_SendFormatted(msg,sizeof msg,
        "START_REQ=%lu RESULT=%s CONTACT=%u CONTACT_MDEG=%ld POST_MDEG=%ld\r\n",
        (unsigned long)tightening_cycle_request_id,result_text,tightening_contact_confirmed,
        (long)(tightening_contact_position_deg*1000.0f),
        (long)(tightening_post_contact_travel_deg*1000.0f));
#else
    UART_SendLiteral(
        "\r\n"
        "========== TIGHTEN RESULT ==========\r\n");

    UART_SendFormatted(
        msg,
        sizeof(msg),
        "Start request : %lu\r\n",
        (unsigned long)tightening_cycle_request_id);

    if (tightening_contact_confirmed != 0U)
    {
        int32_t contact_x100 =
            (int32_t)(tightening_contact_position_deg * 100.0f);
        int32_t post_x100 =
            (int32_t)(tightening_post_contact_travel_deg * 100.0f);

        UART_SendFormatted(
            msg,
            sizeof(msg),
            "RESULT        : %s\r\n"
            "Contact angle : %ld.%02ld deg\r\n"
            "Post travel   : %ld.%02ld deg\r\n",
            (result_text != NULL) ? result_text : "UNKNOWN",
            (long)(contact_x100 / 100),
            (long)labs(contact_x100 % 100),
            (long)(post_x100 / 100),
            (long)labs(post_x100 % 100));
    }
    else
    {
        UART_SendFormatted(
            msg,
            sizeof(msg),
            "RESULT        : %s\r\n"
            "Contact angle : N/A\r\n"
            "Post travel   : N/A\r\n",
            (result_text != NULL) ? result_text : "UNKNOWN");
    }


#endif
    TighteningResult_PrintStage("SEATING", &tighten_result_seating);
    TighteningResult_PrintStage("TIGHTEN#1", &tighten_result_010);
    TighteningResult_PrintStage("TIGHTEN#2", &tighten_result_012);
    TighteningResult_PrintStage("TIGHTEN#3", &tighten_result_015);
    TighteningResult_PrintStage("HOLD", &tighten_result_hold);

#if defined(FOC_INTENT_FSM_CANDIDATE)
    UART_SendLiteral("NOTE: Iq != calibrated N.m\r\n");
#else
    UART_SendLiteral(
        "NOTE: Iq values are electrical q-axis current, NOT calibrated N.m\r\n"
        "====================================\r\n\r\n");
#endif
}



static float TighteningResult_AvgIq(
    const TighteningStageResult_t *r)
{
    if ((r == NULL) || (r->sample_count == 0U))
    {
        return 0.0f;
    }

    return r->iq_sum_A / (float)r->sample_count;
}


static void TighteningRepeat_ResetCurrentCycle(void)
{
    TightenRundown_Begin(&tightening_rundown);
    tightening_contact_candidate_ms = 0U;
    tightening_contact_condition = 0U;
    tightening_contact_confirmed = 0U;
    tightening_test_elapsed_ms = 0U;

    tightening_start_position_deg = encoder_position_deg;
    tightening_travel_deg = 0.0f;

    tightening_contact_position_deg = encoder_position_deg;
    tightening_post_contact_travel_deg = 0.0f;

    tightening_drive_iqref_A = 0.0f;
    tightening_result_printed = 0U;

    TighteningResult_Reset(
        &tighten_result_seating,
        (float)recipe_state.params.seating_iq_mA / 1000.0f);
    TighteningResult_Reset(
        &tighten_result_010,
        (float)recipe_state.params.t1_iq_mA / 1000.0f);
    TighteningResult_Reset(
        &tighten_result_012,
        (float)recipe_state.params.t2_iq_mA / 1000.0f);
    TighteningResult_Reset(
        &tighten_result_015,
        (float)recipe_state.params.t3_iq_mA / 1000.0f);
    TighteningResult_Reset(
        &tighten_result_hold,
        (float)recipe_state.params.hold_iq_mA / 1000.0f);
}


static void TighteningRepeat_StoreCurrentCycle(void)
{
    TighteningCycleSummary_t *s;
    uint32_t index;

    if ((tightening_cycle_number == 0U) ||
        (tightening_cycle_number > TIGHTEN_REPEAT_CYCLES))
    {
        return;
    }

    index = tightening_cycle_number - 1U;
    s = &tightening_cycle_summary[index];

    memset(s, 0, sizeof(*s));

    s->valid = 1U;
    s->rundown_travel_deg = tightening_travel_deg;
    s->post_travel_deg = tightening_post_contact_travel_deg;

    s->seating_iq_avg_A =
        TighteningResult_AvgIq(&tighten_result_seating);
    s->tighten1_iq_avg_A =
        TighteningResult_AvgIq(&tighten_result_010);
    s->tighten2_iq_avg_A =
        TighteningResult_AvgIq(&tighten_result_012);
    s->tighten3_iq_avg_A =
        TighteningResult_AvgIq(&tighten_result_015);
    s->hold_iq_avg_A =
        TighteningResult_AvgIq(&tighten_result_hold);

    s->seating_iq_max_A = tighten_result_seating.iq_max_A;
    s->tighten3_iq_max_A = tighten_result_015.iq_max_A;
    s->hold_iq_max_A = tighten_result_hold.iq_max_A;

    tightening_cycle_ok_count++;
}


static void TighteningRepeat_PrintAggregate(void)
{
    char msg[320];
    uint32_t i;
    uint32_t n = 0U;

    float post_sum = 0.0f;
    float post_min = 1.0e9f;
    float post_max = -1.0e9f;

    float seat_sum = 0.0f;
    float t1_sum = 0.0f;
    float t2_sum = 0.0f;
    float t3_sum = 0.0f;
    float hold_sum = 0.0f;

    float hold_peak_max = 0.0f;

    UART_SendLiteral(
        "\r\n"
        "========== 5-CYCLE REPEATABILITY ==========\r\n");

    for (i = 0U; i < TIGHTEN_REPEAT_CYCLES; i++)
    {
        const TighteningCycleSummary_t *s =
            &tightening_cycle_summary[i];

        int32_t post_x100;
        int32_t seat_mA;
        int32_t t1_mA;
        int32_t t2_mA;
        int32_t t3_mA;
        int32_t hold_mA;
        int32_t hold_peak_mA;

        if (s->valid == 0U)
        {
            continue;
        }

        n++;

        post_sum += s->post_travel_deg;
        if (s->post_travel_deg < post_min)
        {
            post_min = s->post_travel_deg;
        }
        if (s->post_travel_deg > post_max)
        {
            post_max = s->post_travel_deg;
        }

        seat_sum += s->seating_iq_avg_A;
        t1_sum += s->tighten1_iq_avg_A;
        t2_sum += s->tighten2_iq_avg_A;
        t3_sum += s->tighten3_iq_avg_A;
        hold_sum += s->hold_iq_avg_A;

        if (s->hold_iq_max_A > hold_peak_max)
        {
            hold_peak_max = s->hold_iq_max_A;
        }

        post_x100 =
            (int32_t)(s->post_travel_deg * 100.0f);
        seat_mA =
            (int32_t)(s->seating_iq_avg_A * 1000.0f);
        t1_mA =
            (int32_t)(s->tighten1_iq_avg_A * 1000.0f);
        t2_mA =
            (int32_t)(s->tighten2_iq_avg_A * 1000.0f);
        t3_mA =
            (int32_t)(s->tighten3_iq_avg_A * 1000.0f);
        hold_mA =
            (int32_t)(s->hold_iq_avg_A * 1000.0f);
        hold_peak_mA =
            (int32_t)(s->hold_iq_max_A * 1000.0f);

        UART_SendFormatted(
            msg,
            sizeof(msg),
            "Cycle %lu: Post=%ld.%02lddeg "
            "IqAvg[%ld,%ld,%ld,%ld,%ld]mA "
            "HoldPeak=%ldmA\r\n",
            (unsigned long)(i + 1U),
            (long)(post_x100 / 100),
            (long)labs(post_x100 % 100),
            (long)seat_mA,
            (long)t1_mA,
            (long)t2_mA,
            (long)t3_mA,
            (long)hold_mA,
            (long)hold_peak_mA);
    }

    if (n > 0U)
    {
        int32_t post_avg_x100 =
            (int32_t)((post_sum / (float)n) * 100.0f);
        int32_t post_min_x100 =
            (int32_t)(post_min * 100.0f);
        int32_t post_max_x100 =
            (int32_t)(post_max * 100.0f);

        int32_t seat_avg_mA =
            (int32_t)((seat_sum / (float)n) * 1000.0f);
        int32_t t1_avg_mA =
            (int32_t)((t1_sum / (float)n) * 1000.0f);
        int32_t t2_avg_mA =
            (int32_t)((t2_sum / (float)n) * 1000.0f);
        int32_t t3_avg_mA =
            (int32_t)((t3_sum / (float)n) * 1000.0f);
        int32_t hold_avg_mA =
            (int32_t)((hold_sum / (float)n) * 1000.0f);
        int32_t hold_peak_mA =
            (int32_t)(hold_peak_max * 1000.0f);

        UART_SendFormatted(
            msg,
            sizeof(msg),
            "SUCCESS       : %lu/%u cycles\r\n"
            "PostTravel    : avg=%ld.%02lddeg "
            "min=%ld.%02lddeg max=%ld.%02lddeg\r\n"
            "IqAvg mean mA : SEAT=%ld T1=%ld T2=%ld T3=%ld HOLD=%ld\r\n"
            "Worst HoldPeak: %ldmA\r\n",
            (unsigned long)n,
            (unsigned int)TIGHTEN_REPEAT_CYCLES,
            (long)(post_avg_x100 / 100),
            (long)labs(post_avg_x100 % 100),
            (long)(post_min_x100 / 100),
            (long)labs(post_min_x100 % 100),
            (long)(post_max_x100 / 100),
            (long)labs(post_max_x100 % 100),
            (long)seat_avg_mA,
            (long)t1_avg_mA,
            (long)t2_avg_mA,
            (long)t3_avg_mA,
            (long)hold_avg_mA,
            (long)hold_peak_mA);
    }

    UART_SendLiteral(
        "NOTE: repeatability includes manual-load variation.\r\n"
        "Iq is electrical q-axis current, NOT calibrated N.m\r\n"
        "=============================================\r\n\r\n");
}



