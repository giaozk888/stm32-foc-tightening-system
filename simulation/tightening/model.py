"""A reduced-order, forward-only tightening model, NOT firmware emulation.

Production recipe defaults/limits are read-only inputs. Motor, joint and sensor
parameters are synthetic assumptions. The feedback controller exists ONLY here.
There is deliberately no serial, CAN, GPIO, SSH, RPC or flash-writing code.
"""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field, replace
import hashlib
import math
from pathlib import Path
import random
import re


ROOT = Path(__file__).resolve().parents[2]
POST_STAGES = ("SEATING_IQ", "TIGHTEN_010", "TIGHTEN_012", "TIGHTEN_015", "HOLD")


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


@dataclass(frozen=True)
class FirmwareProfile:
    recipe: dict[str, int]
    ranges: dict[str, tuple[int, int]]
    constants: dict[str, float]
    hashes: dict[str, str]
    speed_profile: str = "baseline"

    def with_recipe(self, **values: int) -> FirmwareProfile:
        recipe = self.recipe.copy()
        for name, value in values.items():
            if name not in self.ranges:
                raise ValueError(f"Unknown recipe field: {name}")
            low, high = self.ranges[name]
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"Out-of-range recipe field: {name}")
            recipe[name] = value
        return replace(self, recipe=recipe)


def load_firmware_profile(root: Path = ROOT, *, speed_profile: str = "baseline") -> FirmwareProfile:
    """Fail visibly on source drift, never infer live Flash/KVS configuration."""
    relative = "firmware_common/tighten_params.h"
    raw = (root / relative).read_bytes()
    text = raw.decode("utf-8")
    if speed_profile not in ("baseline", "x2-offline"):
        raise ValueError("Unknown speed profile")
    # Read only this explicit two-branch source contract, not a general C
    # preprocessor. Fail on drift rather than silently infer active macros.
    block = re.search(
        r"#if defined\(TIGHTEN_SPEED_X2_OFFLINE\)(.*?)#else(.*?)#endif",
        text, re.S,
    )
    if not block:
        raise ValueError("Missing explicit rundown speed profile")
    values = dict(re.findall(
        r"^#define\s+(TIGHTEN_RUNDOWN_(?:DEFAULT|MAX)_RPM)\s+(\d+)U\s*$",
        block.group(1 if speed_profile == "x2-offline" else 2), re.M,
    ))
    if len(values) != 2:
        raise ValueError("Rundown speed profile constants require review")

    def integer(token):
        if re.fullmatch(r"\d+U", token):
            return int(token[:-1])
        if token in values:
            return int(values[token])
        raise ValueError(f"Unsupported recipe constant: {token}")

    fields = re.findall(
        r'X\((\w+),\s*"[A-Z0-9_]+",\s*(\w+),\s*(\w+),\s*(\w+)\)', text
    )
    if len(fields) != 18 or len({f[0] for f in fields}) != 18:
        raise ValueError("Expected the existing 18-field V1 recipe")
    recipe = {name: integer(default) for name, _, _, default in fields}
    ranges = {name: (integer(low), integer(high)) for name, low, high, _ in fields}
    if any(not ranges[name][0] <= value <= ranges[name][1]
           for name, value in recipe.items()):
        raise ValueError("Recipe source default outside selected profile range")
    names = (
        "MOTOR_SPEED_IQ_LIMIT_A", "MOTOR_DIRECT_IQ_LIMIT_A",
        "TIGHTEN_STOP_MAX_RPM", "TIGHTEN_STOP_CONFIRM_MS", "TIGHTEN_STOP_TIMEOUT_MS",
        "SPEED_KP_A_PER_RPM", "SPEED_KI_A_PER_RPM_S", "FOC_TS_S",
        "MOTOR_SPEED_API_LIMIT_RPM", "SPEED_OVERSPEED_RPM",
        "FOC_CURRENT_TRIP_A", "FOC_VOLTAGE_LIMIT_V",
    )
    hashes = {relative: hashlib.sha256(raw).hexdigest()}
    both = []
    for slot in ("a", "b"):
        relative = f"foc2_app_{slot}/Core/Src/main.c"
        raw = (root / relative).read_bytes()
        source = raw.decode("utf-8")
        constants = {}
        for name in names:
            match = re.search(rf"^#define\s+{name}\s+([0-9.]+)[fU]?\b", source, re.M)
            if not match:
                raise ValueError(f"Missing constant {name} in {relative}")
            constants[name] = float(match.group(1))
        # These are source-drift sentinels, not proof of equivalence to the MCU.
        for sentinel in (
            "case TIGHTEN_STATE_CONTACT_STOP:", "case TIGHTEN_STATE_HOLD:",
            "tightening_contact_candidate_ms += 10U;", "TIGHTEN_OUTCOME_OK;",
            "recipe_state.params.contact_iq_mA", "recipe_state.params.hold_ms",
        ):
            if sentinel not in source:
                raise ValueError(f"State-machine mirror requires review: {sentinel}")
        both.append(constants)
        hashes[relative] = hashlib.sha256(raw).hexdigest()
    if both[0] != both[1]:
        raise ValueError("A/B control constants differ; choose an explicit baseline")
    if not (ranges["rundown_rpm"][1] <= both[0]["MOTOR_SPEED_API_LIMIT_RPM"]
            < both[0]["SPEED_OVERSPEED_RPM"]):
        raise ValueError("Rundown range exceeds unchanged API/overspeed limits")
    return FirmwareProfile(recipe, ranges, both[0], hashes, speed_profile)


@dataclass(frozen=True)
class Assumptions:
    # ALL values below are illustrative, not identified/calibrated motor data.
    kt_nm_per_a: float = 0.020
    inertia_kg_m2: float = 0.000020
    friction_nm: float = 0.00010
    viscous_nm_per_rad_s: float = 0.00005
    current_tau_s: float = 0.001
    seat_deg: float = 180.0
    stiffness_nm_per_rad: float = 0.20
    has_joint: bool = True
    strip_at_nm: float | None = None
    current_gain: float = 1.0
    current_offset_a: float = 0.0
    torque_gain: float = 1.0
    torque_offset_nm: float = 0.0
    torque_noise_nm: float = 0.000003
    encoder_noise_deg: float = 0.0
    feedback_delay_ms: float = 2.0
    command_delay_ms: float = 1.0
    feedback_dropout_s: float | None = None
    injected_fault_s: float | None = None
    stop_s: float | None = None

    def validate(self) -> None:
        for name, value in asdict(self).items():
            if isinstance(value, (float, int)) and not math.isfinite(value):
                raise ValueError(f"Nonfinite model input: {name}")
        for name in ("kt_nm_per_a", "inertia_kg_m2", "current_tau_s", "current_gain"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        for name in (
            "friction_nm", "viscous_nm_per_rad_s", "seat_deg", "stiffness_nm_per_rad",
            "torque_noise_nm", "encoder_noise_deg", "feedback_delay_ms", "command_delay_ms",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be nonnegative")
        if self.torque_gain <= 0:
            raise ValueError("torque_gain must be positive")
        for name in ("strip_at_nm", "feedback_dropout_s", "injected_fault_s", "stop_s"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} must be nonnegative")


@dataclass(frozen=True)
class SimRecipe:
    # A model-only target, not an industrial requirement or a board setting.
    target_nm: float = 0.002
    tolerance_fraction: float = 0.05
    assumed_kt_nm_per_a: float = 0.020
    approach_start_deg: float = 120.0
    expected_seat_min_deg: float = 150.0
    expected_seat_max_deg: float = 210.0
    approach_rpm: float = 2.0
    stable_ms: float = 150.0
    final_timeout_ms: float = 5000.0
    feedback_watchdog_ms: float = 30.0

    def validate(self) -> None:
        if not all(math.isfinite(v) for v in asdict(self).values()):
            raise ValueError("Nonfinite simulation recipe")
        if self.target_nm <= 0 or not 0 < self.tolerance_fraction < 1:
            raise ValueError("Invalid target/tolerance")
        if not 0 <= self.approach_start_deg < self.expected_seat_min_deg < self.expected_seat_max_deg:
            raise ValueError("Invalid synthetic fixture angle window")
        for name in ("assumed_kt_nm_per_a", "approach_rpm", "stable_ms", "final_timeout_ms", "feedback_watchdog_ms"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")


@dataclass
class Plant:
    assumptions: Assumptions
    theta_rad: float = 0.0
    omega_rad_s: float = 0.0
    iq_a: float = 0.0
    stripped: bool = False

    @property
    def angle_deg(self) -> float:
        return math.degrees(self.theta_rad)

    @property
    def rpm(self) -> float:
        return self.omega_rad_s * 60 / (2 * math.pi)

    @property
    def torque_nm(self) -> float:
        a = self.assumptions
        if not a.has_joint or self.stripped:
            return 0.0
        return a.stiffness_nm_per_rad * max(0.0, self.theta_rad - math.radians(a.seat_deg))

    def step(self, requested_iq_a: float, dt: float, enabled: bool = True) -> None:
        a = self.assumptions
        # Reduced current-loop response. NOT the production dq PI/SVPWM code.
        iq_equilibrium = (
            (requested_iq_a - a.current_offset_a) / a.current_gain if enabled else 0.0
        )
        self.iq_a += (iq_equilibrium - self.iq_a) * (-math.expm1(-dt / a.current_tau_s))
        motor_torque = a.kt_nm_per_a * self.iq_a
        resistance = self.torque_nm + a.friction_nm + a.viscous_nm_per_rad_s * self.omega_rad_s
        self.omega_rad_s = max(0.0, self.omega_rad_s + (motor_torque - resistance) * dt / a.inertia_kg_m2)
        # Explicit forward-only/self-locking assumption: no thread relaxation,
        # elastic reverse travel, backlash or screw clamp-force calculation.
        self.theta_rad += self.omega_rad_s * dt
        if a.strip_at_nm is not None and self.torque_nm >= a.strip_at_nm:
            self.stripped = True


@dataclass(frozen=True)
class Sample:
    time_s: float
    angle_deg: float
    rpm: float
    detect_rpm: float
    iq_a: float
    torque_nm: float


@dataclass
class SpeedPI:
    kp: float
    ki: float
    integral: float = 0.0

    def step(self, reference: float, actual: float, dt: float, limit: float) -> float:
        error = reference - actual
        candidate = self.integral + self.ki * error * dt
        unsaturated = self.kp * error + candidate
        output = clamp(unsaturated, -limit, limit)
        if output == unsaturated or (output >= limit and error < 0) or (output <= -limit and error > 0):
            self.integral = candidate
        return output


@dataclass
class Controller:
    profile: FirmwareProfile
    sim_recipe: SimRecipe
    state: str = "RUNDOWN"
    outcome: str | None = None
    stage_start_s: float = 0.0
    contact_deg: float = 0.0
    confirmed_s: float = 0.0
    request_a: float = 0.0
    drive_request_a: float = 0.0
    events: list[dict] = field(default_factory=list)
    pi: SpeedPI = field(init=False)

    def __post_init__(self) -> None:
        c = self.profile.constants
        self.pi = SpeedPI(c["SPEED_KP_A_PER_RPM"], c["SPEED_KI_A_PER_RPM_S"])
        self.events.append({"time_s": 0.0, "state": self.state})

    def enter(self, state: str, now: float) -> None:
        self.state = state
        self.stage_start_s = now
        self.confirmed_s = 0.0
        self.events.append({"time_s": round(now, 6), "state": state})

    def finish(self, outcome: str, now: float) -> None:
        self.outcome = outcome
        self.request_a = self.drive_request_a = 0.0
        self.pi.integral = 0.0
        self.enter(outcome, now)

    def fast_step(self, sample: Sample, now: float, dt: float) -> float:
        raise NotImplementedError

    def app_step(self, sample: Sample, now: float, dt: float) -> None:
        raise NotImplementedError


class BaselineController(Controller):
    """Behavioral mirror of the current 100 Hz application stage decisions.

    Excludes START admission/session, full MCU speed estimator, RTOS scheduling,
    speed ramp and actual FOC implementation. Never call this firmware-in-loop.
    """

    def fast_step(self, sample: Sample, now: float, dt: float) -> float:
        if self.outcome is not None:
            return 0.0
        if self.state == "RUNDOWN":
            self.request_a = self.pi.step(self.profile.recipe["rundown_rpm"], sample.rpm, dt, self.profile.constants["MOTOR_SPEED_IQ_LIMIT_A"])
        elif self.state in POST_STAGES:
            field_name = ("seating_iq_mA", "t1_iq_mA", "t2_iq_mA", "t3_iq_mA", "hold_iq_mA")[POST_STAGES.index(self.state)]
            self.request_a = min(self.profile.recipe[field_name] / 1000, self.profile.constants["MOTOR_DIRECT_IQ_LIMIT_A"])
        else:
            self.request_a = 0.0
            self.pi.integral = 0.0
        self.drive_request_a = self.request_a
        return self.request_a

    def app_step(self, sample: Sample, now: float, dt: float) -> None:
        if self.outcome is not None:
            return
        p, c = self.profile.recipe, self.profile.constants
        elapsed_ms = (now - self.stage_start_s) * 1000
        if self.state == "RUNDOWN":
            contact = abs(sample.detect_rpm) <= p["contact_rpm"] and self.drive_request_a >= p["contact_iq_mA"] / 1000
            self.confirmed_s = self.confirmed_s + dt if contact else 0.0
            if self.confirmed_s * 1000 + 1e-7 >= p["contact_ms"]:
                self.contact_deg = sample.angle_deg
                self.enter("CONTACT_STOP", now)
            elif elapsed_ms + 1e-7 >= p["rundown_timeout_ms"] or abs(sample.angle_deg) >= p["max_travel_deg"]:
                self.finish("RUNDOWN_TIMEOUT", now)
        elif self.state == "CONTACT_STOP":
            self.confirmed_s = self.confirmed_s + dt if abs(sample.rpm) <= c["TIGHTEN_STOP_MAX_RPM"] else 0.0
            if self.confirmed_s * 1000 + 1e-7 >= c["TIGHTEN_STOP_CONFIRM_MS"]:
                self.enter("SEATING_IQ", now)
            elif elapsed_ms + 1e-7 >= c["TIGHTEN_STOP_TIMEOUT_MS"]:
                self.finish("STOP_TIMEOUT", now)
        elif self.state in POST_STAGES:
            if abs(sample.rpm) >= p["torque_abort_rpm"] or abs(sample.angle_deg - self.contact_deg) >= p["post_travel_max_deg"]:
                self.finish("ABORT", now)
                return
            index = POST_STAGES.index(self.state)
            duration = ("seating_ms", "t1_ms", "t2_ms", "t3_ms", "hold_ms")[index]
            if elapsed_ms + 1e-7 >= p[duration]:
                if index == len(POST_STAGES) - 1:
                    self.finish("PROCESS_OK", now)  # Firmware OK is process completion.
                else:
                    self.enter(POST_STAGES[index + 1], now)


class FeedbackController(Controller):
    """Simulation-only torque feedback + slow approach + angle qualification.

    Assumes a virtual joint torque sensor AND a known fixture seating window.
    NOT available on the user's board and NOT a calibrated Iq torque observer.
    """

    def __post_init__(self) -> None:
        super().__post_init__()
        limit = self.profile.constants["MOTOR_DIRECT_IQ_LIMIT_A"]
        if self.sim_recipe.target_nm > limit * self.sim_recipe.assumed_kt_nm_per_a:
            self.finish("TARGET_UNREACHABLE", 0.0)

    def fast_step(self, sample: Sample, now: float, dt: float) -> float:
        if self.outcome is not None:
            return 0.0
        r = self.sim_recipe
        if self.state == "RUNDOWN":
            rpm = self.profile.recipe["rundown_rpm"]
            limit = self.profile.constants["MOTOR_SPEED_IQ_LIMIT_A"]
        else:
            rpm = r.approach_rpm
            limit = self.profile.constants["MOTOR_DIRECT_IQ_LIMIT_A"]
            if self.state == "TORQUE":
                # Positive torque error sets a low speed; speed PI supplies Iq.
                # No use of the plant's hidden true torque in control decisions.
                error = r.target_nm - sample.torque_nm
                rpm = clamp(error / r.target_nm * r.approach_rpm * 3, 0.0, r.approach_rpm)
        self.request_a = self.pi.step(rpm, sample.rpm, dt, limit)
        self.drive_request_a = self.request_a
        return self.request_a

    def app_step(self, sample: Sample, now: float, dt: float) -> None:
        if self.outcome is not None:
            return
        r, p = self.sim_recipe, self.profile.recipe
        low, high = r.target_nm * (1 - r.tolerance_fraction), r.target_nm * (1 + r.tolerance_fraction)
        if sample.torque_nm > high:
            self.finish("OVERTORQUE", now)
            return
        if self.state in ("RUNDOWN", "APPROACH"):
            if sample.torque_nm >= r.target_nm * 0.10:
                if not r.expected_seat_min_deg <= sample.angle_deg <= r.expected_seat_max_deg:
                    self.finish("ANGLE_REJECT", now)
                    return
                self.contact_deg = sample.angle_deg
                self.enter("TORQUE", now)
            elif self.state == "RUNDOWN" and sample.angle_deg >= r.approach_start_deg:
                # Preserve integrator for braking, but cap it to the smaller
                # final-stage authority instead of carrying 0.4 A into contact.
                limit = self.profile.constants["MOTOR_DIRECT_IQ_LIMIT_A"]
                self.pi.integral = clamp(self.pi.integral, -limit, limit)
                self.enter("APPROACH", now)
            elif now * 1000 >= p["rundown_timeout_ms"] or sample.angle_deg >= p["max_travel_deg"]:
                self.finish("RUNDOWN_TIMEOUT", now)
        elif self.state == "TORQUE":
            if sample.angle_deg - self.contact_deg >= p["post_travel_max_deg"] or abs(sample.rpm) >= p["torque_abort_rpm"]:
                self.finish("ABORT", now)
                return
            good = low <= sample.torque_nm <= high and abs(sample.rpm) <= r.approach_rpm
            self.confirmed_s = self.confirmed_s + dt if good else 0.0
            if self.confirmed_s * 1000 + 1e-7 >= r.stable_ms:
                self.finish("MODEL_OK", now)
            elif (now - self.stage_start_s) * 1000 >= r.final_timeout_ms:
                self.finish("TORQUE_TIMEOUT", now)


@dataclass
class Result:
    controller: str
    seed: int
    outcome: str
    elapsed_s: float
    final_true_torque_nm: float
    peak_true_torque_nm: float
    target_nm: float
    final_error_percent: float
    peak_overshoot_percent: float
    truth_within_demo_band: bool
    quality_claim_allowed: bool
    max_command_a: float
    terminal_command_a: float
    stripped: bool
    events: list[dict]
    assumptions: dict
    simulation_recipe: dict
    trace: list[dict]

    def summary(self) -> dict:
        return {key: value for key, value in asdict(self).items() if key != "trace"}


def simulate(
    profile: FirmwareProfile,
    assumptions: Assumptions = Assumptions(),
    sim_recipe: SimRecipe = SimRecipe(),
    controller: str = "baseline",
    seed: int = 1,
    dt_s: float = 0.0005,
    max_s: float = 16.0,
    keep_trace: bool = True,
) -> Result:
    assumptions.validate()
    sim_recipe.validate()
    if not math.isfinite(dt_s) or not 0 < dt_s <= 0.001:
        raise ValueError("Plant timestep must be finite, >0 and <=1 ms")
    if abs(round(0.001 / dt_s) * dt_s - 0.001) > 1e-10:
        raise ValueError("Timestep must exactly divide the 1 ms control period")
    natural_frequency = math.sqrt(
        assumptions.stiffness_nm_per_rad / assumptions.inertia_kg_m2
    )
    if not math.isfinite(natural_frequency) or dt_s * natural_frequency > 0.2:
        raise ValueError("Use a smaller timestep for this stiffness/inertia")
    if not math.isfinite(max_s) or max_s <= 0:
        raise ValueError("Invalid simulation duration")
    classes = {"baseline": BaselineController, "feedback": FeedbackController}
    if controller not in classes:
        raise ValueError("Unknown controller; hardware adapters are not supported")
    engine = classes[controller](profile, sim_recipe)
    plant, rng = Plant(assumptions), random.Random(seed)
    initial = Sample(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    history = deque([initial])
    commands = deque()
    detector = deque(maxlen=50)
    latest = initial
    delivered = applied = max_command = peak = 0.0
    done_at = 0.0 if engine.outcome is not None else None
    trace = []
    fast_period = round(0.001 / dt_s)
    app_period = round(0.010 / dt_s)
    trace_period = round(0.005 / dt_s)
    for tick in range(round(max_s / dt_s) + 1):
        now = tick * dt_s
        if tick % fast_period == 0:
            if assumptions.feedback_dropout_s is None or now < assumptions.feedback_dropout_s:
                angle = round((plant.angle_deg + rng.gauss(0, assumptions.encoder_noise_deg)) / (360 / 16384)) * (360 / 16384)
                detector.append(plant.rpm)
                sample = Sample(now, angle, plant.rpm, sum(detector) / len(detector), plant.iq_a * assumptions.current_gain + assumptions.current_offset_a, plant.torque_nm * assumptions.torque_gain + assumptions.torque_offset_nm + rng.gauss(0, assumptions.torque_noise_nm))
                history.append(sample)
            while len(history) > 1 and history[1].time_s <= now - assumptions.feedback_delay_ms / 1000 + 1e-10:
                history.popleft()
            latest = history[0]
            if engine.outcome is None:
                # Faults are synthetic inputs at the observer boundary. This
                # does not prove production fault detection/watchdog latency.
                if assumptions.injected_fault_s is not None and now >= assumptions.injected_fault_s:
                    engine.finish("FAULT_INJECTED", now)
                elif assumptions.stop_s is not None and now >= assumptions.stop_s:
                    engine.finish("STOPPED", now)
                elif now - latest.time_s > sim_recipe.feedback_watchdog_ms / 1000:
                    engine.finish("FEEDBACK_STALE", now)
                elif not all(math.isfinite(value) for value in asdict(latest).values()):
                    engine.finish("FEEDBACK_INVALID", now)
            if engine.outcome is None and tick % app_period == 0:
                engine.app_step(latest, now, 0.010)
            request = engine.fast_step(latest, now, 0.001)
            max_command = max(max_command, abs(request))
            if engine.outcome is not None:
                # Cancel delayed commands on termination; coil current still
                # decays in Plant.step. No automatic restart is modeled.
                commands.clear()
                applied = request = 0.0
                if done_at is None:
                    done_at = now
            else:
                commands.append((now + assumptions.command_delay_ms / 1000, request))
        while commands and commands[0][0] <= now + 1e-10:
            _, applied = commands.popleft()
        delivered = applied
        plant.step(
            delivered, dt_s,
            enabled=engine.outcome is None and engine.state != "CONTACT_STOP",
        )
        peak = max(peak, plant.torque_nm)
        if keep_trace and tick % trace_period == 0:
            trace.append({"time_s": round(now, 6), "state": engine.state, "angle_deg": plant.angle_deg, "rpm": plant.rpm, "iq_requested_a": engine.request_a, "iq_command_a": delivered, "iq_true_a": plant.iq_a, "torque_true_nm": plant.torque_nm, "torque_measured_nm": latest.torque_nm})
        if done_at is not None and now - done_at >= 0.25:
            break
    if engine.outcome is None:
        engine.finish("SIMULATION_TIMEOUT", now)
        delivered = 0.0
        done_at = now
    final = plant.torque_nm
    low = sim_recipe.target_nm * (1 - sim_recipe.tolerance_fraction)
    high = sim_recipe.target_nm * (1 + sim_recipe.tolerance_fraction)
    truth_good = low <= final <= high and peak <= high and not plant.stripped
    return Result(
        controller, seed, engine.outcome, done_at, final, peak, sim_recipe.target_nm,
        (final / sim_recipe.target_nm - 1) * 100,
        max(0.0, peak / sim_recipe.target_nm - 1) * 100,
        truth_good, False, max_command, delivered, plant.stripped, engine.events,
        asdict(assumptions), asdict(sim_recipe), trace,
    )
