"""Measure two digital PWM channels from a saved sigrok session, not registers.

Uses the file's samplerate, counts complete cycles, and checks sampled overlap
and both-low commutation gaps. Digital samples do not qualify gate waveforms,
analog current settling, sub-sample glitches, or loaded FOC operation.
"""
from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import re
import statistics
import zipfile
from pathlib import Path

RUNS = re.compile(b"\x00+|\x01+|\x02+|\x03+")


def samplerate(text):
    match = re.fullmatch(r"\s*([\d.]+)\s*([kMG]?)Hz\s*", text)
    if not match:
        raise ValueError(f"Unsupported samplerate: {text}")
    value = float(match[1]) * {"": 1, "k": 1e3, "M": 1e6, "G": 1e9}[match[2]]
    if value <= 0:
        raise ValueError("Invalid samplerate")
    return value


def stats(values, scale=1):
    return {"count": len(values), "min": min(values) * scale,
            "max": max(values) * scale, "mean": statistics.mean(values) * scale,
            "median": statistics.median(values) * scale} if values else None


class Analyzer:
    def __init__(self, rate):
        self.rate = rate
        self.total = 0
        self.state = None
        self.state_start = 0
        self.pending_gap_source = None
        self.overlap_samples = 0
        self.max_overlap_samples = 0
        self.gaps = {"0_to_1": [], "1_to_0": []}
        self.channels = [{"last_rise": None, "fall": None, "periods": [], "highs": [],
                          "rises": 0, "falls": 0} for _ in range(2)]

    def change(self, position, new_state):
        old = self.state
        if old is None:
            self.state = new_state
            self.state_start = position
            return
        if old == new_state:
            return
        run_length = position - self.state_start
        if old == 3:
            self.overlap_samples += run_length
            self.max_overlap_samples = max(self.max_overlap_samples, run_length)
        if old == 0 and self.pending_gap_source is not None:
            destination = {1: 0, 2: 1}.get(new_state)
            if destination is not None and destination != self.pending_gap_source:
                self.gaps[f"{self.pending_gap_source}_to_{destination}"].append(run_length)
        self.pending_gap_source = {1: 0, 2: 1}.get(old) if new_state == 0 else None
        for bit, channel in enumerate(self.channels):
            was = (old >> bit) & 1
            now = (new_state >> bit) & 1
            if was == now:
                continue
            if now:
                channel["rises"] += 1
                if channel["last_rise"] is not None and channel["fall"] is not None:
                    channel["periods"].append(position - channel["last_rise"])
                    channel["highs"].append(channel["fall"] - channel["last_rise"])
                channel["last_rise"] = position
                channel["fall"] = None
            else:
                channel["falls"] += 1
                if channel["last_rise"] is not None:
                    channel["fall"] = position
        self.state = new_state
        self.state_start = position

    def feed(self, masked):
        for match in RUNS.finditer(masked):
            self.change(self.total + match.start(), masked[match.start()])
        self.total += len(masked)

    def result(self):
        # Include a terminal overlap run, but never fabricate a terminal cycle
        # or an unbounded initial/final both-low gap.
        terminal = self.total - self.state_start if self.state == 3 else 0
        channels = []
        for channel in self.channels:
            periods, highs = channel["periods"], channel["highs"]
            channels.append({"complete_cycles": len(periods), "rises": channel["rises"],
                             "falls": channel["falls"],
                             "frequency_hz": self.rate / statistics.mean(periods) if periods else None,
                             "duty_percent": 100 * sum(highs) / sum(periods) if periods else None,
                             "period_us": stats(periods, 1e6 / self.rate),
                             "high_us": stats(highs, 1e6 / self.rate)})
        return {"samplerate_hz": self.rate, "sample_period_ns": 1e9 / self.rate,
                "samples": self.total, "capture_seconds": self.total / self.rate,
                "channels": channels,
                "sampled_overlap_samples": self.overlap_samples + terminal,
                "max_sampled_overlap_ns": max(self.max_overlap_samples, terminal) * 1e9 / self.rate,
                "both_low_gap_ns": {key: stats(values, 1e9 / self.rate) for key, values in self.gaps.items()},
                "limitations": ["Configured samplerate from file, not an independently calibrated clock",
                                "Sub-sample glitches/overlap cannot be excluded",
                                "Both-low digital gap is not a measurement of power-transistor deadtime",
                                "No ADC sampling or loaded motor/FOC qualification"]}


def analyze_session(path, first=0, second=1, expected_main_duty=90.0):
    if first == second or not 0 <= first < 8 or not 0 <= second < 8:
        raise ValueError("Select two different D0-D7 channels")
    if not 0 <= expected_main_duty <= 100:
        raise ValueError("Expected physical main duty must be 0..100 percent")
    with zipfile.ZipFile(path) as session:
        metadata = configparser.ConfigParser()
        metadata.read_string(session.read("metadata").decode("utf-8"))
        devices = [name for name in metadata.sections() if name.startswith("device ")]
        if len(devices) != 1:
            raise ValueError("Select a single-device capture")
        device = metadata[devices[0]]
        if int(device["unitsize"]) != 1:
            raise ValueError("Only current 8-bit logic sessions are supported")
        analyzer = Analyzer(samplerate(device["samplerate"]))
        prefix = device["capturefile"]
        chunks = [name for name in session.namelist()
                  if name == prefix or re.fullmatch(re.escape(prefix) + r"-\d+", name)]
        chunks.sort(key=lambda name: int(name[len(prefix) + 1:]) if name != prefix else 0)
        if not chunks:
            raise ValueError("No logic samples in session")
        table = bytes(((value >> first) & 1) | (((value >> second) & 1) << 1) for value in range(256))
        for name in chunks:
            with session.open(name) as stream:
                while block := stream.read(1_000_000):
                    analyzer.feed(block.translate(table))
        result = analyzer.result()
        for index, physical in enumerate((first, second)):
            result["channels"][index]["channel"] = f"D{physical}"
            result["channels"][index]["label"] = device.get(f"probe{physical + 1}", f"D{physical}")
        result["source"] = str(Path(path).resolve()) if isinstance(path, (str, Path)) else "<in-memory test session>"
        if isinstance(path, (str, Path)):
            with Path(path).open("rb") as source:
                digest = hashlib.sha256()
                while block := source.read(1_000_000):
                    digest.update(block)
            result["source_sha256"] = digest.hexdigest()
        usable = [channel for channel in result["channels"] if channel["complete_cycles"] >= 5]
        result["main_by_larger_duty"] = max(usable, key=lambda item: item["duty_percent"])["channel"] if len(usable) == 2 else None
        result["expected_main_pin_duty_percent"] = expected_main_duty
        result["digital_checks"] = {
            "both_channels_have_cycles": len(usable) == 2,
            "both_near_20khz": len(usable) == 2 and all(19500 <= item["frequency_hz"] <= 20500 for item in usable),
            "main_near_90_percent": len(usable) == 2 and abs(max(item["duty_percent"] for item in usable) - 90) < .25,
            "main_near_expected_percent": len(usable) == 2 and abs(max(item["duty_percent"] for item in usable) - expected_main_duty) < .25,
            "no_sampled_overlap": result["sampled_overlap_samples"] == 0,
            "both_deadtime_directions_present": all(result["both_low_gap_ns"].values()),
            "deadtime_resolution_24mhz_or_better": result["samplerate_hz"] >= 24e6,
        }
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--first", type=int, default=0)
    parser.add_argument("--second", type=int, default=1)
    parser.add_argument("--output", required=True)
    parser.add_argument("--expected-main-duty", type=float, default=90.0,
                        help="Expected PHYSICAL pin duty, not software reference; default preserves earlier 90%% test")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    root = Path(__file__).resolve().parents[1]
    if not output.is_relative_to(root):
        parser.error("Output must stay inside workspace")
    result = analyze_session(args.input, args.first, args.second, args.expected_main_duty)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
