#include "motor_control.h"
#include <string.h>

void MotorControl_Reset(MotorControlSession *session) {
    if (session)
        memset(session, 0, sizeof(*session));
}

void MotorControl_Dispatch(MotorControlSession *s, const MotorControlPort *p, MotorControlOpcode op,
                           const MotorControlRequest *r, MotorControlReply *out) {
    if (!out)
        return;
    memset(out, 0, sizeof(*out));
    out->decision = MOTOR_RPC_INVALID;
    if (!s || !p || !p->snapshot || !p->submit_start || !p->submit_stop || !r ||
        r->version != MOTOR_CONTROL_VERSION || op < MOTOR_RPC_ARM || op > MOTOR_RPC_STATUS)
        return;
    p->snapshot(p->context, &out->view);
    out->operation_id = r->operation_id;
    if (s->boot_id != out->view.boot_id) {
        MotorControl_Reset(s);
        s->boot_id = out->view.boot_id;
    }
    if (op == MOTOR_RPC_STATUS) {
        out->decision = MOTOR_RPC_OK;
        return;
    }
    if (!r->operation_id)
        return;
    if (out->view.blockers & MOTOR_BLOCK_REMOTE_DISABLED) {
        s->armed = 0;
        out->decision = MOTOR_RPC_DISABLED;
        return;
    }
    if (!out->view.boot_id || r->boot_id != out->view.boot_id) {
        s->armed = 0;
        out->decision = MOTOR_RPC_BAD_SESSION;
        return;
    }
    /* STOP does not require ARM, a healthy sensor, or an idle motor. It is a
     * queued SOFTWARE request, never an emergency-stop guarantee. */
    if (op == MOTOR_RPC_STOP) {
        s->armed = 0;
        if (s->last_stop_id == r->operation_id) {
            out->decision = MOTOR_RPC_DUPLICATE;
            return;
        }
        out->decision = p->submit_stop(p->context, r->operation_id) ? MOTOR_RPC_QUEUED
                                                                    : MOTOR_RPC_QUEUE_REJECTED;
        if (out->decision == MOTOR_RPC_QUEUED)
            s->last_stop_id = r->operation_id;
        return;
    }
    if (op == MOTOR_RPC_START && s->last_start_id == r->operation_id) {
        out->decision = r->recipe_crc == s->last_recipe ? MOTOR_RPC_DUPLICATE : MOTOR_RPC_REPLAY;
        return;
    }
    if (op == MOTOR_RPC_START && s->last_start_id &&
        (uint32_t)(r->operation_id - s->last_start_id) >= 0x80000000U) {
        s->armed = 0;
        out->decision = MOTOR_RPC_REPLAY;
        return;
    }
    if (out->view.blockers || out->view.busy || out->view.safe_latched || out->view.preflight ||
        out->view.fault_reason) {
        s->armed = 0;
        out->decision = MOTOR_RPC_UNSAFE;
        return;
    }
    if (!out->view.recipe_crc || r->recipe_crc != out->view.recipe_crc) {
        s->armed = 0;
        out->decision = MOTOR_RPC_BAD_RECIPE;
        return;
    }
    if (op == MOTOR_RPC_ARM) {
        if (r->arm_token) {
            s->armed = 0;
            return;
        }
        if (++s->nonce == 0)
            ++s->nonce;
        /* A correlation token, NOT a cryptographic authorization secret. */
        s->arm_token = s->nonce;
        s->armed_at_ms = out->view.uptime_ms;
        s->armed_recipe = r->recipe_crc;
        s->armed = 1;
        out->arm_token = s->arm_token;
        out->decision = MOTOR_RPC_ARMED;
        return;
    }
    if (!s->armed) {
        out->decision = MOTOR_RPC_NOT_ARMED;
        return;
    }
    if ((uint32_t)(out->view.uptime_ms - s->armed_at_ms) >= MOTOR_CONTROL_ARM_MS) {
        s->armed = 0;
        out->decision = MOTOR_RPC_EXPIRED;
        return;
    }
    if (!r->arm_token || r->arm_token != s->arm_token || r->recipe_crc != s->armed_recipe) {
        s->armed = 0;
        out->decision = MOTOR_RPC_BAD_TOKEN;
        return;
    }
    s->armed = 0; /* one-shot, including failed enqueue */
    if (!p->submit_start(p->context, r->operation_id)) {
        out->decision = MOTOR_RPC_QUEUE_REJECTED;
        return;
    }
    s->last_start_id = r->operation_id;
    s->last_recipe = r->recipe_crc;
    out->decision = MOTOR_RPC_QUEUED;
}
