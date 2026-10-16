#include "tighten_synthetic_bench.h"
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstring>

int main() {
    TightSimContext ctx{};
    auto config = TightSim_DefaultConfig();
    assert(!TightSim_Begin(nullptr, &config, 0, 0));
    assert(!TightSim_Begin(&ctx, nullptr, 0, 0));
    assert(!TightSim_Begin(&ctx, &config, 12, 0));
    assert(!TightSim_Begin(&ctx, &config, 0, 2));
    assert(TightSim_Advance(&ctx, 1) == -1);
    auto bad = config;
    bad.direct_iq_limit = 0.16f;
    assert(!TightSim_Begin(&ctx, &bad, 0, 0));
    bad = config;
    bad.speed_kp = NAN;
    assert(!TightSim_Begin(&ctx, &bad, 0, 0));
    bad = config;
    bad.recipe.rundown_rpm = 121U;
    assert(!TightSim_Begin(&ctx, &bad, 0, 0));
    const uint32_t expected[12][2] = {{TIGHTSIM_PROCESS_OK, TIGHTSIM_MODEL_OK},
                                      {TIGHTSIM_PROCESS_OK, TIGHTSIM_MODEL_OK},
                                      {TIGHTSIM_RUNDOWN_TIMEOUT, TIGHTSIM_RUNDOWN_TIMEOUT},
                                      {TIGHTSIM_PROCESS_OK, TIGHTSIM_OVERTORQUE},
                                      {TIGHTSIM_RUNDOWN_TIMEOUT, TIGHTSIM_TORQUE_TIMEOUT},
                                      {TIGHTSIM_PROCESS_OK, TIGHTSIM_MODEL_OK},
                                      {TIGHTSIM_PROCESS_OK, TIGHTSIM_TORQUE_TIMEOUT},
                                      {TIGHTSIM_FEEDBACK_STALE, TIGHTSIM_FEEDBACK_STALE},
                                      {TIGHTSIM_FEEDBACK_STALE, TIGHTSIM_FEEDBACK_STALE},
                                      {TIGHTSIM_FAULT_INJECTED, TIGHTSIM_FAULT_INJECTED},
                                      {TIGHTSIM_STOPPED, TIGHTSIM_STOPPED},
                                      {TIGHTSIM_PROCESS_OK, TIGHTSIM_TARGET_UNREACHABLE}};
    for (uint32_t id = 0; id < 12; ++id)
        for (uint32_t mode = 0; mode < 2; ++mode) {
            assert(TightSim_Begin(&ctx, &config, id, mode));
            assert(TightSim_Advance(&ctx, 0) == -1);
            assert(TightSim_Advance(&ctx, 129) == -1);
            TightSimResult r{};
            assert(!TightSim_Result(&ctx, &r));
            uint32_t loops = 0;
            int done;
            do {
                done = TightSim_Advance(&ctx, 128);
                assert(++loops < 300);
            } while (!done);
            assert(done == 1 && TightSim_Result(&ctx, &r));
            assert(r.outcome == expected[id][mode]);
            assert(r.model_only == 1 && r.terminal_command_zero == 1);
            assert(r.max_command_ma <= 400U && r.steps <= 32501U);
            if (mode && id <= 1)
                assert(r.truth_in_demo_band);
            if (id == 5)
                assert(!r.truth_in_demo_band);
            if (id == 11 && mode)
                assert(!r.max_command_ma);
            if (id == 4)
                assert(r.stripped);
            auto saved = r;
            assert(TightSim_Advance(&ctx, 128) == 1 && TightSim_Result(&ctx, &r));
            assert(memcmp(&saved, &r, sizeof(r)) == 0);
            printf("CASE=%u MODE=%u OUT=%s MS=%u FINAL=%u PEAK=%u TARGET=%u MAXMA=%u TRUTH=%u "
                   "STEPS=%u TRANS=%u OFF=%u MODEL=1\n",
                   r.case_id, r.feedback, TightSim_OutcomeName(r.outcome), r.elapsed_ms,
                   r.final_nnm, r.peak_nnm, r.target_nnm, r.max_command_ma, r.truth_in_demo_band,
                   r.steps, r.state_transitions, r.terminal_command_zero);
        }
    puts("SYNTHETIC HOST PASS: 24 deterministic scenarios; no hardware access");
}
