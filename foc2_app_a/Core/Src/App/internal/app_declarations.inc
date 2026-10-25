/* App A internal/app_declarations.inc: private binding, included once by main.c.
 * Keep the declared include order and original control/IRQ ownership. */
/* Private function prototypes -----------------------------------------------*/
#include "../board/app_board.h"
/* USER CODE BEGIN PFP */

extern void PW_SmokeTest(void);
extern void PW_ThreadSmokeStart(void);
extern void PW_UnitTestsRun(void);
extern void PW_Rpc_Init(void);
extern void PW_Rpc_HandleCommand(uint32_t request_id, const char *args);
#if defined(ROUTER_READ_ONLY_RPC)
#include "pw_router_rpc.h"
#endif
#if defined(ROUTER_READ_ONLY_TRANSFER)
#include "pw_router_transfer.h"
#endif
extern void PW_Transfer_HandleCommand(uint32_t request_id, const char *args);

/* RTOS task dependencies / forward declarations. */
static HAL_StatusTypeDef AS5047P_ReadAngle(uint16_t *raw);
static void EncoderDiag_InitCycleCounter(void);
static float Encoder_ElectricalAngleRad(uint16_t raw);
static HAL_StatusTypeDef FOC_EncoderSpeedUpdate(float dt_s);
static void PowerStage_Disable(void);
static void PowerStage_Enable(void);
#if defined(AS5047P_SPI_DMA)
/* IRQ priority 3: fixed writes only, no UART/HAL waits/FreeRTOS calls. */
static void EncoderDma_FaultFromISR(void)
{
    if (encoder_timeout_reason==FOC_TO_NONE) {
        uint32_t status=AS5047P_DmaFaultStatus();
        if (status==AS_DMA_TIMEOUT) encoder_timeout_reason=FOC_TO_ENCODER_TRANSACTION;
        else if (status==AS_DMA_CONTROL_STALE) encoder_timeout_reason=FOC_TO_ENCODER_CONTROL;
        else if (status==AS_DMA_SCHEDULE) encoder_timeout_reason=FOC_TO_ENCODER_SCHEDULE;
    }
#if defined(FOC_PROTECTED_CLOSED_LOOP)
    ProtectedLoop_EmergencyOff(CL_BAD_ENCODER);
#endif
#if defined(FOC_FEEDBACK_SAFETY_BINDING)
    FocFeedbackBinding_EmergencyOff(FOC_FB_ENCODER_INVALID);
#endif
    TIM1->BDTR &= ~TIM_BDTR_MOE;
    DRIVER_SD_GPIO_Port->BSRR = (uint32_t)DRIVER_SD_Pin << 16U;
    FaultDiag_Capture(FOC_DIAG_MOTOR,2U,encoder_timeout_reason,
        tightening_test_elapsed_ms,0U);
    foc_enable = 0U;
    encoder_valid = 0U;
    foc_iq_ref_A = 0.0f;
    if (foc_fault == 0U) foc_fault_reason = 2U;
    foc_fault = 1U;
    __DSB();
}
#endif
static void PWM_SetDuty(float du, float dv, float dw);
static void PWM_StopAll(void);
static float ClampFloat(float x, float lo, float hi);
static void FormatSignedX100(char *buf, size_t n, int32_t x100);
static void MotorControlTask(void *argument);
static void TighteningTask(void *argument);
static void RouterTask(void *argument);
static void SafeCommTask(void *argument);
static uint8_t SafeCommBootRequested(void);
static void ProtocolTask(void *argument);
static void ModbusTask(void *argument);

static uint8_t Modbus_Enqueue(const ModbusJob_t *job);
static void Modbus_ServiceCompletions(uint32_t budget);
static void MonitorTask(void *argument);
static void BootHealthTask(void *argument);
static HAL_StatusTypeDef ADC_AnalogLiveSample(void);
static uint8_t Tightening_IsBusy(void);
static const char *TighteningOutcome_Name(TighteningOutcome_t outcome);
static uint8_t Router_Uart1Tx(const RouterPacket_t *packet);
static void Protocol_HandleLine(char *line);
#if defined(ZERO_RETEST_BOOT)
static uint8_t ZeroRetest_HandleCommand(uint32_t request_id, const char *cmd);
static void ZeroRetest_InjectedPair(void);
#endif
#if defined(SWITCH_FEEDBACK_DIAGNOSTIC)
void SwitchFeedback_EmergencyOff(uint32_t reason);
#endif
static uint8_t UART_SendReliableString(const char *str);
static uint8_t Protocol_SendString(const char *str);
static uint8_t Protocol_SendFormatted(char *fallback, size_t capacity,
    const char *format, ...) __attribute__((format(printf, 3, 4)));
static uint8_t UART_SendReliableFormatted(char *fallback, size_t capacity,
    const char *format, ...) __attribute__((format(printf, 3, 4)));
static void Protocol_SetReplyRoute(uint16_t dst_node);
static void Protocol_ClearReplyRoute(void);
static uint8_t Protocol_AsyncEventEnqueue(uint8_t routed, uint16_t dst_node, const char *payload);
static void Protocol_AsyncEventService(uint32_t budget);
static uint8_t Protocol_ReliableEventTransmit(ProtocolReliableEvent_t *slot, uint8_t is_retry);
static uint8_t Protocol_ReliableEventStart(uint16_t dst_node, const char *payload);
static void Protocol_ReliableEventService(uint32_t budget);
static uint8_t Protocol_ReliableEventAck(uint16_t src_node, uint32_t eid);
static uint32_t Protocol_ReliableEventPendingCount(void);
static uint8_t Protocol_ReliableEventParseEid(const char *text, const char *prefix, uint32_t *eid_out);
static uint8_t Protocol_ReliableEventRxSeen(uint16_t src_node, uint32_t eid);
static void Protocol_ReliableEventHandleEventPacket(const RouterPacket_t *packet);
static void Protocol_ReliableEventHandleAckPacket(const RouterPacket_t *packet);
static void Protocol_SendDeferredStartError(uint8_t routed, uint16_t dst_node, uint32_t request_id, const char *name);
static void Protocol_PrintStatus(uint32_t request_id);
static void TightenParams_RestoreDefaults(void);
static uint32_t TightenParams_Crc32(const uint8_t *data, size_t length);
static TightenParamsFlashLoadStatus_t TightenParams_LoadFromFlash(void);
static uint8_t TightenParams_SaveToFlash(void);
static uint8_t BootMeta_ReadV1(BootMetaV1_t *out);
static uint8_t BootMeta_ReadV2Legacy(BootMetaV2_t *out);
static uint8_t BootMeta_ReadV3At(uint32_t address, BootMetaV3_t *out);
static uint8_t BootMeta_ReadV3(BootMetaV3_t *out);
static uint8_t BootMeta_SaveV3(const BootMetaV3_t *meta);
static uint8_t BootMeta_EnsureV3(BootMetaV3_t *out);

static uint8_t BootMailbox_WriteRequest(uint32_t command,
                                        uint32_t target_slot,
                                        uint32_t image_size,
                                        uint32_t image_crc32);
static uint8_t BootMailbox_RequestConfirmCurrent(void);
static uint8_t BootMailbox_RequestStartTrial(uint32_t target_slot,
                                             uint32_t image_size,
                                             uint32_t image_crc32);
static uint8_t BootMailbox_RequestSetConfirmedSlot(uint32_t target_slot);

static uint8_t BootHealth_IsCurrentTrial(void);
static uint8_t BootMeta_ConfirmCurrent(void);
static uint8_t BootMeta_SaveSlot(uint32_t slot);

static uint8_t Fw_HexNibble(char c, uint8_t *value);
static uint8_t Fw_ParseHexBytes(const char *text,
                                uint8_t *out,
                                uint32_t *out_len);
static uint8_t Fw_TargetVectorValid(void);
static uint8_t Fw_EraseTarget(uint32_t image_size);
static uint8_t Fw_ProgramData(uint32_t offset,
                              const uint8_t *data,
                              uint32_t length);
static uint32_t Fw_TargetCrc32(uint32_t image_size);
static void Fw_EnterSafeState(void);
static void Fw_ResetContext(void);
static void Fw_DiagSnapshotComms(void);
static void Fw_SendStatus(uint32_t request_id);
static void TighteningResult_Reset(TighteningStageResult_t *r,
                                   float command_A);
static void TighteningResult_Sample(TighteningStageResult_t *r);
static void TighteningResult_PrintStage(const char *name,
                                        const TighteningStageResult_t *r);
static void TighteningResult_PrintSummary(const char *result_text);
static float TighteningResult_AvgIq(
    const TighteningStageResult_t *r);
static void TighteningRepeat_ResetCurrentCycle(void);
static void TighteningRepeat_StoreCurrentCycle(void);
static void TighteningRepeat_PrintAggregate(void);

static void MotorControl_SetIdle(void);
static void MotorControl_SetSpeed(float rpm);
static void MotorControl_SetPosition(float position_deg, uint8_t active_hold);
static void MotorControl_SetIq(float iq_A);
static const char *MotorControl_ModeName(MotorControlMode_t mode);

/* USER CODE END PFP */

