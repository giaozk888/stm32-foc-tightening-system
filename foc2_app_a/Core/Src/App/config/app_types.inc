/* App A config/app_types.inc: private binding, included once by main.c.
 * Keep the declared include order and original control/IRQ ownership. */
/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */

/*
 * Generic command interface used by the application layer.
 *
 * The application/TighteningTask never writes PWM directly.  It only selects
 * one of these motor modes and publishes a command.  MotorControlTask owns the
 * 1 kHz outer control; the ADC injected ISR continues to own the 20 kHz
 * current loop.
 */
typedef enum
{
    MOTOR_MODE_IDLE = 0,
    MOTOR_MODE_POSITION,
    MOTOR_MODE_SPEED,
    MOTOR_MODE_IQ
} MotorControlMode_t;

typedef enum
{
    TIGHTEN_STATE_IDLE_DELAY = 0,
    TIGHTEN_STATE_RUNDOWN,
    TIGHTEN_STATE_CONTACT_STOP,
    TIGHTEN_STATE_SEATING_IQ,
    TIGHTEN_STATE_TIGHTEN_010,
    TIGHTEN_STATE_TIGHTEN_012,
    TIGHTEN_STATE_TIGHTEN_015,
    TIGHTEN_STATE_HOLD,
    TIGHTEN_STATE_CYCLE_PAUSE,
    TIGHTEN_STATE_DONE,
    TIGHTEN_STATE_TIMEOUT,
    TIGHTEN_STATE_FAULT
} TighteningTestStage_t;

typedef enum
{
    TIGHTEN_OUTCOME_NONE = 0,
    TIGHTEN_OUTCOME_OK,
    TIGHTEN_OUTCOME_STOPPED,
    TIGHTEN_OUTCOME_RUNDOWN_TIMEOUT,
    TIGHTEN_OUTCOME_STOP_TIMEOUT,
    TIGHTEN_OUTCOME_ABORT,
    TIGHTEN_OUTCOME_FAULT,
    TIGHTEN_OUTCOME_NO_ROTATION
} TighteningOutcome_t;

/*
 * ASCII Protocol V1 error codes.
 * Keep these numeric values stable once an external client depends on them.
 */
typedef enum
{
    PROTO_ERR_UNKNOWN_COMMAND = 100,
    PROTO_ERR_BUSY            = 101,
    PROTO_ERR_LINE_TOO_LONG   = 102,
    PROTO_ERR_BAD_ARGUMENT    = 103,
    PROTO_ERR_NOT_READY       = 104,
    PROTO_ERR_FAULT           = 105,
    PROTO_ERR_ROTOR_MOVING    = 106,
    PROTO_ERR_FLASH           = 107,
    PROTO_ERR_NO_VALID_PARAMS = 108,
    PROTO_ERR_FW_STATE        = 109,
    PROTO_ERR_FW_CRC          = 110,
    PROTO_ERR_FW_RANGE        = 111,
    PROTO_ERR_FW_SEQUENCE     = 112
} ProtocolError_t;

typedef struct
{
    float command_A;
    float iq_sum_A;
    float iq_max_A;
    float ctrl_max_abs_rpm;
    float det_sum_abs_rpm;
    float start_position_deg;
    float end_position_deg;
    uint32_t sample_count;
} TighteningStageResult_t;

typedef struct
{
    uint8_t valid;
    float rundown_travel_deg;
    float post_travel_deg;

    float seating_iq_avg_A;
    float tighten1_iq_avg_A;
    float tighten2_iq_avg_A;
    float tighten3_iq_avg_A;
    float hold_iq_avg_A;

    float seating_iq_max_A;
    float tighten3_iq_max_A;
    float hold_iq_max_A;
} TighteningCycleSummary_t;

/* USER CODE END PTD */

