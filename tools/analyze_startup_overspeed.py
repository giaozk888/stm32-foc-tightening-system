"""Offline evidence arithmetic only; no serial, debugger, reset or motor I/O.

The scalar RL experiment is a hypothetical sensitivity check, NOT a replay
of motor physics and NOT a diagnosis of the actual wiring polarity.
"""
import argparse
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / 'safety_backups/protected-closed-loop-20261014/startup-closed-loop-trial-1792065859172936800.json'


def triple(row, key, scale=1.0):
    values = [float(x) / scale for x in row[key].split(',')]
    if len(values) != 3 or not all(math.isfinite(x) for x in values):
        raise ValueError(key)
    return values


def delta14(new, old):
    return (new - old + 8192) % 16384 - 8192


def rpm_bounds(value):
    # FocStartup_Scaled casts x*10 to long: truncation, NOT rounding.
    if value > 0:
        return value, value + .1
    if value < 0:
        return value - .1, value
    return -.1, .1


def analyze(receipt):
    frames = receipt['startup_frames']
    summary = receipt['startup_trace']
    if summary['FROZEN'] != '1' or len(frames) != int(summary['N']) or len(frames) < 2:
        raise ValueError('Need complete frozen startup frames')
    instant_errors, speed_errors, lpf_consistent = [], [], []
    for previous, current in zip(frames, frames[1:]):
        dt = (int(current['ENC_US']) - int(previous['ENC_US'])) * 1e-6
        if not 0 < dt <= .1:
            raise ValueError('Invalid adjacent encoder timestamp')
        new, old = int(current['RAW'].split(',')[0]), int(previous['RAW'].split(',')[0])
        predicted_instant = -delta14(new, old) * 60 / (16384 * dt)
        _, instant, speed = triple(current, 'RPM10', 10)
        old_speed = triple(previous, 'RPM10', 10)[2]
        predicted_speed = old_speed + dt / (.020 + dt) * (instant - old_speed)
        instant_errors.append(abs(predicted_instant - instant))
        speed_errors.append(abs(predicted_speed - speed))
        alpha = dt / (.020 + dt)
        old_lo, old_hi = rpm_bounds(old_speed)
        inst_lo, inst_hi = rpm_bounds(instant)
        new_lo, new_hi = rpm_bounds(speed)
        pred_lo = (1-alpha)*old_lo + alpha*inst_lo
        pred_hi = (1-alpha)*old_hi + alpha*inst_hi
        lpf_consistent.append(max(pred_lo, new_lo) <= min(pred_hi, new_hi) + 1e-6)
    # Contiguous low-speed interval: rotor motion is small, before runaway.
    early = [f for f in frames if 11800 <= int(f['US']) <= 20900]
    if len(early) < 3:
        raise ValueError('Need early low-speed interval')
    early_values = []
    for frame in early:
        iq_ref, id_a, iq_a = triple(frame, 'MA', 1000)
        vd, vq = [float(x) / 1000 for x in frame['MV'].split(',')]
        early_values.append(dict(us=int(frame['US']), id_A=id_a, iq_A=iq_a,
                                 iq_ref_A=iq_ref, vd_V=vd, vq_V=vq))
    # Do not treat sparse/asynchronous outer snapshots as a fitted plant model.
    first, last = frames[0], frames[-1]
    raw_change = -delta14(int(last['RAW'].split(',')[0]), int(first['RAW'].split(',')[0]))
    return dict(
        frame_count=len(frames), first_fault_us=int(receipt['first_fault']['US']),
        first_flags=int(summary['FIRST_FLAGS']),
        encoder_delta_counts=raw_change, encoder_delta_degrees=raw_change*360/16384,
        adjacent_instant_max_discrepancy_rpm=max(instant_errors),
        lpf_max_discrepancy_rpm=max(speed_errors),
        lpf_all_intervals_consistent_with_truncated_format=all(lpf_consistent),
        early_low_speed_interval=early_values,
        all_early_id_positive_vd_negative=all(f['id_A'] > 0 and f['vd_V'] < 0 for f in early_values),
        all_early_iq_negative_vq_positive=all(f['iq_A'] < 0 and f['vq_V'] > 0 for f in early_values),
        warning='Sparse mixed-age software snapshots; not independent speed/current measurements or unique root cause')


def hypothetical_rl(measurement_sign=1, delay_samples=1):
    """One axis, zero reference, ideal RL, 1 mA sensor offset, 30 ms.

    Constants mirror main.c (R/L are comment estimates, not identified plant).
    Exact-ZOH RL integration avoids Euler instability; one sample output queue
    plus configurable measurement delay. No rotor, PWM/deadtime or ADC model.
    """
    if measurement_sign not in (-1, 1) or delay_samples not in (1, 2, 3):
        raise ValueError('Hypothesis out of scope')
    ts, r, l, kp, ki = .00005, .1, 42.3e-6, .08, 188.
    decay = math.exp(-r * ts / l)
    history = [0.] * delay_samples
    current = integral = applied = peak = 0.
    saturated = 0
    for _ in range(600):
        current = decay * current + (1-decay) / r * applied
        history.append(measurement_sign * current + .001)
        error = -history.pop(0)
        integral = max(-.75, min(.75, integral + ki * error * ts))
        requested = kp * error + integral
        applied = max(-.8, min(.8, requested))
        if applied != requested:
            saturated += 1
            integral = max(-.75, min(.75, applied - kp * error))
        peak = max(peak, abs(current))
    return dict(measurement_sign=measurement_sign, delay_samples=delay_samples,
                peak_current_A=peak, final_current_A=current, final_voltage_V=applied,
                saturated_steps=saturated,
                warning='Hypothetical ideal scalar RL only; not physical acceptance')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt', type=Path, default=RECEIPT)
    args = parser.parse_args()
    result = analyze(json.loads(args.receipt.read_text('utf-8')))
    result['hypothetical_rl'] = [hypothetical_rl(sign, delay) for sign in (1, -1) for delay in (1, 2, 3)]
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
