/* App A sensing/encoder_service.inc: private binding, included once by main.c.
 * Keep the declared include order and original control/IRQ ownership. */
/*
 * AS5047P SPI command helpers.
 *
 * Command frame:
 *   bit15    = even parity over bits 14..0
 *   bit14    = R/W (1 = read)
 *   bits13:0 = register address
 *
 * Important correction:
 *   A READ of NOP (0x0000) is NOT the raw frame 0x0000.
 *   The correct read-NOP frame is 0xC000 after adding R/W + parity.
 */
#define AS5047P_REG_NOP       0x0000U
#define AS5047P_REG_ERRFL     0x0001U
#define AS5047P_REG_ANGLECOM  0x3FFFU

#define AS5047P_ERRFL_FRERR    (1U << 0)
#define AS5047P_ERRFL_INVCOMM  (1U << 1)
#define AS5047P_ERRFL_PARERR   (1U << 2)

/*
 * The datasheet requires >=350 ns from CSn falling edge to the first clock,
 * and >=350 ns CSn high time between frames.
 *
 * At 170 MHz, 128 explicit NOPs are comfortably longer than 350 ns.
 * The loop overhead only makes this more conservative.
 */
#define AS5047P_CS_GUARD_NOPS  128U

static volatile uint8_t as5047p_diag_verbose = 0U;
static volatile uint16_t as5047p_last_errfl = 0U;


static void AS5047P_CsGuardDelay(void)
{
    for (uint32_t i = 0U; i < AS5047P_CS_GUARD_NOPS; i++)
    {
        __NOP();
    }
}



static HAL_StatusTypeDef AS5047P_Transfer16(uint16_t tx, uint16_t *rx)
{
    HAL_StatusTypeDef st;
    uint16_t r = 0U;

    HAL_GPIO_WritePin(AS5047_CS_GPIO_Port,
                      AS5047_CS_Pin,
                      GPIO_PIN_RESET);

    AS5047P_CsGuardDelay();

    st = HAL_SPI_TransmitReceive(&hspi1,
                                 (uint8_t *)&tx,
                                 (uint8_t *)&r,
                                 1U,
                                 10U);

    /*
     * Keep CS low long enough after the last clock before releasing it.
     * This delay is intentionally conservative.
     */
    AS5047P_CsGuardDelay();

    HAL_GPIO_WritePin(AS5047_CS_GPIO_Port,
                      AS5047_CS_Pin,
                      GPIO_PIN_SET);

    /*
     * Guarantee the inter-frame CS-high time before another transaction.
     */
    AS5047P_CsGuardDelay();

    if (rx != NULL)
    {
        *rx = r;
    }

    return st;
}


/*
 * Generic two-frame AS5047P register read.
 *
 * Frame 1: READ requested register.
 * Frame 2: READ NOP; MISO returns data requested by frame 1.
 *
 * The second command is the properly formed READ-NOP command (0xC000),
 * not the old raw 0x0000 frame.
 */
static int AS5047P_TransferAdapter(void *context, uint16_t tx,
                                    uint16_t *rx)
{
    (void)context;
    return (int)AS5047P_Transfer16(tx, rx);
}

/* The two-frame sequence is shared with the host fake-device tests. */
static HAL_StatusTypeDef AS5047P_ReadRegisterFrame(uint16_t reg,
                                                   uint16_t *response)
{
#if defined(AS5047P_SPI_DMA)
    return AS5047P_DmaReadOne(reg, response) == AS_DMA_OK ? HAL_OK : HAL_ERROR;
#else
    AS5047P_TransactionTrace_t trace = {0};
    int status = AS5047P_ReadRegisterVia(AS5047P_TransferAdapter, NULL,
                                          reg, response, &trace);
    if ((status != 0) && (as5047p_diag_verbose != 0U))
    {
        char msg[180];
        UART_SendFormatted(msg, sizeof(msg),
                 "ENC FAIL: REG=0x%04X PHASE=%u STAGE=%u HAL=%d "
                 "SPI_ERR=0x%08lX RX=0x%04X\r\n",
                 (unsigned int)trace.reg, (unsigned int)trace.phase,
                 (unsigned int)trace.failure, status,
                 (unsigned long)HAL_SPI_GetError(&hspi1),
                 (unsigned int)trace.response);
    }
    return (HAL_StatusTypeDef)status;
#endif
}
static HAL_StatusTypeDef AS5047P_ReadAndClearErrorFlags(uint16_t *flags)
{
    HAL_StatusTypeDef st;
    uint16_t rsp = 0U;
    uint16_t f;

    st = AS5047P_ReadRegisterFrame(AS5047P_REG_ERRFL, &rsp);

    if (st != HAL_OK)
    {
        return st;
    }

    f = AS5047P_ErrorFlags(rsp);
    as5047p_last_errfl = f;

    if (flags != NULL)
    {
        *flags = f;
    }

    if (as5047p_diag_verbose != 0U)
    {
        char msg[220];

        UART_SendFormatted(msg,
                 sizeof(msg),
                 "ENC ERRFL: RAW=0x%04X FLAGS=0x%X "
                 "PARERR=%u INVCOMM=%u FRERR=%u EF=%u\r\n",
                 (unsigned int)rsp,
                 (unsigned int)f,
                 (unsigned int)((f & AS5047P_ERRFL_PARERR) != 0U),
                 (unsigned int)((f & AS5047P_ERRFL_INVCOMM) != 0U),
                 (unsigned int)((f & AS5047P_ERRFL_FRERR) != 0U),
                 (unsigned int)((rsp & 0x4000U) != 0U));
    }

    return HAL_OK;
}


static HAL_StatusTypeDef AS5047P_ReadAngle(uint16_t *raw)
{
#if defined(AS5047P_SPI_DMA)
    uint16_t response = 0U;
    AsDmaStatus status = AS5047P_DmaReadOne(0x3FFFU, &response);
    if (status == AS_DMA_OK && raw != NULL) *raw = response & 0x3FFFU;
    return status == AS_DMA_OK ? HAL_OK : HAL_ERROR;
#else
    AS5047P_TransactionTrace_t trace = {0};
    uint32_t start_cycles = DWT->CYCCNT;
    int status = AS5047P_ReadAngleVia(AS5047P_TransferAdapter, NULL,
                                       raw, &trace);
    if (encoder_diag_dwt_ready != 0U)
    {
        uint32_t elapsed_cycles = DWT->CYCCNT - start_cycles;
        encoder_diag_last_cycles = elapsed_cycles;
        if (elapsed_cycles > encoder_diag_max_cycles)
        {
            encoder_diag_max_cycles = elapsed_cycles;
        }
        if (elapsed_cycles >= (SystemCoreClock / 1000U))
        {
            encoder_diag_over_1ms++;
        }
        encoder_diag_reads++;
        if (status != 0) { encoder_diag_failures++; }
    }
    if (trace.errfl_valid != 0U)
    {
        as5047p_last_errfl = trace.errfl;
    }
    if (as5047p_diag_verbose != 0U)
    {
        char msg[200];
        if (status != 0)
        {
            UART_SendFormatted(msg, sizeof(msg),
                     "ENC FAIL: PHASE=%u STAGE=%u HAL=%d "
                     "REG=0x%04X RX=0x%04X ERRFL=0x%X\r\n",
                     (unsigned int)trace.phase,
                     (unsigned int)trace.failure, status,
                     (unsigned int)trace.reg,
                     (unsigned int)trace.response,
                     (unsigned int)trace.errfl);
        }
        else if (trace.recovered != 0U)
        {
            UART_SendFormatted(msg, sizeof(msg),
                     "ENC RECOVERED: ERRFL=0x%X ANGLE_RX=0x%04X\r\n",
                     (unsigned int)trace.errfl,
                     (unsigned int)trace.response);
        }
    }
    return (HAL_StatusTypeDef)status;
#endif
}

static void EncoderDiag_InitCycleCounter(void)
{
    uint32_t before;

    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CYCCNT = 0U;
    DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
    before = DWT->CYCCNT;
    __NOP(); __NOP(); __NOP(); __NOP();
    encoder_diag_dwt_ready =
        (uint8_t)(((DWT->CTRL & DWT_CTRL_CYCCNTENA_Msk) != 0U) &&
                  (DWT->CYCCNT != before));
}

static float Encoder_ElectricalAngleRad(uint16_t raw)
{
#if defined(FOC_TORQUE_CHAIN_DIAG) && !defined(FOC_SPEED_DYNAMIC_DIAG) && !defined(FOC_TORQUE350_FIVE_SECOND) && !defined(FOC_TORQUE450_FIVE_SECOND) && !defined(FOC_ANGLE_HAND_ONLY)
    return FocTorqueChain_Angle(AS5047P_ElectricalAngleRad(raw,
        ELECTRICAL_ZERO_RAW,POLE_PAIRS,ENCODER_DIRECTION),torque_diag.offset_deg);
#else
    return AS5047P_ElectricalAngleRad(raw, ELECTRICAL_ZERO_RAW,
                                     POLE_PAIRS, ENCODER_DIRECTION);
#endif
}

static HAL_StatusTypeDef AS5047P_StartupCheck(void)
{
    uint32_t ok = 0U;
    uint16_t raw = 0U;
    uint16_t startup_errfl = 0U;
    char msg[220];

    HAL_GPIO_WritePin(AS5047_CS_GPIO_Port,
                      AS5047_CS_Pin,
                      GPIO_PIN_SET);

    HAL_Delay(5U);

    /*
     * Startup-only verbose diagnostics.
     *
     * First read ERRFL once. This both tells us whether a stale communication
     * error was latched and clears the ERRFL register before the 20-read test.
     */
    as5047p_diag_verbose = 1U;

    if (AS5047P_ReadAndClearErrorFlags(&startup_errfl) == HAL_OK)
    {
        UART_SendFormatted(msg,
                 sizeof(msg),
                 "AS5047P PRE-CLEAR ERRFL=0x%X "
                 "PARERR=%u INVCOMM=%u FRERR=%u\r\n",
                 (unsigned int)startup_errfl,
                 (unsigned int)((startup_errfl &
                                 AS5047P_ERRFL_PARERR) != 0U),
                 (unsigned int)((startup_errfl &
                                 AS5047P_ERRFL_INVCOMM) != 0U),
                 (unsigned int)((startup_errfl &
                                 AS5047P_ERRFL_FRERR) != 0U));
    }
    else
    {
        UART_SendLiteral(
            "AS5047P PRE-CLEAR ERRFL read failed\r\n");
    }

    HAL_Delay(1U);

    /*
     * Perform 20 corrected ANGLECOM reads.
     *
     * Each read now uses:
     *   frame 1 = READ ANGLECOM = 0xFFFF
     *   frame 2 = READ NOP      = 0xC000
     */
    for (uint32_t i = 0U; i < 20U; i++)
    {
        if (AS5047P_ReadAngle(&raw) == HAL_OK)
        {
            ok++;
            encoder_raw = raw;
            encoder_theta_e = Encoder_ElectricalAngleRad(raw);
            encoder_valid = 1U;
        }
        else
        {
            encoder_error_count++;
        }

        HAL_Delay(1U);
    }

    as5047p_diag_verbose = 0U;

    UART_SendFormatted(msg,
             sizeof(msg),
             "AS5047P startup: OK=%lu/20 RAW=%u ELEC=%ludeg "
             "ERR=%lu LAST_ERRFL=0x%X\r\n",
             (unsigned long)ok,
             (unsigned int)encoder_raw,
             (unsigned long)(encoder_theta_e * 180.0f / PI_F),
             (unsigned long)encoder_error_count,
             (unsigned int)as5047p_last_errfl);

    return (ok >= 15U) ? HAL_OK : HAL_ERROR;
}


