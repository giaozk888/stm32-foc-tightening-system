/* App A storage/recipe_storage.inc: private binding, included once by main.c.
 * Keep the declared include order and original control/IRQ ownership. */
static uint32_t SystemPreflight_FailMask(void)
{
    uint32_t mask = 0U;
#if defined(SAFETY_LOCKED_BOOT)
    mask |= PREFLIGHT_FAIL_BOOT_LOCK;
#endif

    if (adc_fault != 0U) mask |= PREFLIGHT_FAIL_ADC_FAULT;
    if (foc_fault != 0U) mask |= PREFLIGHT_FAIL_FOC_FAULT;
    if (encoder_valid == 0U) mask |= PREFLIGHT_FAIL_ENCODER;
    if (foc_enable == 0U) mask |= PREFLIGHT_FAIL_FOC_DISABLED;
    if (run_zero_cal_done == 0U) mask |= PREFLIGHT_FAIL_ZERO_CAL;
    if (UART_Async_IsReady() == 0U) mask |= PREFLIGHT_FAIL_UART;
    if (motor_control_mode != MOTOR_MODE_IDLE) mask |= PREFLIGHT_FAIL_MODE;
    if (fabsf(encoder_speed_rpm) > TIGHTEN_REPEAT_RESTART_MAX_RPM)
    {
        mask |= PREFLIGHT_FAIL_SPEED;
    }
    if (fw_update.active != 0U) mask |= PREFLIGHT_FAIL_FW_UPDATE;
    if (BootHealth_IsCurrentTrial() != 0U) mask |= PREFLIGHT_FAIL_TRIAL;
    if ((xTaskGetTickCount() - preflight_adc_progress_tick) >
        pdMS_TO_TICKS(PREFLIGHT_CHAIN_MAX_STALE_MS))
    {
        mask |= PREFLIGHT_FAIL_ADC_STALE;
    }
    if ((xTaskGetTickCount() - preflight_foc_progress_tick) >
        pdMS_TO_TICKS(PREFLIGHT_CHAIN_MAX_STALE_MS))
    {
        mask |= PREFLIGHT_FAIL_FOC_STALE;
    }
    return mask;
}

#include "motor_job_port.inc"

static void Protocol_PrintSelftestStatus(uint32_t request_id)
{
    uint32_t mask = SystemPreflight_FailMask();
    TickType_t now = xTaskGetTickCount();
    char msg[192];

    (void)Protocol_SendFormatted(msg, sizeof(msg),
             "%lu OK SELFTEST READY=%u MASK=0x%03lX ADC=%u FOC=%u ENC=%u ZERO=%u UART=%u MODE=%s SPEED_OK=%u AAGE=%lu FAGE=%lu ADC_CNT=%lu FOC_CNT=%lu\r\n",
             (unsigned long)request_id,
             mask == 0U ? 1U : 0U,
             (unsigned long)mask,
             adc_fault == 0U ? 1U : 0U,
             (foc_fault == 0U) && (foc_enable != 0U) ? 1U : 0U,
             encoder_valid,
             run_zero_cal_done,
             UART_Async_IsReady(),
             MotorControl_ModeName(motor_control_mode),
             (mask & PREFLIGHT_FAIL_SPEED) == 0U ? 1U : 0U,
             (unsigned long)(now - preflight_adc_progress_tick),
             (unsigned long)(now - preflight_foc_progress_tick),
             (unsigned long)injected_seq_count,
             (unsigned long)foc_control_count);
}


static void TightenParams_RestoreDefaults(void)
{
    TightenParams_ResetDefaults(&recipe_state.params);
    recipe_state.dirty = 1U;
}

static uint32_t TightenParams_Crc32(const uint8_t *data, size_t length)
{
    uint32_t crc = 0xFFFFFFFFUL;
    size_t i;
    uint32_t bit;

    for (i = 0U; i < length; i++)
    {
        crc ^= (uint32_t)data[i];
        for (bit = 0U; bit < 8U; bit++)
        {
            if ((crc & 1UL) != 0UL)
                crc = (crc >> 1U) ^ 0xEDB88320UL;
            else
                crc >>= 1U;
        }
    }
    return ~crc;
}

/* Hardware boundary only; storage policy and record ABI live in C++. */
static int TightenParams_PortLoad(void *context, void *data, size_t length)
{
    (void)context;
    return PW_Kvs_LoadParams(data, length);
}

static int TightenParams_PortSave(void *context, const void *data, size_t length)
{
    (void)context;
    return PW_Kvs_SaveParams(data, length);
}

static void TightenParams_PortReadLegacy(void *context, void *data, size_t length)
{
    (void)context;
    memcpy(data, (const void *)PARAM_FLASH_ADDRESS, length);
}

_Static_assert(PW_KVS_RESULT_OK == 0 && PW_KVS_RESULT_NOT_FOUND == 1 &&
               PW_KVS_RESULT_ERROR == 2, "Parameter storage port result ABI");

static const TightenParamsStoragePort_t params_storage_port =
{
    NULL, TightenParams_PortLoad, TightenParams_PortSave,
    TightenParams_PortReadLegacy
};

static uint8_t TightenParams_SaveToFlash(void)
{
    return TightenParams_StorageSave(&recipe_state, &params_storage_port);
}

static TightenParamsFlashLoadStatus_t TightenParams_LoadFromFlash(void)
{
    return TightenParams_StorageLoad(&recipe_state, &params_storage_port);
}

#if defined(FOC_RUNDOWN240_CANDIDATE)
static void TightenParams_ApplyRundown240Candidate(void)
{
    /* Startup only, after normal load/defaults and before tasks/START.
     * Never persist A candidate recipe overrides into B. */
    recipe_state.params.rundown_rpm=FOC_RUNDOWN240_TARGET_RPM;
#if defined(FOC_RUNDOWN240_TRAVEL20000)
    recipe_state.params.max_travel_deg=FOC_RUNDOWN240_MAX_TRAVEL_DEG;
#endif
#if defined(FOC_DOB_CONTACT20_OBSERVE10)
    recipe_state.params.contact_rpm=DOB_CONTACT20_RPM;
#endif
    recipe_state.dirty=1U;
}
#endif


/*
 * IAP A/B boot metadata V2 + UART firmware-update helpers.
 *
 * Flash layout:
 *   Bank2 Page126 @ 0x0807F000 : boot metadata
 *   Bank2 Page127 @ 0x0807F800 : tightening parameters
 *
 * The bootloader accepts both legacy V1 metadata and V2 metadata. Once an
 * application writes V2, all later boot selection / trial / rollback state is
 * carried by V2.
 */
