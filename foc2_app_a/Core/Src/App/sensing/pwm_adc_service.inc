/* App A sensing/pwm_adc_service.inc: private binding, included once by main.c.
 * Keep the declared include order and original control/IRQ ownership. */
static void PWM_StartAll(void)
{
#if defined(FOC_PROTECTED_CLOSED_LOOP)
    PowerStage_Disable(); TIM1->CCER=0U;
    TIM1->BDTR &= ~(TIM_BDTR_MOE | TIM_BDTR_AOE);
    return;
#endif
#if defined(ZERO_RETEST_BOOT)
    PowerStage_Disable();
    TIM1->CCER = 0U;
    TIM1->BDTR &= ~(TIM_BDTR_MOE | TIM_BDTR_AOE);
    return;
#endif
#if defined(FOC_ISOLATED_CONCURRENCY)
    /* Internal CH4 trigger is started only by the bounded fixture. */
    PowerStage_Disable();
    TIM1->CCER = 0U;
    TIM1->BDTR &= ~(TIM_BDTR_MOE | TIM_BDTR_AOE);
    return;
#endif
    if (analog_safe_latched != 0U)
    {
        PowerStage_Disable();
        __HAL_TIM_MOE_DISABLE(&htim1);
        return;
    }

#if defined(FOC_ADC_WINDOW)
    PWM_SetDuty(0.5f, 0.5f, 0.5f);
    if (adc_fault != 0U || !FocAdcTiming_CanStart())
    {
        PowerStage_Disable();
        __HAL_TIM_MOE_DISABLE(&htim1);
        return;
    }
#else
    __HAL_TIM_SET_COMPARE(&htim1, TIM_CHANNEL_1, PWM_HALF);
    __HAL_TIM_SET_COMPARE(&htim1, TIM_CHANNEL_2, PWM_HALF);
    __HAL_TIM_SET_COMPARE(&htim1, TIM_CHANNEL_3, PWM_HALF);
    __HAL_TIM_SET_COMPARE(&htim1, TIM_CHANNEL_4, ADC_TRIGGER_CCR4);
#endif

    if (HAL_TIM_PWM_Start(&htim1, TIM_CHANNEL_4) != HAL_OK) Error_Handler();

    if (HAL_TIM_PWM_Start(&htim1, TIM_CHANNEL_1) != HAL_OK) Error_Handler();
    if (HAL_TIM_PWM_Start(&htim1, TIM_CHANNEL_2) != HAL_OK) Error_Handler();
    if (HAL_TIM_PWM_Start(&htim1, TIM_CHANNEL_3) != HAL_OK) Error_Handler();

    if (HAL_TIMEx_PWMN_Start(&htim1, TIM_CHANNEL_1) != HAL_OK) Error_Handler();
    if (HAL_TIMEx_PWMN_Start(&htim1, TIM_CHANNEL_2) != HAL_OK) Error_Handler();
    if (HAL_TIMEx_PWMN_Start(&htim1, TIM_CHANNEL_3) != HAL_OK) Error_Handler();
}

static void PWM_StopAll(void)
{
    HAL_TIMEx_PWMN_Stop(&htim1, TIM_CHANNEL_1);
    HAL_TIMEx_PWMN_Stop(&htim1, TIM_CHANNEL_2);
    HAL_TIMEx_PWMN_Stop(&htim1, TIM_CHANNEL_3);

    HAL_TIM_PWM_Stop(&htim1, TIM_CHANNEL_1);
    HAL_TIM_PWM_Stop(&htim1, TIM_CHANNEL_2);
    HAL_TIM_PWM_Stop(&htim1, TIM_CHANNEL_3);
    HAL_TIM_PWM_Stop(&htim1, TIM_CHANNEL_4);
}

static HAL_StatusTypeDef ADC_ReadRegularMedian(ADC_HandleTypeDef *hadc,
                                               uint32_t channel,
                                               uint16_t *raw)
{
    ADC_ChannelConfTypeDef cfg = {0};
    uint16_t x[ADC_MEDIAN_SAMPLES];
    HAL_StatusTypeDef st;
    char dbg[180];
    const char *adc_name = (hadc->Instance == ADC1) ? "ADC1" :
                           (hadc->Instance == ADC2) ? "ADC2" : "ADC?";

    /*
     * Diagnostic version: print only when a HAL operation fails.
     */
    st = HAL_ADC_Stop(hadc);
    if ((st != HAL_OK) && (st != HAL_ERROR))
    {
        UART_SendFormatted(dbg, sizeof(dbg),
                 "ZERO DBG %s: HAL_ADC_Stop st=%d state=0x%08lX err=0x%08lX\r\n",
                 adc_name, (int)st,
                 (unsigned long)HAL_ADC_GetState(hadc),
                 (unsigned long)HAL_ADC_GetError(hadc));
    }

    cfg.Channel = channel;
    cfg.Rank = ADC_REGULAR_RANK_1;
    /* PC4/PC5 sampling time must be configured before injected ADC2 starts. */
    cfg.SamplingTime = (channel == ADC_CHANNEL_VREFINT)
                           ? ADC_SAMPLETIME_640CYCLES_5
                           : ((hadc->Instance == ADC2) &&
                              ((channel == ADC_CHANNEL_5) ||
                               (channel == ADC_CHANNEL_11)))
                                 ? ANALOG_GPIO_SAMPLE_TIME
                                 : ADC_SAMPLETIME_47CYCLES_5;
    cfg.SingleDiff = ADC_SINGLE_ENDED;
    cfg.OffsetNumber = ADC_OFFSET_NONE;
    cfg.Offset = 0;

    st = HAL_ADC_ConfigChannel(hadc, &cfg);
    if (st != HAL_OK)
    {
        UART_SendFormatted(dbg, sizeof(dbg),
                 "ZERO DBG %s: ConfigChannel FAIL st=%d state=0x%08lX err=0x%08lX\r\n",
                 adc_name, (int)st,
                 (unsigned long)HAL_ADC_GetState(hadc),
                 (unsigned long)HAL_ADC_GetError(hadc));
        return HAL_ERROR;
    }

    for (uint32_t i = 0U; i < ADC_MEDIAN_SAMPLES; i++)
    {
        st = HAL_ADC_Start(hadc);
        if (st != HAL_OK)
        {
            UART_SendFormatted(dbg, sizeof(dbg),
                     "ZERO DBG %s: Start FAIL sub=%lu st=%d state=0x%08lX err=0x%08lX\r\n",
                     adc_name, (unsigned long)i, (int)st,
                     (unsigned long)HAL_ADC_GetState(hadc),
                     (unsigned long)HAL_ADC_GetError(hadc));
            return HAL_ERROR;
        }

        st = HAL_ADC_PollForConversion(hadc, 10U);
        if (st != HAL_OK)
        {
            UART_SendFormatted(dbg, sizeof(dbg),
                     "ZERO DBG %s: Poll FAIL sub=%lu st=%d state=0x%08lX err=0x%08lX tick=%lu\r\n",
                     adc_name, (unsigned long)i, (int)st,
                     (unsigned long)HAL_ADC_GetState(hadc),
                     (unsigned long)HAL_ADC_GetError(hadc),
                     (unsigned long)HAL_GetTick());
            HAL_ADC_Stop(hadc);
            return HAL_ERROR;
        }

        x[i] = (uint16_t)HAL_ADC_GetValue(hadc);

        st = HAL_ADC_Stop(hadc);
        if ((st != HAL_OK) && (st != HAL_ERROR))
        {
            UART_SendFormatted(dbg, sizeof(dbg),
                     "ZERO DBG %s: Stop-after-read st=%d state=0x%08lX err=0x%08lX\r\n",
                     adc_name, (int)st,
                     (unsigned long)HAL_ADC_GetState(hadc),
                     (unsigned long)HAL_ADC_GetError(hadc));
        }
    }

    for (uint32_t i = 0U; i < ADC_MEDIAN_SAMPLES - 1U; i++)
    {
        for (uint32_t j = i + 1U; j < ADC_MEDIAN_SAMPLES; j++)
        {
            if (x[j] < x[i])
            {
                uint16_t t = x[i];
                x[i] = x[j];
                x[j] = t;
            }
        }
    }

    *raw = x[ADC_MEDIAN_SAMPLES / 2U];
    return HAL_OK;
}

static HAL_StatusTypeDef ADC_CurrentZeroCalibrate(void)
{
    uint32_t su = 0U;
    uint32_t sv = 0U;
    uint16_t u = 0U;
    uint16_t v = 0U;
    char msg[220];

    /*
     * PC3 / AMP_IW is intentionally NOT used.
     * Only PA0/ADC1=IU and PA1/ADC2=IV are calibrated.
     */
    PowerStage_Disable();
    PWM_StopAll();

    UART_SendLiteral(
        "\r\nTWO-PHASE CURRENT ZERO CALIBRATION\r\n"
        "CTRL_SD=LOW, PWM=OFF, PD6010B 12V must be ON\r\n"
        "AMP_IU->PA0/ADC1, AMP_IV->PA1/ADC2, PC3 unused\r\n");

    UART_SendLiteral("ZERO DBG: settling 1000 ms...\r\n");
    HAL_Delay(1000U);
    UART_SendLiteral("ZERO DBG: settle complete, starting ADC reads\r\n");

    for (uint32_t i = 0U; i < ADC_ZERO_CAL_SAMPLES; i++)
    {
        if (ADC_ReadRegularMedian(&hadc1, ADC_CHANNEL_1, &u) != HAL_OK)
        {
            UART_SendFormatted(msg, sizeof(msg),
                     "ZERO DBG: ADC1 read failed at sample=%lu\r\n",
                     (unsigned long)i);
            return HAL_ERROR;
        }

        if (ADC_ReadRegularMedian(&hadc2, ADC_CHANNEL_2, &v) != HAL_OK)
        {
            UART_SendFormatted(msg, sizeof(msg),
                     "ZERO DBG: ADC2 read failed at sample=%lu\r\n",
                     (unsigned long)i);
            return HAL_ERROR;
        }

        su += u;
        sv += v;

        if ((i == 0U) || (i == 99U) || (i == 249U) || (i == 499U))
        {
            UART_SendFormatted(msg, sizeof(msg),
                     "ZERO DBG sample=%lu U=%u V=%u tick=%lu\r\n",
                     (unsigned long)i,
                     (unsigned int)u,
                     (unsigned int)v,
                     (unsigned long)HAL_GetTick());
        }

        HAL_Delay(1U);
    }

    iu_zero_raw = (uint16_t)(su / ADC_ZERO_CAL_SAMPLES);
    iv_zero_raw = (uint16_t)(sv / ADC_ZERO_CAL_SAMPLES);

    UART_SendFormatted(msg, sizeof(msg),
             "ZERO DBG AVG: U=%u V=%u valid-range=1000..2200\r\n",
             (unsigned int)iu_zero_raw,
             (unsigned int)iv_zero_raw);

    /*
     * W is reconstructed, so this is only a numerical center for pseudo-raw W.
     * It is NOT a measurement from PC3.
     */
    iw_zero_raw = 2048U;

    if ((iu_zero_raw < 1000U) || (iu_zero_raw > 2200U) ||
        (iv_zero_raw < 1000U) || (iv_zero_raw > 2200U))
    {
        UART_SendLiteral(
            "ZERO DBG: average OUT OF RANGE. Check PD6010B 12V/current-sense outputs.\r\n");
        return HAL_ERROR;
    }

    UART_SendFormatted(msg, sizeof(msg),
             "ZERO CAL DONE\r\n"
             "U_ZERO_RAW=%u\r\n"
             "V_ZERO_RAW=%u\r\n"
             "W is reconstructed; PC3/AMP_IW is not used\r\n",
             iu_zero_raw,
             iv_zero_raw);
    return HAL_OK;
}

/*
 * Diagnostic only: ADC2 regular conversions run before the 20 kHz injected
 * IV conversion is armed.  ADC_ReadRegularMedian() stops ADC2 after each
 * reading, so it MUST NOT be called after injected sampling has started.
 * Report by MCU pin until the physical VBUS/VTEMP wire order is confirmed.
 */
static void ADC_AnalogBootSnapshot(void)
{
    GPIO_InitTypeDef gpio = {0};
    uint16_t pc4 = 0U;
    uint16_t pc5 = 0U;

    gpio.Pin = GPIO_PIN_4 | GPIO_PIN_5;
    gpio.Mode = GPIO_MODE_ANALOG;
    gpio.Pull = GPIO_NOPULL;
    HAL_GPIO_Init(GPIOC, &gpio);

    if ((ADC_ReadRegularMedian(&hadc2, ADC_CHANNEL_5, &pc4) == HAL_OK) &&
        (ADC_ReadRegularMedian(&hadc2, ADC_CHANNEL_11, &pc5) == HAL_OK))
    {
        analog_boot_pc4_raw = pc4;
        analog_boot_pc5_raw = pc5;
        __DMB();
        analog_boot_valid = 1U;
    }
    else
    {
        analog_boot_valid = 0U;
        UART_SendLiteral("ANALOG BOOT: ADC2 one-shot read unavailable\r\n");
    }
}

/*
 * ADC2 cannot sample VREFINT on STM32G474.  Read it once through ADC1 before
 * either ADC's 20 kHz injected conversion is armed.  The factory constant
 * estimates the board's VREF+/VDDA; this is display calibration only.
 */
static void ADC_VrefBootSnapshot(void)
{
    uint16_t raw = 0U;
    uint32_t vdda_mv = 0U;
    uint16_t factory_cal = *VREFINT_CAL_ADDR;

    if ((factory_cal == 0U) || (factory_cal == UINT16_MAX) ||
        (ADC_ReadRegularMedian(&hadc1, ADC_CHANNEL_VREFINT, &raw) != HAL_OK) ||
        (raw == 0U) || (raw >= ADC_FULL_SCALE))
    {
        analog_vdda_boot_valid = 0U;
        UART_SendLiteral("ANALOG VREF: calibration unavailable\r\n");
        return;
    }

    vdda_mv = __HAL_ADC_CALC_VREFANALOG_VOLTAGE(raw,
                                                ADC_RESOLUTION_12B);
    if ((vdda_mv < ANALOG_VDDA_MIN_MV) ||
        (vdda_mv > ANALOG_VDDA_MAX_MV))
    {
        analog_vdda_boot_valid = 0U;
        UART_SendLiteral("ANALOG VREF: VDDA estimate out of range\r\n");
        return;
    }

    analog_vref_boot_raw = raw;
    analog_vdda_boot_mv = (uint16_t)vdda_mv;
    analog_vdda_boot_valid = 1U;
}

/*
 * Regular ADC2 measurements may run while the independent injected channel
 * is armed.  Configure only SQR rank 1 here: HAL permits that when ADSTART
 * is clear even if JADSTART is set.  PC4/PC5 sampling times were configured
 * by ADC_AnalogBootSnapshot() before injected conversion started, because
 * sampling-time registers cannot be changed while JADSTART is active.
 *
 * Never call HAL_ADC_Stop() here: it also stops the injected IV conversion.
 * This is diagnostic only, not a motor-protection input.
 */
static HAL_StatusTypeDef ADC_AnalogLiveReadChannel(uint32_t channel,
                                                    uint16_t *raw)
{
    ADC_ChannelConfTypeDef cfg = {0};

    if ((ADC2->CR & ADC_CR_ADSTART) != 0U)
    {
        return HAL_BUSY;
    }

    cfg.Channel = channel;
    cfg.Rank = ADC_REGULAR_RANK_1;
    cfg.SamplingTime = ANALOG_GPIO_SAMPLE_TIME;
    cfg.SingleDiff = ADC_SINGLE_ENDED;
    cfg.OffsetNumber = ADC_OFFSET_NONE;
    cfg.Offset = 0U;

    if (HAL_ADC_ConfigChannel(&hadc2, &cfg) != HAL_OK)
    {
        return HAL_ERROR;
    }
    if (HAL_ADC_Start(&hadc2) != HAL_OK)
    {
        return HAL_ERROR;
    }
    if (HAL_ADC_PollForConversion(&hadc2, 2U) != HAL_OK)
    {
        /* No Stop: leave injected IV sampling armed for the 20 kHz loop. */
        return HAL_TIMEOUT;
    }

    *raw = (uint16_t)HAL_ADC_GetValue(&hadc2);
    return HAL_OK;
}

static void ADC_AnalogTripleRecord(volatile AnalogTripleDiag_t *diag,
                                   uint16_t first, uint16_t second,
                                   uint16_t third)
{
    uint16_t lo = first;
    uint16_t mid = second;
    uint16_t hi = third;
    uint16_t tmp;

    if (lo > mid) { tmp = lo; lo = mid; mid = tmp; }
    if (mid > hi) { tmp = mid; mid = hi; hi = tmp; }
    if (lo > mid) { tmp = lo; lo = mid; mid = tmp; }

    taskENTER_CRITICAL();
    diag->last_first = first;
    diag->last_second = second;
    diag->last_third = third;
    diag->last_median = mid;
    if ((diag->count == 0U) || (hi > diag->peak_raw_value))
    {
        diag->peak_raw_value = hi;
        diag->peak_raw_first = first;
        diag->peak_raw_second = second;
        diag->peak_raw_third = third;
    }
    if ((diag->count == 0U) || (mid > diag->peak_median_value))
    {
        diag->peak_median_value = mid;
        diag->peak_median_first = first;
        diag->peak_median_second = second;
        diag->peak_median_third = third;
    }
    if ((hi - lo) > diag->max_spread) { diag->max_spread = hi - lo; }
    if ((hi - lo) > ANALOG_TRIPLE_DISAGREE_COUNTS) { diag->disagree_count++; }
    diag->last_tick_ms = HAL_GetTick();
    diag->count++;
    taskEXIT_CRITICAL();
}

static HAL_StatusTypeDef ADC_AnalogLiveSample(void)
{
    uint16_t pc4;
    uint16_t pc4_second = 0U;
    uint16_t pc4_third = 0U;
    uint16_t pc5;
    uint16_t pc5_second = 0U;
    uint16_t pc5_third = 0U;
    uint8_t pair_valid = 0U;
    uint8_t triple_valid = 0U;
    uint8_t pc5_triple_valid = 0U;

    if ((analog_boot_valid == 0U) ||
        (ADC_AnalogLiveReadChannel(ADC_CHANNEL_5, &pc4) != HAL_OK))
    {
        analog_live_valid = 0U;
        analog_live_error_count++;
        return HAL_ERROR;
    }

    /* Repeat PC4 without changing the mux while the gate is safely off.
     * Retain all raw values; the median is only diagnostic and does not
     * replace ANALOG VOLT or feed any motor-protection decision. */
    if (analog_safe_latched != 0U)
    {
        if (ADC_AnalogLiveReadChannel(ADC_CHANNEL_5, &pc4_second) == HAL_OK)
        {
            pair_valid = 1U;
            if (ADC_AnalogLiveReadChannel(ADC_CHANNEL_5, &pc4_third) == HAL_OK)
            {
                triple_valid = 1U;
            }
            else
            {
                taskENTER_CRITICAL();
                analog_triple_diag.errors++;
                taskEXIT_CRITICAL();
            }
        }
        else
        {
            taskENTER_CRITICAL();
            analog_pair_diag.errors++;
            analog_triple_diag.errors++;
            taskEXIT_CRITICAL();
        }
    }

    if (ADC_AnalogLiveReadChannel(ADC_CHANNEL_11, &pc5) != HAL_OK)
    {
        analog_live_valid = 0U;
        analog_live_error_count++;
        if (analog_safe_latched != 0U) { analog_pc5_triple_diag.errors++; }
        return HAL_ERROR;
    }

    /* PC5 is the same-ADC control channel. Extra reads are SAFE-only;
     * keep the original first PC5 sample for ANALOG LIVE/VOLT. */
    if (analog_safe_latched != 0U)
    {
        if ((ADC_AnalogLiveReadChannel(ADC_CHANNEL_11, &pc5_second) == HAL_OK) &&
            (ADC_AnalogLiveReadChannel(ADC_CHANNEL_11, &pc5_third) == HAL_OK))
        {
            pc5_triple_valid = 1U;
        }
        else
        {
            analog_pc5_triple_diag.errors++;
        }
    }

    if (pair_valid != 0U)
    {
        taskENTER_CRITICAL();
        analog_pair_diag.last_first = pc4;
        analog_pair_diag.last_second = pc4_second;
        if ((analog_pair_diag.count == 0U) ||
            (pc4 > analog_pair_diag.peak_first))
        {
            analog_pair_diag.peak_first = pc4;
            analog_pair_diag.peak_first_second = pc4_second;
        }
        if ((analog_pair_diag.count == 0U) ||
            (pc4_second > analog_pair_diag.peak_second))
        {
            analog_pair_diag.peak_second = pc4_second;
            analog_pair_diag.peak_second_first = pc4;
        }
        analog_pair_diag.count++;
        taskEXIT_CRITICAL();
    }

    if (triple_valid != 0U)
    {
        ADC_AnalogTripleRecord(&analog_triple_diag, pc4, pc4_second, pc4_third);
    }
    if (pc5_triple_valid != 0U)
    {
        ADC_AnalogTripleRecord(&analog_pc5_triple_diag, pc5, pc5_second, pc5_third);
    }

    analog_live_pc4_raw = pc4;
    analog_live_pc5_raw = pc5;
    analog_live_last_tick_ms = HAL_GetTick();
    analog_live_sample_count++;
    analog_live_valid = 1U;
    return HAL_OK;
}

static HAL_StatusTypeDef ADC_ConfigIndependentSameTrigger(void)
{
    ADC_MultiModeTypeDef multimode = {0};
    ADC_InjectionConfTypeDef inj = {0};

    /*
     * Use ADC1 and ADC2 independently, but arm both from the SAME
     * TIM1 TRGO2 rising edge.
     *
     * Both ADCs use the same asynchronous SYSCLK/4 ADC clock (42.5 MHz)
     * and the same 12.5-cycle
     * sample time, so IU and IV are sampled concurrently without relying on
     * the ADC dual-mode master/slave state machine.
     */
    if (!FocAdcClock_IsExpected())
        return HAL_ERROR;

    multimode.Mode = ADC_MODE_INDEPENDENT;
    multimode.DMAAccessMode = ADC_DMAACCESSMODE_DISABLED;
    multimode.TwoSamplingDelay = ADC_TWOSAMPLINGDELAY_1CYCLE;

    if (HAL_ADCEx_MultiModeConfigChannel(&hadc1, &multimode) != HAL_OK)
        return HAL_ERROR;

    /* ADC1 injected: IU on PA0 / IN1 */
    inj.InjectedChannel = ADC_CHANNEL_1;
    inj.InjectedRank = ADC_INJECTED_RANK_1;
    inj.InjectedSamplingTime = ADC_SAMPLETIME_12CYCLES_5;
    inj.InjectedSingleDiff = ADC_SINGLE_ENDED;
    inj.InjectedOffsetNumber = ADC_OFFSET_NONE;
    inj.InjectedOffset = 0;
    inj.InjectedNbrOfConversion = 1;
    inj.InjectedDiscontinuousConvMode = DISABLE;
    inj.AutoInjectedConv = DISABLE;
    inj.QueueInjectedContext = DISABLE;
    inj.ExternalTrigInjecConv = ADC_EXTERNALTRIGINJEC_T1_TRGO2;
    inj.ExternalTrigInjecConvEdge = ADC_EXTERNALTRIGINJECCONV_EDGE_RISING;
    inj.InjecOversamplingMode = DISABLE;

    if (HAL_ADCEx_InjectedConfigChannel(&hadc1, &inj) != HAL_OK)
        return HAL_ERROR;

    /* ADC2 injected: IV on PA1 / IN2, same trigger and same sample time */
    inj.InjectedChannel = ADC_CHANNEL_2;
    inj.InjectedRank = ADC_INJECTED_RANK_1;

    if (HAL_ADCEx_InjectedConfigChannel(&hadc2, &inj) != HAL_OK)
        return HAL_ERROR;

    return HAL_OK;
}


static HAL_StatusTypeDef ADC_RunZeroCalibrate(void)
{
    uint16_t static_u = iu_zero_raw;
    uint16_t static_v = iv_zero_raw;

    uint32_t start_tick;
    uint32_t valid;
    uint32_t rejected;
    uint32_t sum_u;
    uint32_t sum_v;

    char msg[320];

    PWM_SetDuty(0.5f, 0.5f, 0.5f);

    UART_SendLiteral(
        "\r\n"
        "PWM-ON TWO-ADC RUN ZERO CALIBRATION\r\n"
        "ADC1=IU, ADC2=IV, same TIM1 TRGO2 trigger\r\n"
        "PWM=20kHz, U/V/W=50%, CTRL_SD=HIGH, MOD=0\r\n"
        "Settling...\r\n");

    HAL_Delay(RUN_ZERO_SETTLE_MS);

    {
        uint32_t primask = __get_PRIMASK();

        __disable_irq();

        run_zero_sum_u = 0U;
        run_zero_sum_v = 0U;
        run_zero_valid_count = 0U;
        run_zero_reject_count = 0U;

        run_zero_cal_done = 0U;
        FocCurrentMedian_Begin(&run_zero_median);
        run_zero_cal_active = 1U;

        if (primask == 0U)
            __enable_irq();
    }

    start_tick = HAL_GetTick();

    while (run_zero_cal_done == 0U)
    {
        if (adc_fault != 0U)
        {
            run_zero_cal_active = 0U;
            return HAL_ERROR;
        }

        if ((HAL_GetTick() - start_tick) > RUN_ZERO_TIMEOUT_MS)
        {
            FaultDiag_Capture(FOC_DIAG_STARTUP,FOC_FAULT_STARTUP_ZERO_CAL,
                FOC_TO_STARTUP_ZERO,HAL_GetTick()-start_tick,RUN_ZERO_TIMEOUT_MS);
            run_zero_cal_active = 0U;
            UART_SendLiteral("TWO ADC RUN ZERO CAL TIMEOUT\r\n");
            return HAL_TIMEOUT;
        }
    }

    valid = run_zero_valid_count;
    rejected = run_zero_reject_count;
    sum_u = run_zero_sum_u;
    sum_v = run_zero_sum_v;

    if (valid == 0U)
        return HAL_ERROR;

    /* Validate candidate offsets before publishing either channel. */
    uint16_t candidate_u = (uint16_t)(sum_u / valid);
    uint16_t candidate_v = (uint16_t)(sum_v / valid);
    if ((candidate_u < 1000U) || (candidate_u > 2200U) ||
        (candidate_v < 1000U) || (candidate_v > 2200U))
    {
        UART_SendLiteral("TWO ADC RUN ZERO CAL INVALID\r\n");
        return HAL_ERROR;
    }
    {
        uint32_t mask = __get_PRIMASK();
        __disable_irq();
        iu_zero_raw = candidate_u;
        iv_zero_raw = candidate_v;
        __DMB();
        __set_PRIMASK(mask);
    }

    UART_SendFormatted(
        msg,
        sizeof(msg),
        "TWO ADC RUN ZERO CAL DONE\r\n"
        "STATIC ZERO : U=%u V=%u\r\n"
        "RUN ZERO    : U=%u V=%u\r\n"
        "SHIFT(count): U=%ld V=%ld\r\n"
        "VALID=%lu REJECTED=%lu\r\n"
        "ZERO FILTER: " FOC_CURRENT_FILTER_NAME "; raw deviation gate unchanged\r\n"
        "IW is reconstructed from -(IU+IV)\r\n"
        "========================================\r\n",
        static_u,
        static_v,
        iu_zero_raw,
        iv_zero_raw,
        (long)((int32_t)iu_zero_raw - (int32_t)static_u),
        (long)((int32_t)iv_zero_raw - (int32_t)static_v),
        (unsigned long)valid,
        (unsigned long)rejected);

    /*
     * Seed the published frame with zero-current values. iw_zero_raw is only
     * used as a numerical center for the reconstructed pseudo-raw W value.
     */
    {
        uint32_t primask = __get_PRIMASK();

        __disable_irq();

        iu_inj_raw = iu_zero_raw;
        iv_inj_raw = iv_zero_raw;
        iw_inj_raw = iw_zero_raw;

        current_valid_count = 0U;
        current_reject_count = 0U;
        current_reject_streak = 0U;
        current_last_rejected_sum_counts = 0;

        current_prev_raw_u = iu_zero_raw;
        current_prev_raw_v = iv_zero_raw;
        current_prev_raw_valid = 0U;

        current_med_u[0] = iu_zero_raw;
        current_med_u[1] = iu_zero_raw;
        current_med_u[2] = iu_zero_raw;
        current_med_v[0] = iv_zero_raw;
        current_med_v[1] = iv_zero_raw;
        current_med_v[2] = iv_zero_raw;
        current_med_index = 0U;
        current_med_count = 0U;
#if defined(FOC_CURRENT_SPIKE_ONLY)
        FocCurrentMedian_Begin(&current_spike_filter);
#endif

        current_filter_enable = 1U;

        if (primask == 0U)
            __enable_irq();
    }

    UART_SendLiteral(
        "Two-ADC step filter ON: |dIU| or |dIV| > about 0.40A => hold last valid frame\r\n");

    return HAL_OK;
}


