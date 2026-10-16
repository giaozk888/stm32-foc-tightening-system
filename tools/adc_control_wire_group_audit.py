"""Offline GPIO-low control-wire comparison; retain all samples, no hardware calls."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from adc_control_pins_low_acceptance import PINNED, pinned_image
from adc_control_pins_low_restart import prior_identity
from adc_reference_report import analyze
from adc_control_pins_low_sample import single_control_description


def single_wiring_matches(description, wiring, control):
    expected = {s: "disconnected" if s == control else "connected"
                for s in ("UH", "VH", "WH", "UL", "VL", "WL")}
    return (description == single_control_description(control) and
            wiring.get("per_control_wire") == expected and
            wiring.get("disconnected_control") == control and
            wiring.get("common_ground") == "unchanged" and
            wiring.get("UH_VH_WH") == "connected" and wiring.get("UL_VL_WL") == "mixed")


def audit(deployment, capture_path, readback_path):
    capture = json.loads(capture_path.read_text(encoding="utf-8"))
    readback = json.loads(readback_path.read_text(encoding="utf-8"))
    slot, generation, crc, power = prior_identity(deployment, capture, readback)
    raw = readback_path.with_suffix(".raw.bin").read_bytes()
    if len(raw) != 24576 or hashlib.sha256(raw).hexdigest() != readback["raw_sha256"]:
        raise RuntimeError("Saved independent RAM binary identity mismatch")
    values = struct.unpack("<12288H", raw)
    triples = [list(t) for t in zip(values[:4096], values[4096:8192], values[8192:])]
    if triples != capture["triples"]:
        raise RuntimeError("Saved RAM binary differs from full UART values")
    image = readback_path.with_suffix(".active-code.bin").read_bytes()
    if image != pinned_image(slot)[1] or hashlib.sha256(image).hexdigest() != PINNED[slot]:
        raise RuntimeError("Saved full active image differs from pinned A")
    events = [{"index": i, "U": t[0], "V": t[1],
               "previous": triples[i - 1] if i else None,
               "next": triples[i + 1] if i + 1 < 4096 else None}
              for i, t in enumerate(triples) if t[0] or t[1]]
    return {"slot": slot, "generation": generation, "power": power, "crc32": crc,
            "all": analyze(triples), "nonzero_events": events,
            "paired_nonzero_count": sum(t[0] > 0 and t[1] > 0 for t in triples),
            "common_strictly_above_20": sum(t[0] > 20 and t[1] > 20 for t in triples),
            "raw_uart_ram_match": True, "all_samples_retained": True, "filtering": False,
            "capture": str(capture_path), "readback": str(readback_path),
            "wiring_record": capture.get("raw_mapping", {}).get("CONTROL_WIRING_USER_CONFIRMED",
                        "All six connected per prior user condition; not independently traced")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("deployment", "baseline", "baseline-readback", "group", "group-readback", "reset", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    wiring = parser.add_mutually_exclusive_group()
    wiring.add_argument("--disconnected-group", choices=("upper", "lower"), default="upper")
    wiring.add_argument("--all-six-connected", action="store_true")
    wiring.add_argument("--only-disconnected-control", choices=("UL", "VL", "WL"))
    parser.add_argument("--prior-capture", type=Path)
    parser.add_argument("--prior-readback", type=Path)
    args = parser.parse_args()
    deployment = json.loads(args.deployment.read_text(encoding="utf-8"))
    baseline = audit(deployment, args.baseline, args.baseline_readback)
    group = audit(deployment, args.group, args.group_readback)
    if bool(args.prior_capture) != bool(args.prior_readback):
        parser.error("Prior capture and readback must be provided together")
    prior = (audit(deployment, args.prior_capture, args.prior_readback)
             if args.prior_capture else baseline)
    reset = json.loads(args.reset.read_text(encoding="utf-8"))
    upper = args.disconnected_group == "upper"
    disconnected = "UH/VH/WH" if upper else "UL/VL/WL"
    connected = "UL/VL/WL" if upper else "UH/VH/WH"
    if args.only_disconnected_control:
        control = args.only_disconnected_control
        record_matches = single_wiring_matches(group["wiring_record"], reset.get("wiring_user_confirmed", {}), control)
        reset_wire_matches = record_matches
    elif args.all_six_connected:
        record_matches = all(s + " connected" in group["wiring_record"] for s in ("UH/VH/WH", "UL/VL/WL"))
        reset_wire_matches = all(reset.get("wiring_user_confirmed", {}).get(s) == "connected"
                                 for s in ("UH_VH_WH", "UL_VL_WL"))
    else:
        record_matches = (disconnected + " disconnected" in group["wiring_record"] and
                          connected + " connected" in group["wiring_record"])
        reset_wire_matches = (reset.get("wiring_user_confirmed", {}).get(disconnected.replace("/", "_")) == "disconnected" and
                              reset.get("wiring_user_confirmed", {}).get(connected.replace("/", "_")) == "connected")
    prior_capture_path = args.prior_capture or args.baseline
    prior_readback_path = args.prior_readback or args.baseline_readback
    if (baseline["generation"] != group["generation"] or prior["generation"] != group["generation"] or
            not record_matches or not reset_wire_matches or
            reset.get("pass") is not True or reset.get("reset_commands") != 1 or
            reset.get("sample_commands") != 0 or reset.get("before_raw", {}).get("CRC") != prior["crc32"] or
            Path(reset.get("prior_capture", "")).resolve() != prior_capture_path.resolve() or
            Path(reset.get("prior_readback", "")).resolve() != prior_readback_path.resolve() or
            reset.get("before_fw", {}).get("GEN") != group["generation"] or
            reset.get("after_fw", {}).get("GEN") != group["generation"] or
            reset.get("before_image_sha256") != PINNED["A"] or
            reset.get("after_image_sha256") != PINNED["A"] or
            any(reset.get(k) is not False for k in ("flash_write", "target_ram_write", "halt", "motion_commands", "thresholds_changed")) or
            reset.get("drive_12v_off_user_confirmed") is not True):
        raise RuntimeError("Same-image group wiring/reset chain required")
    key = "all_six_connected_repeat" if args.all_six_connected else args.disconnected_group + "_three_disconnected"
    if args.only_disconnected_control:
        key = "only_" + args.only_disconnected_control + "_disconnected"
    result = {"pass": True, "all_six_connected": baseline, key: group,
              "preserved_immediately_prior_batch": prior,
              "same_image_sha256": PINNED["A"], "same_generation": True,
              "reset_evidence": str(args.reset), "short_different_boots_not_failure_rate_measurement": True,
              "physical_12v_closed_after_capture_confirmed": False,
              "causal_root_cause_proven": False, "current_feedback_qualified": False,
              "industrial_qualification": False, "reset": False, "hardware_calls": False,
              "conclusion": (
                  "All-connected repeat is one additional short window, not a causal mechanism or failure-rate qualification; retain all deviations"
                  if args.all_six_connected else
                  "Selected-group removal did not eliminate observed paired raw outlier in this one window; other group/common paths remain; no exclusive EMI or single-wire diagnosis"
                  if group["common_strictly_above_20"] else
                  "No pair with BOTH channels strictly >20 counts in this window; any smaller nonzero deviations retained, not evidence of elimination; no reliable failure-rate or causal diagnosis")}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"pass": True, "baseline_crc": baseline["crc32"], "group_crc": group["crc32"],
                      "baseline_events": baseline["nonzero_events"], "group_events": group["nonzero_events"]},
                     ensure_ascii=False), flush=True)


if __name__ == "__main__": main()
