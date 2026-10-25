#ifndef CAN_STATUS_TX_H
#define CAN_STATUS_TX_H

#include <stdint.h>
#include "can_wire_profile.h"

/* Default classic CAN, 500 kbit/s. FD is an opt-in isolated profile only. */
#define CAN_STATUS_V1_ID 0x180U
#define CAN_MOTOR_V1_ID 0x181U
#define CAN_ELECTRICAL_V1_ID 0x182U
#define CAN_STATUS_FLAG_FOC_ENABLED 0x01U
#define CAN_STATUS_FLAG_FAULT_LATCHED 0x02U
#define CAN_STATUS_FLAG_ENCODER_VALID 0x04U
#define CAN_STATUS_FLAG_DRIVER_SD_HIGH 0x08U

/* Failure is nonfatal to motor control; the monitor task may keep running. */
uint8_t CAN_StatusTx_Init(void);
/* Poll only from MonitorTask. At most three delayed recovery attempts per boot. */
void CAN_StatusTx_Service(uint32_t now_ms);
/* MonitorTask only, logger IDs only, reserve a FIFO slot, suppress on CAN errors. */
uint8_t CAN_StatusTx_TryLogFrame(uint32_t id, const uint8_t data[8]);

typedef struct {
    uint32_t init_attempts;
    uint32_t recoveries;
    uint32_t init_failures;
    uint32_t bus_off_events;
    uint32_t fifo_stalls;
    uint32_t tx_enqueued;
    uint32_t tx_completed;
    uint32_t tx_event_lost;
    uint32_t tx_fifo_full;
    uint32_t tx_add_failures;
    uint32_t tx_error_count;
    uint32_t rx_error_count;
    uint32_t last_error_code;
    uint32_t fifo_free;
    uint8_t ready;
    uint8_t recovery_exhausted;
} CAN_StatusTx_Health;

void CAN_StatusTx_GetHealth(CAN_StatusTx_Health *out);
#if CAN_WIRE_FD_ENABLED
typedef struct {
    uint32_t received;
    uint32_t rejected;
    uint32_t dropped;
    uint32_t fifo_overruns;
    uint32_t echoes_enqueued; /* Not proof of on-wire delivery. */
} CAN_FdProbeHealth;
void CAN_StatusTx_GetFdProbeHealth(CAN_FdProbeHealth *out);
#endif
#if defined(CAN_RPC_READ_ONLY)
/* MonitorTask only, exact RPC response ID, never a generic CAN send API. */
uint8_t CAN_StatusTx_TryRpcFrame(uint32_t id, const uint8_t data[8]);
#endif
#if defined(SAFETY_LOCKED_BOOT)
/* Single owner: locked sampling loop only; allowlisted read-only diagnostic IDs. */
uint8_t CAN_StatusTx_TrySafetyFrame(uint32_t id, const uint8_t data[8]);
#endif
#if defined(CAN_SHADOW_DIAG)
typedef struct {
    uint32_t received;
    uint32_t invalid_frames;
    uint32_t replies_queued;
    uint32_t replies_dropped;
    uint32_t probe_timeouts;
    uint32_t stop_tests;
    uint32_t range_rejects;
    uint32_t fifo_overruns;
} CAN_ShadowHealth;
void CAN_StatusTx_GetShadowHealth(CAN_ShadowHealth *out);
#endif
#if defined(CAN_CONTROL_REJECT_ONLY)
typedef struct {
    uint32_t received;
    uint32_t invalid_frames;
    uint32_t rejected;
    uint32_t replies_queued;
    uint32_t replies_dropped;
    uint32_t fifo_overruns;
} CAN_ControlRejectHealth;
void CAN_StatusTx_GetControlRejectHealth(CAN_ControlRejectHealth *out);
#endif
void CAN_StatusTx_Publish(uint8_t mode, uint8_t flags, uint16_t fault_code);
/* Read-only measurements; invalid values are marked, never invented as zero. */
void CAN_StatusTx_PublishMotor(float angle_deg, float iq_A,
                               uint8_t angle_valid, uint8_t current_valid);
void CAN_StatusTx_PublishElectrical(uint32_t vbus_mv, float speed_rpm,
                                    uint8_t vbus_valid, uint8_t speed_valid);

#endif
