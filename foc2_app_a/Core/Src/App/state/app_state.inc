/* App A state/app_state.inc: private binding, included once by main.c.
 * Keep the declared include order and original control/IRQ ownership. */
/* Private variables ---------------------------------------------------------*/
ADC_HandleTypeDef hadc1;
ADC_HandleTypeDef hadc2;

UART_HandleTypeDef hlpuart1;

SPI_HandleTypeDef hspi1;

TIM_HandleTypeDef htim1;

/* USER CODE BEGIN PV */

/*
 * Temporary FreeRTOS bring-up flag.
 * SysTick forwards ticks to the kernel only after the first task starts.
 */
volatile uint8_t g_rtos_started = 0U;

static uint16_t iu_zero_raw = 0U;
static uint16_t iv_zero_raw = 0U;
static uint16_t iw_zero_raw = 0U;

/* One-shot analog wiring diagnostic, sampled before injected FOC starts. */
static volatile uint16_t analog_boot_pc4_raw = 0U;
static volatile uint16_t analog_boot_pc5_raw = 0U;
static volatile uint8_t analog_boot_valid = 0U;

/* Factory-VREFINT-based VDDA estimate, taken before ADC1 injected FOC starts. */
static volatile uint16_t analog_vref_boot_raw = 0U;
static volatile uint16_t analog_vdda_boot_mv = 0U;
static volatile uint8_t analog_vdda_boot_valid = 0U;

/* IDLE-only, low-rate regular ADC2 diagnostic while injected FOC is armed. */
static volatile uint16_t analog_live_pc4_raw = 0U;
static volatile uint16_t analog_live_pc5_raw = 0U;
static volatile uint32_t analog_live_last_tick_ms = 0U;
static volatile uint32_t analog_live_sample_count = 0U;
static volatile uint32_t analog_live_error_count = 0U;
static volatile uint8_t analog_live_valid = 0U;
/* Raw PC4 conversions before/after a same-channel repeat, SAFE mode only. */
typedef struct
{
    uint16_t last_first;
    uint16_t last_second;
    uint16_t peak_first;
    uint16_t peak_first_second;
    uint16_t peak_second;
    uint16_t peak_second_first;
    uint32_t count;
    uint32_t errors;
} AnalogPairDiag_t;
static volatile AnalogPairDiag_t analog_pair_diag;
/* Three consecutive PC4 conversions; median is experimental, not protection. */
typedef struct
{
    uint16_t last_first;
    uint16_t last_second;
    uint16_t last_third;
    uint16_t last_median;
    uint16_t peak_raw_value;
    uint16_t peak_raw_first;
    uint16_t peak_raw_second;
    uint16_t peak_raw_third;
    uint16_t peak_median_value;
    uint16_t peak_median_first;
    uint16_t peak_median_second;
    uint16_t peak_median_third;
    uint16_t max_spread;
    uint32_t count;
    uint32_t errors;
    uint32_t disagree_count;
    uint32_t last_tick_ms;
} AnalogTripleDiag_t;
static volatile AnalogTripleDiag_t analog_triple_diag;
static volatile AnalogTripleDiag_t analog_pc5_triple_diag;
/* One-way, voltage-diagnostics-only shutdown until the next MCU reset. */
static volatile uint8_t analog_safe_latched = 0U;

static volatile uint16_t iu_inj_raw = 0U;
static volatile uint16_t iv_inj_raw = 0U;
static volatile uint16_t iw_inj_raw = 0U;
static volatile uint32_t injected_seq_count = 0U;
static volatile uint8_t adc_fault = 0U;

/* PWM-ON dynamic zero calibration state */
static volatile uint8_t run_zero_cal_active = 0U;
static volatile uint8_t run_zero_cal_done = 0U;
static FocCurrentMedian run_zero_median; /* Sole writer: ADC1 ISR while active. */

static volatile uint32_t run_zero_sum_u = 0U;
static volatile uint32_t run_zero_sum_v = 0U;
static volatile uint32_t run_zero_sum_w = 0U;

static volatile uint32_t run_zero_valid_count = 0U;
static volatile uint32_t run_zero_reject_count = 0U;

/* Runtime current-frame filter statistics/state */
static volatile uint8_t current_filter_enable = 0U;
static volatile uint32_t current_valid_count = 0U;
static volatile uint32_t current_reject_count = 0U;
static volatile uint32_t current_reject_streak = 0U;
static volatile int32_t current_last_rejected_sum_counts = 0;

/*
 * Previous PHYSICAL ADC sample, used only for one-sample jump detection.
 * Important: this is updated even when a frame is rejected, otherwise one
 * rejected sample can make the filter compare forever against stale data.
 */
static volatile uint16_t current_prev_raw_u = 0U;
static volatile uint16_t current_prev_raw_v = 0U;
static volatile uint8_t current_prev_raw_valid = 0U;

/*
 * 3-sample median post-filter.
 *
 * The proven raw-to-raw step reject remains the FIRST gate.  We do not use
 * a stale "last accepted" sample as a hard gate, because that can latch the
 * filter after one disturbance.  Median-of-3 only cleans the frames that
 * already passed the step gate.
 */
static uint16_t current_med_u[3] = {0U, 0U, 0U};
static uint16_t current_med_v[3] = {0U, 0U, 0U};
static uint8_t current_med_index = 0U;
static uint8_t current_med_count = 0U;
#if defined(FOC_CURRENT_SPIKE_ONLY)
static FocCurrentMedian current_spike_filter;
#if defined(FOC_CURRENT_TREND4)
static FocTrend4Angle current_trend4_angle;
#endif
#endif

/* Encoder / position / speed-estimator state. */
static volatile uint16_t encoder_raw = 0U;
#if defined(FOC_RUNDOWN_DIAGNOSTIC)
static int32_t rundown_encoder_delta;
static uint32_t rundown_encoder_dt_us;
#endif
static volatile float encoder_theta_e = 0.0f;       /* latest measured electrical angle */
static volatile float encoder_theta_e_pred = 0.0f;  /* 20 kHz predicted electrical angle */
static volatile float encoder_speed_rpm = 0.0f;     /* mechanical speed; +RAW = positive */
static volatile float encoder_omega_e_rad_s = 0.0f;
static volatile uint8_t encoder_valid = 0U;
static volatile uint32_t encoder_error_count = 0U;
static uint16_t encoder_prev_raw = 0U;
static uint8_t encoder_prev_valid = 0U;
static float encoder_speed_dt_accum_s = 0.0f;
static volatile uint32_t encoder_speed_glitch_count = 0U;
static volatile uint32_t encoder_speed_glitch_streak = 0U;

/* 1 ms instantaneous speed diagnostic. */
static volatile float encoder_rpm_instant = 0.0f;

/*
 * 50 ms average speed for future seating/load detection.
 * This is deliberately independent of the Speed PI feedback path.
 */
static volatile float encoder_speed_detect_rpm = 0.0f;
static int32_t encoder_speed_detect_counts = 0;
static float encoder_speed_detect_dt_s = 0.0f;
static uint32_t encoder_speed_detect_samples = 0U;

/*
 * Unwrapped mechanical position, relative to the rotor position at FOC enable.
 * Positive position uses the same verified sign convention as positive speed:
 * ENCODER_DIRECTION=-1 means decreasing AS5047P RAW is positive motion.
 */
static volatile float encoder_position_deg = 0.0f;

/* Position outer-loop state. */
static volatile float position_target_deg = 0.0f;
static volatile float position_error_deg = 0.0f;
static volatile float position_speed_cmd_rpm = 0.0f;

/*
 * Position deadband hysteresis state.
 *
 * 1: currently considered settled/in deadband
 * 0: position loop is active
 */
static volatile uint8_t position_deadband_active = 1U;

/*
 * Final-stage hybrid active-hold state.
 *
 * STG0..STG4: active_hold_enable = 0 -> normal position/speed/current cascade.
 * STG5:
 *   active_hold_enable = 1 inside the <=2 deg hold region;
 *   active_hold_enable = 0 outside the >=3 deg exit boundary.
 *
 * Between 2 and 3 deg the current mode is retained (hysteresis).
 */
static volatile uint8_t active_hold_enable = 0U;
static volatile float active_hold_iq_cmd_A = 0.0f;

/*
 * Position-sequence stage must be file-scope because FOC_EncoderSpeedUpdate()
 * uses it to select the gentler STG5 cascade return limits.
 */

/*
 * Generic command mailbox.
 *
 * TighteningTask is the application-layer writer.
 * MotorControlTask / FOC_EncoderSpeedUpdate are the control-layer readers.
 *
 * 32-bit aligned enum/float accesses are atomic on Cortex-M4; the command
 * value is written before the mode so the mode acts as the commit point.
 */
static volatile MotorControlMode_t motor_control_mode = MOTOR_MODE_IDLE;
static volatile float motor_position_command_deg = 0.0f;
static volatile float motor_speed_command_rpm = 0.0f;
static volatile float motor_iq_command_A = 0.0f;
static volatile uint8_t motor_position_active_hold = 0U;

static volatile TighteningTestStage_t tightening_test_stage =
    TIGHTEN_STATE_IDLE_DELAY;
static volatile uint32_t tightening_test_elapsed_ms = 0U;

/* Tightening/contact-detection diagnostics. */
static volatile uint32_t tightening_contact_candidate_ms = 0U;
static volatile uint8_t tightening_contact_condition = 0U;
static volatile float tightening_start_position_deg = 0.0f;
static volatile float tightening_travel_deg = 0.0f;
static volatile float tightening_contact_position_deg = 0.0f;
static volatile float tightening_post_contact_travel_deg = 0.0f;
static volatile float tightening_drive_iqref_A = 0.0f;

/*
 * Set only after the 250 ms contact criterion is truly confirmed.
 * This prevents STOPPED/RUNDOWN_TIMEOUT results from printing a fake
 * "Contact angle".
 */
static volatile uint8_t tightening_contact_confirmed = 0U;


/*
 * PARAMETER SYSTEM V1
 *
 * Tightening recipe values are now runtime parameters stored in RAM.
 * This stage intentionally does NOT write Flash.
 *
 * Reset/power-cycle => safe defaults below.
 * SET is rejected while a tightening cycle is active.
 *
 * Integer units keep the ASCII protocol simple:
 *   speed   : rpm
 *   current : mA
 *   time    : ms
 *   travel  : mechanical deg
 */
/* C ABI recipe layout shared by both slots; implementation is C++17. */

#define PARAM_FLASH_ADDRESS       (0x0807F800UL)

#define APP_A_ADDRESS          (0x08008000UL)
#define APP_A_END              (0x08040000UL)
#define APP_B_ADDRESS          (0x08040000UL)
#define APP_B_END              (0x08078000UL)

/*
 * Metadata V3: two independent erase pages.
 *
 * Copy1 / Page125 : 0x0807E800..0x0807EFFF
 * Copy0 / Page126 : 0x0807F000..0x0807F7FF
 * Parameters      : 0x0807F800..0x0807FFFF (unchanged)
 *
 * Copy0 deliberately keeps the historical V1/V2 address for staged
 * migration compatibility.
 */
#define BOOT_META_COPY0_ADDRESS (0x0807F000UL)
#define BOOT_META_COPY0_PAGE    (126U)
#define BOOT_META_COPY1_ADDRESS (0x0807E800UL)
#define BOOT_META_COPY1_PAGE    (125U)
#define BOOT_META_BANK          FLASH_BANK_2

#define BOOT_META_ADDRESS       BOOT_META_COPY0_ADDRESS

#define BOOT_META_MAGIC         (0x424F4F54UL)  /* "BOOT" */
#define BOOT_META_VERSION_V1    (1UL)
#define BOOT_META_VERSION_V2    (2UL)
#define BOOT_META_VERSION_V3    (3UL)

#define BOOT_SLOT_NONE         (0UL)
#define BOOT_SLOT_A            (1UL)
#define BOOT_SLOT_B            (2UL)

#define APP_THIS_SLOT          (BOOT_SLOT_A)
#define APP_THIS_ADDRESS       (APP_A_ADDRESS)
#define APP_TARGET_SLOT        (BOOT_SLOT_B)
#define APP_TARGET_ADDRESS     (APP_B_ADDRESS)
#define APP_TARGET_END         (APP_B_END)
#define APP_TARGET_BANK        FLASH_BANK_2
#define APP_TARGET_FIRST_PAGE  (0U)

#define FW_FLASH_PAGE_SIZE     (0x800UL)
#define FW_SLOT_SIZE           (0x38000UL)
#define FW_DATA_MAX_BYTES      (32U)
#define FW_TRIAL_ATTEMPTS      (2UL)

/*
 * Reserved SRAM mailbox. Linker RAM LENGTH must end at 0x2001FFC0 so the
 * startup stack/.bss never overwrite 0x2001FFC0..0x2001FFFF.
 */
#define BOOT_MAILBOX_ADDRESS        (0x2001FFC0UL)
#define BOOT_MAILBOX_RESERVED_BYTES (64UL)
#define BOOT_MAILBOX_MAGIC          (0x584F424DUL) /* "MBOX" */
#define BOOT_MAILBOX_VERSION        (1UL)

#define BOOT_MAILBOX_CMD_NONE               (0UL)
#define BOOT_MAILBOX_CMD_CONFIRM_CURRENT    (1UL)
#define BOOT_MAILBOX_CMD_START_TRIAL        (2UL)
#define BOOT_MAILBOX_CMD_SET_CONFIRMED_SLOT (3UL)

/*
 * Automatic trial-firmware health gate.
 *
 * A newly downloaded slot is NOT confirmed immediately. It must first keep
 * the core control/communication chain healthy for a continuous 5-second
 * window. If that never happens, the APP deliberately resets so Bootloader
 * V2 can consume the remaining trial attempt and eventually roll back.
 */
#define BOOT_HEALTH_CHECK_MS              (500U)
#define BOOT_HEALTH_STABLE_REQUIRED_MS    (5000U)
#define BOOT_HEALTH_FAIL_RESET_MS         (12000U)
#define BOOT_HEALTH_MIN_ADC_DELTA          (9000U)
#define BOOT_HEALTH_MIN_FOC_DELTA          (9000U)

#define BOOT_HEALTH_FAIL_FORCED            (1UL << 0)
#define BOOT_HEALTH_FAIL_ADC_FAULT         (1UL << 1)
#define BOOT_HEALTH_FAIL_FOC_FAULT         (1UL << 2)
#define BOOT_HEALTH_FAIL_ENCODER           (1UL << 3)
#define BOOT_HEALTH_FAIL_FOC_DISABLED      (1UL << 4)
#define BOOT_HEALTH_FAIL_UART              (1UL << 5)
#define BOOT_HEALTH_FAIL_ADC_RATE          (1UL << 6)
#define BOOT_HEALTH_FAIL_FOC_RATE          (1UL << 7)
#define BOOT_HEALTH_FAIL_FW_ACTIVE         (1UL << 8)
#define BOOT_HEALTH_FAIL_TIGHTENING        (1UL << 9)
#define BOOT_HEALTH_FAIL_MOTOR_MODE        (1UL << 10)
#define BOOT_HEALTH_FAIL_SPEED             (1UL << 11)

/*
 * Lab-only fault injection.
 * 0 = normal automatic confirmation.
 * 1 = deliberately fail every health sample so rollback can be tested.
 *
 * Keep this 0 in the normal APP A/B builds.
 */
/* Acceptance-only fault injection; normal images must leave this at zero. */
#ifndef BOOT_HEALTH_FORCE_FAIL_TEST
#define BOOT_HEALTH_FORCE_FAIL_TEST        (0U)
#endif

/* Stage 7.1: only software-visible preflight conditions. */
#define PREFLIGHT_FAIL_ADC_FAULT           (1UL << 0)
#define PREFLIGHT_FAIL_FOC_FAULT           (1UL << 1)
#define PREFLIGHT_FAIL_ENCODER             (1UL << 2)
#define PREFLIGHT_FAIL_FOC_DISABLED        (1UL << 3)
#define PREFLIGHT_FAIL_ZERO_CAL            (1UL << 4)
#define PREFLIGHT_FAIL_UART                (1UL << 5)
#define PREFLIGHT_FAIL_MODE                (1UL << 6)
#define PREFLIGHT_FAIL_SPEED               (1UL << 7)
#define PREFLIGHT_FAIL_FW_UPDATE           (1UL << 8)
#define PREFLIGHT_FAIL_TRIAL               (1UL << 9)
#define PREFLIGHT_FAIL_ADC_STALE           (1UL << 10)
#define PREFLIGHT_FAIL_FOC_STALE           (1UL << 11)
#define PREFLIGHT_CHAIN_MAX_STALE_MS       (50U)
#define PREFLIGHT_FAIL_BOOT_LOCK           (1UL << 12)
#define FOC_FAULT_ADC_CHAIN_STALE           (5U)
#define FOC_FAULT_CONTROL_CHAIN_STALE       (6U)
#define FOC_FAULT_STARTUP_ZERO_CAL          (7U)
#define FOC_FAULT_ADC_WINDOW                (8U)

typedef struct __attribute__((aligned(8)))
{
    uint32_t magic;
    uint32_t version;
    uint32_t active_slot;
    uint32_t crc32;
} BootMetaV1_t;

typedef struct __attribute__((aligned(8)))
{
    uint32_t magic;
    uint32_t version;

    uint32_t confirmed_slot;
    uint32_t pending_slot;
    uint32_t attempts_left;
    uint32_t generation;

    uint32_t app_a_size;
    uint32_t app_a_crc32;
    uint32_t app_b_size;
    uint32_t app_b_crc32;

    uint32_t flags;
    uint32_t crc32;
} BootMetaV2_t;

/*
 * V3 keeps exactly the same payload fields as V2.
 * The upgrade is the storage protocol: dual-page + generation + CRC32.
 */
typedef BootMetaV2_t BootMetaV3_t;

/*
 * V4 APP -> Bootloader command mailbox.
 * The top 64 bytes of SRAM are excluded from the linker RAM region in both
 * APP and bootloader projects, so this request survives NVIC_SystemReset().
 */
typedef struct __attribute__((aligned(8)))
{
    uint32_t magic;
    uint32_t version;
    uint32_t command;
    uint32_t requester_slot;
    uint32_t target_slot;
    uint32_t image_size;
    uint32_t image_crc32;
    uint32_t crc32;
} BootMailbox_t;

_Static_assert(sizeof(BootMailbox_t) <= BOOT_MAILBOX_RESERVED_BYTES,
               "BootMailbox_t exceeds reserved SRAM mailbox");

typedef struct
{
    uint8_t active;
    uint32_t target_slot;
    uint32_t target_address;
    uint32_t image_size;
    uint32_t expected_crc32;
    uint32_t bytes_received;
} FwUpdateContext_t;

static TightenParamsState_t recipe_state = TIGHTEN_PARAMS_STATE_INITIALIZER;

static FwUpdateContext_t fw_update =
{
    .active = 0U,
    .target_slot = APP_TARGET_SLOT,
    .target_address = APP_TARGET_ADDRESS,
    .image_size = 0U,
    .expected_crc32 = 0U,
    .bytes_received = 0U
};


/*
 * GDB-visible IAP diagnostics. These are deliberately non-static.
 * They let us diagnose FW BEGIN even when UART itself is the failing path.
 */
volatile uint32_t g_fw_diag_stage = 0U;
volatile uint32_t g_fw_diag_hal_status = 0U;
volatile uint32_t g_fw_diag_lock_status = 0U;
volatile uint32_t g_fw_diag_page_error = 0xFFFFFFFFUL;
volatile uint32_t g_fw_diag_flash_error = 0U;
volatile uint32_t g_fw_diag_flash_sr = 0U;
volatile uint32_t g_fw_diag_flash_cr = 0U;
volatile uint32_t g_fw_diag_erase_bank = 0U;
volatile uint32_t g_fw_diag_erase_page = 0U;
volatile uint32_t g_fw_diag_erase_pages = 0U;
volatile uint32_t g_fw_diag_ack_queued = 0U;
volatile uint32_t g_fw_diag_uart_rx_dma_state = 0U;
volatile uint32_t g_fw_diag_uart_rx_dma_remaining = 0U;
volatile uint32_t g_fw_diag_uart_rx_state = 0U;
volatile uint32_t g_fw_diag_uart_rx_dma_ccr = 0U;
volatile uint32_t g_fw_diag_uart_cr3 = 0U;
volatile uint32_t g_fw_diag_uart_rx_errors = 0U;
volatile uint32_t g_fw_diag_uart_rx_last_error = 0U;
volatile uint32_t g_fw_diag_uart_rx_restarts = 0U;
volatile uint32_t g_fw_diag_uart_rx_restart_failures = 0U;
volatile uint32_t g_fw_diag_uart_tx_queued = 0U;
volatile uint32_t g_fw_diag_uart_tx_dropped = 0U;
volatile uint32_t g_fw_diag_uart_tx_dma_errors = 0U;


/* Boot-health state is exposed through FW STATUS for trial diagnostics. */
static volatile uint8_t boot_health_trial_active = 0U;
static volatile uint8_t boot_health_last_sample_ok = 0U;
static volatile uint32_t boot_health_stable_ms = 0U;
static volatile uint32_t boot_health_elapsed_ms = 0U;
volatile uint32_t g_boot_health_fail_mask = 0U;
volatile uint32_t g_boot_health_last_adc_delta = 0U;
volatile uint32_t g_boot_health_last_foc_delta = 0U;
volatile uint32_t g_boot_health_sample_count = 0U;

/* Stage 8.3 diagnostics only. DWT includes interrupt/preemption time. */
static volatile uint8_t encoder_diag_dwt_ready = 0U;
static volatile uint32_t encoder_diag_reads = 0U;
static volatile uint32_t encoder_diag_failures = 0U;
static volatile uint32_t encoder_diag_over_1ms = 0U;
static volatile uint32_t encoder_diag_last_cycles = 0U;
static volatile uint32_t encoder_diag_max_cycles = 0U;
static volatile uint32_t motor_stack_min_words = UINT32_MAX;
static volatile uint32_t motor_stack_samples = 0U;
static TaskHandle_t motor_control_task_handle = NULL;


/*
 * Per-stage tightening result recorder.
 * TighteningTask samples at 100 Hz (10 ms/sample), independently of the
 * slower 500 ms MonitorTask UART snapshots.
 */
static TighteningStageResult_t tighten_result_seating;
static TighteningStageResult_t tighten_result_010;
static TighteningStageResult_t tighten_result_012;
static TighteningStageResult_t tighten_result_015;
static TighteningStageResult_t tighten_result_hold;
static volatile uint8_t tightening_result_printed = 0U;

static TighteningCycleSummary_t
    tightening_cycle_summary[TIGHTEN_REPEAT_CYCLES];

static volatile uint32_t tightening_cycle_number = 1U;
static volatile uint32_t tightening_cycle_ok_count = 0U;

/*
 * ProtocolTask -> TighteningTask command mailbox.
 * Only TighteningTask changes the application state machine.
 */
static volatile uint8_t tightening_start_request = 0U;
static volatile uint8_t tightening_stop_request = 0U;
static volatile uint8_t tightening_result_request = 0U;

/*
 * Protocol V2 correlation IDs.
 *
 * ProtocolTask writes the request ID before setting the corresponding
 * mailbox flag. TighteningTask consumes the flag + ID pair.
 *
 * cycle_request_id remains attached to the latest START cycle so later
 * RESULT queries can tell the host which START produced the stored result.
 */
static volatile uint32_t tightening_start_request_id = 0U;
static volatile uint32_t tightening_stop_request_id = 0U;
static volatile uint32_t tightening_result_request_id = 0U;
static volatile uint32_t tightening_cycle_request_id = 0U;

/*
 * Router Stage 4.1: preserve the origin of a START request after
 * ProtocolTask has finished handling the packet.
 *
 * The short-lived mailbox fields below belong to the START command that is
 * waiting for TighteningTask.  TighteningTask copies them into the persistent
 * session fields only when the cycle actually starts.
 *
 * routed = 0 : legacy/local UART START
 * routed = 1 : START arrived inside a routed ROUTER_PKT_PROTOCOL packet
 */
static volatile uint8_t tightening_start_request_routed = 0U;
static volatile uint16_t tightening_start_request_source_node = 0U;

/*
 * Persistent tightening-session owner.  These symbols are intentionally
 * global (not static) so they are easy to inspect with GDB while learning
 * Stage 4.1.
 *
 * active          : one tightening cycle currently owns this session
 * routed          : the START came from another Router node
 * owner_node      : source node that issued START (0 for local/legacy)
 * request_id      : Protocol V2 request ID of that START
 *
 * On cycle completion only active is cleared.  The remaining fields keep the
 * last owner/request for post-mortem inspection; the next successful START
 * overwrites them.
 */
volatile uint8_t g_tightening_session_active = 0U;
volatile uint8_t g_tightening_session_routed = 0U;
volatile uint16_t g_tightening_session_owner_node = 0U;
volatile uint32_t g_tightening_session_request_id = 0U;

/*
 * Router Stage 4.3: reliable routed asynchronous events.
 *
 * Stage 4.2 already moved application events out of TighteningTask and into a
 * ProtocolTask-owned queue. Stage 4.3 adds an application-level EID, ACK and
 * bounded retransmission on top of the existing Router route table.
 *
 * Router packet type 4 = reliable asynchronous EVENT
 * Router packet type 5 = EVENT ACK
 *
 * Router SEQ is transport-level and changes on every retry. EID is the stable
 * business-event identifier and stays unchanged across retransmissions.
 */
#define PROTOCOL_ASYNC_EVENT_QUEUE_DEPTH          (4U)
#define PROTOCOL_ROUTER_TYPE_EVENT                (4U)
#define PROTOCOL_ROUTER_TYPE_EVENT_ACK            (5U)
#define PROTOCOL_RELIABLE_EVENT_SLOTS             (4U)
#define PROTOCOL_RELIABLE_EVENT_RETRY_MS          (500U)
#define PROTOCOL_RELIABLE_EVENT_MAX_ATTEMPTS      (5U)
#define PROTOCOL_RELIABLE_RX_CACHE_SIZE           (8U)
#define PROTOCOL_RELIABLE_RX_CACHE_MS             (5000U)

typedef struct
{
    uint8_t routed;
    uint16_t dst_node;
    char payload[ROUTER_MAX_PAYLOAD + 1U];
} ProtocolAsyncEvent_t;

typedef struct
{
    uint8_t in_use;
    uint8_t attempts;
    uint16_t dst_node;
    uint32_t eid;
    TickType_t next_retry_tick;
    char payload[ROUTER_MAX_PAYLOAD + 1U];
} ProtocolReliableEvent_t;

typedef struct
{
    uint8_t valid;
    uint16_t src_node;
    uint32_t eid;
    TickType_t expires_tick;
} ProtocolReliableRxCache_t;

static QueueHandle_t protocol_async_event_queue = NULL;

/* Stage 6.2: only ModbusTask touches USART3; ProtocolTask never waits for RTU. */
#define MODBUS_QUEUE_DEPTH  (4U)
typedef enum
{
    MODBUS_JOB_READ = 0,
    MODBUS_JOB_RELAY = 1
} ModbusJobType_t;

typedef struct
{
    uint32_t request_id;
    uint32_t baud;
    uint16_t address;
    uint16_t reply_dst;
    uint8_t routed;
    uint8_t type;
    uint8_t slave;
    uint8_t function;
    uint8_t even_parity;
    uint8_t relay;
    uint8_t on;
} ModbusJob_t;

typedef struct
{
    ModbusJob_t job;
    ModbusProbeReply_t reply;
    ModbusProbeResult_t result;
    uint8_t busy;
} ModbusCompletion_t;

static QueueHandle_t modbus_request_queue = NULL;
static QueueHandle_t modbus_completion_queue = NULL;
static volatile uint32_t modbus_submitted = 0U;
static volatile uint32_t modbus_completed = 0U;
static volatile uint32_t modbus_failed = 0U;
static volatile uint32_t modbus_queue_full = 0U;
static volatile uint32_t modbus_timeout = 0U;
static volatile uint32_t modbus_crc_error = 0U;
static ProtocolReliableEvent_t
    protocol_reliable_events[PROTOCOL_RELIABLE_EVENT_SLOTS];
static ProtocolReliableRxCache_t
    protocol_reliable_rx_cache[PROTOCOL_RELIABLE_RX_CACHE_SIZE];
static uint32_t protocol_reliable_next_eid = 1U;
static uint32_t protocol_reliable_rx_cache_cursor = 0U;

volatile uint32_t g_protocol_async_event_enqueued = 0U;
volatile uint32_t g_protocol_async_event_queue_drop = 0U;
volatile uint32_t g_protocol_async_event_route_ok = 0U;
volatile uint32_t g_protocol_async_event_route_fail = 0U;
volatile uint32_t g_protocol_async_event_local_ok = 0U;

/* Stage 4.3 diagnostics, intentionally global for GDB inspection. */
volatile uint32_t g_protocol_reliable_event_created = 0U;
volatile uint32_t g_protocol_reliable_event_sent = 0U;
volatile uint32_t g_protocol_reliable_event_retried = 0U;
volatile uint32_t g_protocol_reliable_event_acked = 0U;
volatile uint32_t g_protocol_reliable_event_giveup = 0U;
volatile uint32_t g_protocol_reliable_event_table_full = 0U;
volatile uint32_t g_protocol_reliable_event_no_route = 0U;
volatile uint32_t g_protocol_reliable_event_rx = 0U;
volatile uint32_t g_protocol_reliable_event_rx_duplicate = 0U;
volatile uint32_t g_protocol_reliable_event_ack_tx = 0U;
volatile uint32_t g_protocol_reliable_event_ack_tx_fail = 0U;
volatile uint32_t g_protocol_reliable_event_bad_event = 0U;
volatile uint32_t g_protocol_reliable_event_bad_ack = 0U;

static volatile TighteningOutcome_t tightening_last_outcome =
    TIGHTEN_OUTCOME_NONE;
#if defined(ESP_NETWORK_OBSERVER)
static volatile uint32_t g_network_run, g_network_seq, g_network_drop;
#endif

/*
 * Position-command direction reversal tracking.
 *
 * +1: target lies in positive direction
 * -1: target lies in negative direction
 *  0: no previous non-zero command direction recorded yet
 *
 * When the position error crosses through zero and emerges on the opposite
 * side of the deadband, the old speed-PI integral is cleared so a stale
 * positive torque cannot fight a new negative command (and vice versa).
 */
static volatile int8_t position_error_sign_prev = 0;
static volatile uint32_t position_direction_reset_count = 0U;

/* Speed PI state. */
static volatile float speed_target_rpm = SPEED_REF_RPM;
static volatile float speed_ref_rpm = SPEED_REF_RPM; /* ramped reference */
static volatile float speed_integrator_A = 0.0f;
static volatile uint8_t speed_integrator_bleed_active = 0U;
static volatile uint8_t speed_overspeed_bleed_active = 0U;

/* Speed-PI diagnostic values printed over UART. */
static volatile float speed_error_rpm = 0.0f;
static volatile float speed_p_term_A = 0.0f;

/*
 * Time-weighted speed diagnostics.
 *
 * We accumulate at every accepted encoder-speed update instead of observing
 * only one instantaneous sample every UART print.  This avoids the previous
 * 150 rpm / 200 ms phase-lock problem.
 */
static float speed_diag_time_s = 0.0f;
static float speed_diag_speed_integral = 0.0f; /* rpm*s */
static float speed_diag_error_integral = 0.0f; /* rpm*s */
static float speed_diag_min_rpm = 0.0f;
static float speed_diag_max_rpm = 0.0f;
static uint8_t speed_diag_valid = 0U;

/* FOC fault diagnostics. */
static volatile uint32_t foc_fault_reason = 0U;
/* reason: 1=current trip, 2=encoder, 3=overspeed, 4=position/speed stall */
static volatile int32_t foc_trip_iu_mA = 0;
static volatile int32_t foc_trip_iv_mA = 0;
static volatile int32_t foc_trip_iw_mA = 0;

/* First overcurrent event only. Commit valid last; ProtocolTask never reads
 * partially written ISR data. This is diagnostic RAM, not a fault clear. */
typedef struct
{
    uint32_t tick_ms;
    uint32_t adc_seq;
    uint32_t vbus_age_ms;
    uint32_t current_valid_count;
    uint32_t current_reject_count;
    uint32_t current_reject_streak;
    uint32_t analog_sample_count;
    uint32_t analog_error_count;
    int32_t iu_mA;
    int32_t iv_mA;
    int32_t iw_mA;
    int32_t last_rejected_step;
    uint16_t accepted_u;
    uint16_t accepted_v;
    uint16_t physical_u;
    uint16_t physical_v;
    uint16_t zero_u;
    uint16_t zero_v;
    uint16_t vbus_raw;
    uint16_t median_u[3];
    uint16_t median_v[3];
    uint8_t filter_on;
    uint8_t median_count;
    uint8_t vbus_valid;
#if defined(FOC_CURRENT_TREND4)
    FocOcShadow shadow;
    int32_t raw_mA[3], filtered_mA[3];
    uint16_t trend_u[4], trend_v[4]; /* Chronological p,a,b,c; c is newest. */
    uint32_t trend_pairs, trend_changed, trend_u_changed, trend_v_changed;
    uint8_t trip_source, raw_mask, filtered_mask, spike_mask;
#endif
    uint8_t valid;
} FocCurrentTripSnapshot_t;
static volatile FocCurrentTripSnapshot_t foc_current_trip_snapshot;

/* Stall detector state / trip snapshot. */
static volatile float stall_timer_s = 0.0f;
static volatile float stall_trip_position_deg = 0.0f;
static volatile float stall_trip_target_deg = 0.0f;
static volatile float stall_trip_ref_rpm = 0.0f;
static volatile float stall_trip_speed_rpm = 0.0f;

/* First closed-loop FOC current controller state. */
static volatile uint8_t foc_enable = 0U;
static volatile uint8_t foc_fault = 0U;
static volatile uint32_t foc_control_count = 0U;
static volatile TickType_t preflight_adc_progress_tick = 0U;
static volatile TickType_t preflight_foc_progress_tick = 0U;

static volatile float foc_id_ref_A = FOC_ID_REF_A;
static volatile float foc_iq_ref_A = 0.0f;

static volatile float foc_id_A = 0.0f;
static volatile float foc_iq_A = 0.0f;
static volatile float foc_vd_V = 0.0f;
static volatile float foc_vq_V = 0.0f;

static volatile float foc_int_d_V = 0.0f;
static volatile float foc_int_q_V = 0.0f;

static volatile float foc_duty_u = 0.5f;
static volatile float foc_duty_v = 0.5f;
static volatile float foc_duty_w = 0.5f;

#include "foc_timeout_diag.h"
#include "foc_encoder_timeout_diag.h"
static FocTimeoutReason encoder_timeout_reason;
static void FaultDiag_Monitor(void);
static void FaultDiag_Clear(void);

/* USER CODE END PV */

