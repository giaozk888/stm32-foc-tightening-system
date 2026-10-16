#include "tighten_synthetic_bench.h"

#include <cmath>
#include <cstring>
#include <new>

namespace {
constexpr float kPi = 3.14159265358979323846f;
constexpr float kDt = 0.0005f;
constexpr uint32_t kMagic = 0x53494D31U;
constexpr uint32_t kMaxTicks = 32000U;
enum Stage { Rundown, ContactStop, Seating, T1, T2, T3, Hold, Approach, Torque };
struct Sample {
    uint32_t tick;
    float angle, rpm, detect, iq, torque;
};
struct Command {
    uint32_t due;
    float value;
};
struct Work {
    uint32_t magic, case_id, feedback, tick, done_tick, outcome, stage_tick;
    uint32_t stage, confirm_ms, transitions, sample_head, sample_count;
    uint32_t command_head, command_count, detector_head, detector_count;
    bool stripped;
    TightSimConfig config;
    float theta, omega, iq, peak, request, applied, maximum, integral;
    float contact_angle, target, kt, stiffness, seat, torque_gain;
    uint32_t delay_ticks;
    Sample samples[48], latest;
    Command commands[8];
    float detector[50];
};
static_assert(sizeof(Work) <= TIGHTSIM_CONTEXT_BYTES, "Synthetic context budget");
static_assert(alignof(Work) <= alignof(TightSimContext), "Context alignment");

float clamp(float x, float low, float high) {
    return fmaxf(low, fminf(high, x));
}
Work &work(TightSimContext *context) {
    return *reinterpret_cast<Work *>(context->bytes);
}
const Work &work(const TightSimContext *context) {
    return *reinterpret_cast<const Work *>(context->bytes);
}
float rpm(const Work &w) {
    return w.omega * 60.0f / (2.0f * kPi);
}
float angle(const Work &w) {
    return w.theta * 180.0f / kPi;
}
float true_torque(const Work &w) {
    if (w.case_id == 2U || w.stripped)
        return 0.0f;
    return w.stiffness * fmaxf(0.0f, w.theta - w.seat * kPi / 180.0f);
}
void enter(Work &w, Stage stage) {
    w.stage = static_cast<uint32_t>(stage);
    w.stage_tick = w.tick;
    w.confirm_ms = 0U;
    ++w.transitions;
}
void finish(Work &w, TightSimOutcome outcome) {
    if (w.outcome != TIGHTSIM_RUNNING)
        return;
    w.outcome = outcome;
    w.done_tick = w.tick;
    w.request = w.applied = w.integral = 0.0f;
    w.command_head = w.command_count = 0U;
    ++w.transitions;
}
float speed_pi(Work &w, float reference, float limit) {
    float error = reference - w.latest.rpm;
    float candidate = w.integral + w.config.speed_ki * error * 0.001f;
    float unsaturated = w.config.speed_kp * error + candidate;
    float output = clamp(unsaturated, -limit, limit);
    if (output == unsaturated || (output >= limit && error < 0.0f) ||
        (output <= -limit && error > 0.0f))
        w.integral = candidate;
    return output;
}
void sample(Work &w) {
    if (w.case_id != 8U || w.tick < 800U) {
        if (w.sample_count == 48U) {
            finish(w, TIGHTSIM_INVALID);
            return;
        }
        w.detector[w.detector_head] = rpm(w);
        w.detector_head = (w.detector_head + 1U) % 50U;
        if (w.detector_count < 50U)
            ++w.detector_count;
        float sum = 0.0f;
        for (uint32_t i = 0; i < w.detector_count; ++i)
            sum += w.detector[i];
        Sample s{w.tick, roundf(angle(w) / (360.0f / 16384.0f)) * (360.0f / 16384.0f),
                 rpm(w), sum / static_cast<float>(w.detector_count),
                 w.iq,   true_torque(w) * w.torque_gain};
        w.samples[(w.sample_head + w.sample_count) % 48U] = s;
        ++w.sample_count;
    }
    while (w.sample_count > 1U &&
           w.samples[(w.sample_head + 1U) % 48U].tick + w.delay_ticks <= w.tick) {
        w.sample_head = (w.sample_head + 1U) % 48U;
        --w.sample_count;
    }
    w.latest = w.samples[w.sample_head];
}
void baseline_app(Work &w) {
    const auto &p = w.config.recipe;
    const auto &s = w.latest;
    uint32_t elapsed = (w.tick - w.stage_tick) / 2U;
    if (w.stage == Rundown) {
        bool contact = fabsf(s.detect) <= p.contact_rpm &&
                       w.request >= static_cast<float>(p.contact_iq_mA) / 1000.0f;
        w.confirm_ms = contact ? w.confirm_ms + 10U : 0U;
        if (w.confirm_ms >= p.contact_ms) {
            w.contact_angle = s.angle;
            enter(w, ContactStop);
        } else if (elapsed >= p.rundown_timeout_ms || fabsf(s.angle) >= p.max_travel_deg)
            finish(w, TIGHTSIM_RUNDOWN_TIMEOUT);
    } else if (w.stage == ContactStop) {
        w.confirm_ms = fabsf(s.rpm) <= w.config.stop_max_rpm ? w.confirm_ms + 10U : 0U;
        if (w.confirm_ms >= w.config.stop_confirm_ms)
            enter(w, Seating);
        else if (elapsed >= w.config.stop_timeout_ms)
            finish(w, TIGHTSIM_STOP_TIMEOUT);
    } else if (w.stage >= Seating && w.stage <= Hold) {
        if (fabsf(s.rpm) >= p.torque_abort_rpm ||
            fabsf(s.angle - w.contact_angle) >= p.post_travel_max_deg) {
            finish(w, TIGHTSIM_ABORT);
            return;
        }
        const uint32_t durations[] = {p.seating_ms, p.t1_ms, p.t2_ms, p.t3_ms, p.hold_ms};
        if (elapsed >= durations[w.stage - Seating]) {
            if (w.stage == Hold)
                finish(w, TIGHTSIM_PROCESS_OK);
            else
                enter(w, static_cast<Stage>(w.stage + 1U));
        }
    }
}
void feedback_app(Work &w) {
    const auto &s = w.latest;
    const auto &p = w.config.recipe;
    if (s.torque > w.target * 1.05f) {
        finish(w, TIGHTSIM_OVERTORQUE);
        return;
    }
    if (w.stage == Rundown || w.stage == Approach) {
        if (s.torque >= w.target * 0.10f) {
            if (s.angle < 150.0f || s.angle > 210.0f) {
                finish(w, TIGHTSIM_ANGLE_REJECT);
                return;
            }
            w.contact_angle = s.angle;
            enter(w, Torque);
        } else if (w.stage == Rundown && s.angle >= 120.0f) {
            w.integral = clamp(w.integral, -w.config.direct_iq_limit, w.config.direct_iq_limit);
            enter(w, Approach);
        } else if (w.tick / 2U >= p.rundown_timeout_ms || s.angle >= p.max_travel_deg)
            finish(w, TIGHTSIM_RUNDOWN_TIMEOUT);
    } else if (w.stage == Torque) {
        if (s.angle - w.contact_angle >= p.post_travel_max_deg ||
            fabsf(s.rpm) >= p.torque_abort_rpm) {
            finish(w, TIGHTSIM_ABORT);
            return;
        }
        bool good =
            s.torque >= w.target * 0.95f && s.torque <= w.target * 1.05f && fabsf(s.rpm) <= 2.0f;
        w.confirm_ms = good ? w.confirm_ms + 10U : 0U;
        if (w.confirm_ms >= 150U)
            finish(w, TIGHTSIM_MODEL_OK);
        else if ((w.tick - w.stage_tick) / 2U >= 5000U)
            finish(w, TIGHTSIM_TORQUE_TIMEOUT);
    }
}
void fast(Work &w) {
    sample(w);
    if (w.outcome == TIGHTSIM_RUNNING) {
        if (w.case_id == 9U && w.tick >= 800U)
            finish(w, TIGHTSIM_FAULT_INJECTED);
        else if (w.case_id == 10U && w.tick >= 800U)
            finish(w, TIGHTSIM_STOPPED);
        else if (w.tick - w.latest.tick > 60U)
            finish(w, TIGHTSIM_FEEDBACK_STALE);
    }
    if (w.outcome == TIGHTSIM_RUNNING && w.tick % 20U == 0U) {
        if (w.feedback)
            feedback_app(w);
        else
            baseline_app(w);
    }
    if (w.outcome != TIGHTSIM_RUNNING)
        return;
    if (w.stage == Rundown)
        w.request =
            speed_pi(w, static_cast<float>(w.config.recipe.rundown_rpm), w.config.speed_iq_limit);
    else if (w.feedback) {
        float reference = w.stage == Torque
                              ? clamp((w.target - w.latest.torque) / w.target * 6.0f, 0.0f, 2.0f)
                              : 2.0f;
        w.request = speed_pi(w, reference, w.config.direct_iq_limit);
    } else if (w.stage >= Seating && w.stage <= Hold) {
        const auto &p = w.config.recipe;
        const uint32_t currents[] = {p.seating_iq_mA, p.t1_iq_mA, p.t2_iq_mA, p.t3_iq_mA,
                                     p.hold_iq_mA};
        w.request = fminf(currents[w.stage - Seating] / 1000.0f, w.config.direct_iq_limit);
    } else
        w.request = w.integral = 0.0f;
    w.maximum = fmaxf(w.maximum, fabsf(w.request));
    if (!std::isfinite(w.request) || w.command_count >= 8U) {
        finish(w, TIGHTSIM_INVALID);
        return;
    }
    w.commands[(w.command_head + w.command_count) % 8U] = Command{w.tick + 2U, w.request};
    ++w.command_count;
}
void step(Work &w) {
    if (w.tick % 2U == 0U)
        fast(w);
    while (w.command_count && w.commands[w.command_head].due <= w.tick) {
        w.applied = w.commands[w.command_head].value;
        w.command_head = (w.command_head + 1U) % 8U;
        --w.command_count;
    }
    bool enabled = w.outcome == TIGHTSIM_RUNNING && w.stage != ContactStop;
    w.iq += ((enabled ? w.applied : 0.0f) - w.iq) * 0.3934693402873666f;
    float resistance = true_torque(w) + 0.00010f + 0.00005f * w.omega;
    w.omega = fmaxf(0.0f, w.omega + (w.kt * w.iq - resistance) * kDt / 0.000020f);
    w.theta += w.omega * kDt;
    if (w.case_id == 4U && true_torque(w) >= 0.0010f)
        w.stripped = true;
    w.peak = fmaxf(w.peak, true_torque(w));
    if (!std::isfinite(w.theta) || !std::isfinite(w.iq) || !std::isfinite(w.omega))
        finish(w, TIGHTSIM_INVALID);
    if (w.outcome == TIGHTSIM_RUNNING && w.tick >= kMaxTicks)
        finish(w, TIGHTSIM_SIMULATION_TIMEOUT);
    ++w.tick;
}
uint32_t nnm(float torque) {
    if (!std::isfinite(torque) || torque < 0.0f || torque > 4.0f)
        return UINT32_MAX;
    return static_cast<uint32_t>(torque * 1.0e9f + 0.5f);
}
} // namespace

extern "C" TightSimConfig TightSim_DefaultConfig(void) {
    return TightSimConfig{
        TIGHTEN_PARAMS_DEFAULT_INITIALIZER, 0.003f, 0.020f, 0.40f, 0.15f, 2.0f, 150U, 2000U};
}
extern "C" int TightSim_Begin(TightSimContext *context, const TightSimConfig *config,
                              uint32_t case_id, uint32_t feedback) {
    if (!context || !config || case_id >= TIGHTSIM_CASES || feedback > 1U)
        return 0;
    if (!std::isfinite(config->speed_kp) || !std::isfinite(config->speed_ki) ||
        !std::isfinite(config->speed_iq_limit) || !std::isfinite(config->direct_iq_limit) ||
        config->speed_kp <= 0 || config->speed_ki <= 0 || config->speed_iq_limit <= 0 ||
        config->speed_iq_limit > 0.40f || config->direct_iq_limit <= 0 ||
        config->direct_iq_limit > 0.15f || !std::isfinite(config->stop_max_rpm) ||
        config->stop_max_rpm <= 0 || !config->stop_confirm_ms || !config->stop_timeout_ms)
        return 0;
#define CHECK(field, name, low, high, initial)                                                     \
    if (config->recipe.field < low || config->recipe.field > high)                                 \
        return 0;
    TIGHTEN_PARAM_FIELDS(CHECK)
#undef CHECK
    auto &w = *new (context->bytes) Work{};
    w.magic = kMagic;
    w.config = *config;
    w.case_id = case_id;
    w.feedback = feedback;
    w.kt = case_id == 6U ? 0.016f : 0.020f;
    w.stiffness =
        (case_id == 1U || case_id == 4U || case_id == 5U || case_id == 6U || case_id == 11U)
            ? 0.010f
            : 0.20f;
    w.seat = case_id == 3U ? 10.0f : 180.0f;
    w.torque_gain = case_id == 5U ? 1.10f : 1.0f;
    w.target = case_id == 11U ? 0.20f : 0.002f;
    w.delay_ticks = case_id == 7U ? 80U : 4U;
    w.sample_count = 1U;
    w.transitions = 1U;
    if (feedback && w.target > config->direct_iq_limit * 0.020f)
        finish(w, TIGHTSIM_TARGET_UNREACHABLE);
    return 1;
}
extern "C" int TightSim_Advance(TightSimContext *context, uint32_t budget) {
    if (!context || !budget || budget > 128U || work(context).magic != kMagic)
        return -1;
    auto &w = work(context);
    for (uint32_t i = 0; i < budget; ++i) {
        if (w.outcome != TIGHTSIM_RUNNING && w.tick >= w.done_tick + 500U)
            return 1;
        step(w);
    }
    return w.outcome != TIGHTSIM_RUNNING && w.tick >= w.done_tick + 500U ? 1 : 0;
}
extern "C" int TightSim_Result(const TightSimContext *context, TightSimResult *result) {
    if (!context || !result || work(context).magic != kMagic)
        return 0;
    const auto &w = work(context);
    if (w.outcome == TIGHTSIM_RUNNING || w.tick < w.done_tick + 500U)
        return 0;
    float actual = true_torque(w);
    *result = TightSimResult{
        w.case_id,
        w.feedback,
        w.outcome,
        w.done_tick / 2U,
        nnm(actual),
        nnm(w.peak),
        nnm(w.target),
        static_cast<uint32_t>(w.maximum * 1000.0f + 0.5f),
        static_cast<uint32_t>(actual >= w.target * 0.95f && actual <= w.target * 1.05f &&
                              w.peak <= w.target * 1.05f && !w.stripped),
        static_cast<uint32_t>(w.stripped),
        1U,
        w.transitions,
        w.tick,
        static_cast<uint32_t>(w.request == 0.0f && w.applied == 0.0f && w.command_count == 0U)};
    return 1;
}
extern "C" const char *TightSim_OutcomeName(uint32_t outcome) {
    static const char *names[] = {"RUNNING",
                                  "PROCESS_OK",
                                  "MODEL_OK",
                                  "RUNDOWN_TIMEOUT",
                                  "STOP_TIMEOUT",
                                  "ABORT",
                                  "OVERTORQUE",
                                  "ANGLE_REJECT",
                                  "TORQUE_TIMEOUT",
                                  "FEEDBACK_STALE",
                                  "FAULT_INJECTED",
                                  "STOPPED",
                                  "TARGET_UNREACHABLE",
                                  "SIMULATION_TIMEOUT",
                                  "INVALID"};
    return outcome <= TIGHTSIM_INVALID ? names[outcome] : "INVALID";
}
