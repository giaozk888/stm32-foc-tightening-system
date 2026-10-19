"""Offline model contracts only. Never connects to hardware."""

from dataclasses import replace
import math
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "simulation/tightening"))
from model import (
    Assumptions, BaselineController, FeedbackController, Plant, Sample, SimRecipe,
    SpeedPI, load_firmware_profile, simulate,
)
from run import aggregate, numerical_checks, write_report


class TighteningSimulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = load_firmware_profile()

    def test_reads_project_defaults_and_current_limits(self):
        self.assertEqual(len(self.profile.recipe), 18)
        self.assertEqual(self.profile.recipe["hold_iq_mA"], 150)
        self.assertEqual(self.profile.constants["MOTOR_DIRECT_IQ_LIMIT_A"], 0.20)
        self.assertEqual(self.profile.constants["MOTOR_SPEED_IQ_LIMIT_A"], 0.40)
        self.assertEqual(self.profile.constants["FOC_CURRENT_TRIP_A"], 4.0)
        self.assertEqual(self.profile.constants["FOC_VOLTAGE_LIMIT_V"], 0.80)
        self.assertEqual(self.profile.constants["FOC_TS_S"], 0.00005)
        self.assertEqual(len(self.profile.hashes), 3)

    def test_recipe_edit_is_copy_and_stays_in_persistent_range(self):
        p = self.profile.with_recipe(rundown_rpm=70)
        self.assertEqual(p.recipe["rundown_rpm"], 70)
        self.assertEqual(self.profile.recipe["rundown_rpm"], 80)
        for field, value in (("rundown_rpm", 9999), ("hold_iq_mA", 151), ("bogus", 1)):
            with self.assertRaises(ValueError):
                self.profile.with_recipe(**{field: value})

    def test_one_third_speed_uses_normal_range_and_keeps_protections(self):
        increased = self.profile.with_recipe(rundown_rpm=round(80 * 4 / 3))
        self.assertEqual(increased.recipe["rundown_rpm"], 107)
        self.assertEqual(increased.ranges, self.profile.ranges)
        self.assertEqual(increased.constants, self.profile.constants)
        self.assertEqual(self.profile.recipe["rundown_rpm"], 80)
        for name, value in self.profile.recipe.items():
            if name != "rundown_rpm":
                self.assertEqual(increased.recipe[name], value)
        for mode in ("baseline", "feedback"):
            result = simulate(increased, Assumptions(stop_s=0.05), controller=mode)
            self.assertEqual(result.outcome, "STOPPED")
            self.assertEqual(result.terminal_command_a, 0)
            self.assertLessEqual(result.max_command_a, 0.40)

    def test_report_separates_source_defaults_from_model_override(self):
        import json
        increased = self.profile.with_recipe(rundown_rpm=107)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            write_report(output, increased, {}, {}, 30, [],
                         source_recipe_defaults=self.profile.recipe,
                         recipe_overrides={"rundown_rpm": 107})
            report = json.loads((output / "results.json").read_text(encoding="utf-8"))
            self.assertEqual(report["source_recipe_defaults"]["rundown_rpm"], 80)
            self.assertEqual(report["effective_recipe"]["rundown_rpm"], 107)
            self.assertEqual(report["recipe_overrides"], {"rundown_rpm": 107})
            self.assertFalse(report["hardware_access"])
            self.assertFalse(report["industrial_accuracy_certified"])
            self.assertFalse(report["numerical_checks_passed"])

    def test_double_speed_profile_only_changes_rundown(self):
        doubled = load_firmware_profile(speed_profile="x2-offline")
        self.assertEqual(doubled.recipe["rundown_rpm"], 160)
        self.assertEqual(doubled.ranges["rundown_rpm"], (20, 240))
        self.assertEqual(self.profile.recipe["rundown_rpm"], 80)
        self.assertEqual(self.profile.ranges["rundown_rpm"], (20, 120))
        for name in self.profile.recipe:
            if name != "rundown_rpm":
                self.assertEqual(doubled.recipe[name], self.profile.recipe[name])
                self.assertEqual(doubled.ranges[name], self.profile.ranges[name])
        self.assertEqual(doubled.constants, self.profile.constants)
        self.assertEqual(doubled.with_recipe(rundown_rpm=240).recipe["rundown_rpm"], 240)
        with self.assertRaises(ValueError):
            doubled.with_recipe(rundown_rpm=241)
        with self.assertRaises(ValueError):
            load_firmware_profile(speed_profile="unlimited")

    def test_double_speed_keeps_current_limit_and_fault_stop(self):
        doubled = load_firmware_profile(speed_profile="x2-offline")
        for mode in ("baseline", "feedback"):
            run = simulate(doubled, controller=mode)
            self.assertLessEqual(run.max_command_a, 0.40)
            for assumptions, outcome in (
                # Inject before contact; later injection may correctly lose
                # priority to an earlier OVERTORQUE at the faster approach.
                (Assumptions(stop_s=0.05), "STOPPED"),
                (Assumptions(injected_fault_s=0.05), "FAULT_INJECTED"),
                (Assumptions(feedback_dropout_s=0.05), "FEEDBACK_STALE"),
            ):
                run = simulate(doubled, assumptions, controller=mode)
                self.assertEqual(run.outcome, outcome)
                self.assertEqual(run.terminal_command_a, 0)

    def test_legacy_150ma_double_speed_model_reports_overshoot_instead_of_success(self):
        doubled = load_firmware_profile(speed_profile="x2-offline")
        # Keep this historical overshoot fixture at its identified 150mA
        # model limit, not the newly requested firmware 200mA limit.
        doubled = replace(doubled, constants={**doubled.constants, "MOTOR_DIRECT_IQ_LIMIT_A": 0.15})
        run = simulate(doubled, controller="feedback")
        self.assertEqual(run.outcome, "OVERTORQUE")
        self.assertFalse(run.truth_within_demo_band)
        self.assertFalse(run.quality_claim_allowed)
        self.assertEqual(run.terminal_command_a, 0)

    def test_requested_200ma_model_is_not_a_hardware_quality_certificate(self):
        doubled = load_firmware_profile(speed_profile="x2-offline")
        self.assertEqual(doubled.constants["MOTOR_DIRECT_IQ_LIMIT_A"], 0.20)
        run = simulate(doubled, controller="feedback")
        self.assertFalse(run.quality_claim_allowed)
        # Complete-model rundown still uses the unchanged 0.40A speed limit;
        # direct-IQ post stages use the separate 0.20A clamp.
        self.assertLessEqual(run.max_command_a, doubled.constants["MOTOR_SPEED_IQ_LIMIT_A"] + 1e-9)
        self.assertEqual(run.terminal_command_a, 0)

    def test_contact_requires_speed_and_iq_continuously(self):
        e = BaselineController(self.profile, SimRecipe())
        def feed(now, speed, iq):
            e.drive_request_a = iq
            e.app_step(Sample(now, 180, speed, speed, iq, 0), now, 0.01)
        for tick in range(24):
            feed(tick * 0.01, 0, 0.30)
        self.assertEqual(e.state, "RUNDOWN")
        feed(0.24, 11, 0.30)
        self.assertEqual(e.confirmed_s, 0)
        feed(0.25, 0, 0.29)
        self.assertEqual(e.confirmed_s, 0)
        for tick in range(25):
            feed(0.26 + tick * 0.01, 0, 0.30)
        self.assertEqual(e.state, "CONTACT_STOP")

    def test_stop_confirmation_is_continuous(self):
        e = BaselineController(self.profile, SimRecipe())
        e.enter("CONTACT_STOP", 0)
        for tick in range(14):
            e.app_step(Sample(tick * 0.01, 180, 0, 0, 0, 0), tick * 0.01, 0.01)
        self.assertEqual(e.state, "CONTACT_STOP")
        e.app_step(Sample(0.14, 180, 3, 3, 0, 0), 0.14, 0.01)
        self.assertEqual(e.confirmed_s, 0)
        for tick in range(15):
            now = 0.15 + tick * 0.01
            e.app_step(Sample(now, 180, 0, 0, 0, 0), now, 0.01)
        self.assertEqual(e.state, "SEATING_IQ")

    def test_baseline_timed_stages_and_process_completion(self):
        e = BaselineController(self.profile, SimRecipe())
        e.enter("SEATING_IQ", 0)
        e.contact_deg = 180
        s = Sample(0, 180, 0, 0, 0, 0)
        for now, state in ((0.30, "TIGHTEN_010"), (0.60, "TIGHTEN_012"), (0.90, "TIGHTEN_015"), (1.20, "HOLD"), (1.70, "PROCESS_OK")):
            e.app_step(s, now, 0.01)
            self.assertEqual(e.state, state)
        self.assertEqual(e.request_a, 0)

    def test_abort_has_priority_over_stage_completion(self):
        e = BaselineController(self.profile, SimRecipe())
        e.enter("HOLD", 0)
        e.app_step(Sample(0.5, 180, 30, 30, 0, 0), 0.5, 0.01)
        self.assertEqual(e.outcome, "ABORT")

    def test_timeout_and_travel_limits(self):
        for sample, now in ((Sample(8, 0, 80, 80, 0, 0), 8), (Sample(1, 3000, 80, 80, 0, 0), 1)):
            e = BaselineController(self.profile, SimRecipe())
            e.app_step(sample, now, 0.01)
            self.assertEqual(e.outcome, "RUNDOWN_TIMEOUT")
        e.enter("CONTACT_STOP", 0)
        e.outcome = None
        e.app_step(Sample(2, 180, 3, 3, 0, 0), 2, 0.01)
        self.assertEqual(e.outcome, "STOP_TIMEOUT")

    def test_pi_does_not_wind_up_into_saturation(self):
        pi = SpeedPI(0.003, 0.02)
        for _ in range(10000):
            self.assertLessEqual(abs(pi.step(1000, 0, 0.001, 0.15)), 0.15)
        self.assertEqual(pi.integral, 0)

    def test_feedback_angle_rejects_early_contact(self):
        e = FeedbackController(self.profile, SimRecipe())
        e.app_step(Sample(1, 10, 0, 0, 0, 0.0003), 1, 0.01)
        self.assertEqual(e.outcome, "ANGLE_REJECT")

    def test_over_torque_priority_and_no_restart(self):
        e = FeedbackController(self.profile, SimRecipe())
        e.enter("TORQUE", 0)
        e.app_step(Sample(1, 180, 0, 0, 0, 0.0022), 1, 0.01)
        self.assertEqual(e.outcome, "OVERTORQUE")
        self.assertEqual(e.fast_step(Sample(2, 180, 0, 0, 0, 0.002), 2, 0.001), 0)

    def test_unreachable_target_is_rejected_without_larger_current(self):
        r = simulate(self.profile, sim_recipe=replace(SimRecipe(), target_nm=0.20), controller="feedback")
        self.assertEqual(r.outcome, "TARGET_UNREACHABLE")
        self.assertEqual(r.max_command_a, 0)

    def test_stop_fault_and_stale_cancel_delayed_commands(self):
        for a, outcome in ((Assumptions(stop_s=0.4), "STOPPED"), (Assumptions(injected_fault_s=0.4), "FAULT_INJECTED"), (Assumptions(feedback_dropout_s=0.4), "FEEDBACK_STALE")):
            for mode in ("baseline", "feedback"):
                r = simulate(self.profile, a, controller=mode)
                self.assertEqual(r.outcome, outcome)
                self.assertEqual(r.terminal_command_a, 0)
                self.assertTrue(all(row["iq_command_a"] == 0 for row in r.trace if row["time_s"] >= r.elapsed_s + 0.001))

    def test_excessive_delay_is_not_accepted_as_fresh_feedback(self):
        r = simulate(self.profile, replace(Assumptions(), feedback_delay_ms=40), controller="feedback")
        self.assertEqual(r.outcome, "FEEDBACK_STALE")

    def test_no_joint_never_becomes_torque_success(self):
        for mode in ("baseline", "feedback"):
            r = simulate(self.profile, replace(Assumptions(), has_joint=False), controller=mode)
            self.assertEqual(r.outcome, "RUNDOWN_TIMEOUT")
            self.assertFalse(r.truth_within_demo_band)

    def test_process_ok_is_not_a_torque_certificate(self):
        r = simulate(self.profile)
        self.assertEqual(r.outcome, "PROCESS_OK")
        self.assertFalse(r.truth_within_demo_band)
        self.assertFalse(r.quality_claim_allowed)

    def test_nominal_virtual_feedback_meets_only_the_demo_band(self):
        for stiffness in (0.20, 0.010):
            r = simulate(self.profile, Assumptions(stiffness_nm_per_rad=stiffness), controller="feedback")
            self.assertEqual(r.outcome, "MODEL_OK")
            self.assertTrue(r.truth_within_demo_band)
            self.assertFalse(r.quality_claim_allowed)

    def test_sensor_gain_bias_can_create_a_false_model_ok(self):
        r = simulate(self.profile, Assumptions(stiffness_nm_per_rad=0.010, torque_gain=1.10), controller="feedback")
        self.assertEqual(r.outcome, "MODEL_OK")
        self.assertFalse(r.truth_within_demo_band)
        self.assertEqual(aggregate([r])["false_complete_count"], 1)

    def test_stripped_joint_never_gets_model_ok(self):
        r = simulate(self.profile, Assumptions(stiffness_nm_per_rad=0.010, strip_at_nm=0.001), controller="feedback")
        self.assertTrue(r.stripped)
        self.assertNotEqual(r.outcome, "MODEL_OK")
        self.assertEqual(r.terminal_command_a, 0)

    def test_command_limits_apply_to_each_simulated_stage(self):
        for mode in ("baseline", "feedback"):
            r = simulate(self.profile, controller=mode)
            self.assertLessEqual(r.max_command_a, 0.40)
            for row in r.trace:
                if row["state"] not in ("RUNDOWN", "APPROACH"):
                    self.assertLessEqual(abs(row["iq_requested_a"]), 0.15)

    def test_disabled_plant_does_not_apply_sensor_offset_as_drive(self):
        p = Plant(Assumptions(current_offset_a=-0.02))
        p.step(0, 0.001, enabled=False)
        self.assertEqual(p.iq_a, 0)
        self.assertEqual(p.angle_deg, 0)

    def test_timestep_comparison_preserves_outcomes_and_final_values(self):
        rows = numerical_checks(self.profile)
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(row["check_pass"] for row in rows))

    def test_seed_is_reproducible(self):
        a = simulate(self.profile, seed=42, max_s=0.5)
        b = simulate(self.profile, seed=42, max_s=0.5)
        self.assertEqual(a.summary(), b.summary())
        self.assertEqual(a.trace, b.trace)

    def test_plant_has_no_reverse_unloading_by_explicit_assumption(self):
        p = Plant(Assumptions(), theta_rad=math.radians(181))
        before = p.theta_rad
        for _ in range(100):
            p.step(-0.15, 0.0005)
        self.assertEqual(p.theta_rad, before)
        self.assertGreater(p.torque_nm, 0)

    def test_model_rejects_invalid_inputs(self):
        for a in (Assumptions(kt_nm_per_a=0), Assumptions(current_gain=0), Assumptions(inertia_kg_m2=-1), Assumptions(stiffness_nm_per_rad=1e10), Assumptions(torque_noise_nm=-1), Assumptions(torque_offset_nm=float("nan"))):
            with self.assertRaises(ValueError):
                simulate(self.profile, a)
        for dt in (0, -1, float("nan"), 0.002, 0.0007):
            with self.assertRaises(ValueError):
                simulate(self.profile, dt_s=dt)


if __name__ == "__main__":
    unittest.main()
