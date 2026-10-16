"""Known-reference-only locked OFF/ON contrast; preserve every raw sample."""
import re
import adc12_only_report as adc12
from zero_retest_sample import fields


def require_status(line, terminal=False, power=None):
    row = fields(line)
    if row.get("MODE") != "ADC12_REFERENCE" or row.get("SUPPLY_POLICY") != "EXPLICIT_OFF_ON":
        raise ValueError("Explicit locked reference-input profile required")
    state = row.get("POWER")
    value = row.get("ADMIT_MV", "")
    if not re.fullmatch(r"\d+", value) or state not in ("NONE", "OFF", "ON"):
        raise ValueError("Missing actual supply admission record")
    value = int(value)
    if ((state == "NONE" and value != 0) or (state == "OFF" and not 0 <= value <= 1000) or
            (state == "ON" and not 10000 <= value <= 14000) or (terminal and state == "NONE") or
            (power is not None and state != power)):
        raise ValueError("Supply state does not match explicit capture request")
    # Reuse the strict ADC1/2 count/lock/IRQ/padding validator only after
    # validating the new identity. No legacy reply is admitted as reference.
    normalized = line.replace("MODE=ADC12_REFERENCE", "MODE=ADC12_ONLY", 1)
    adc12.require_status(normalized, terminal=terminal)
    return row


def verify_capture(line, triples, power=None):
    require_status(line, terminal=True, power=power)
    return adc12.verify_capture(line.replace("MODE=ADC12_REFERENCE", "MODE=ADC12_ONLY", 1), triples)


def require_supply(line, power):
    if not re.match(r"^\d+ OK ", line) or power not in ("OFF", "ON"):
        raise ValueError("An acknowledged explicit supply state is required")
    row = fields(line)
    if row.get("VALID") != "1" or row.get("PROTECT") != "0":
        raise ValueError("Invalid or protected analog supply estimate")
    bus, vdda, age = (int(row.get(k, "-1")) for k in ("VBUS_EST_MV", "VDDA_BOOT_MV", "AGE_MS"))
    expected = 0 <= bus <= 1000 if power == "OFF" else 10000 <= bus <= 14000
    if not expected or not 3000 <= vdda <= 3600 or not 0 <= age <= 500:
        raise ValueError("Fresh real supply estimate must match requested OFF/ON; no fabricated VBUS")
    return row


analyze = adc12.analyze
