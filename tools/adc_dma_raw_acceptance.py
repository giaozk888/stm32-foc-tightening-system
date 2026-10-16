"""Pinned locked diagnostic deployment using the existing guarded UART IAP.

No sampling, force confirmation, direct Flash metadata writes or motor action.
The shared deployer checks both known fallback images and protected regions.
Drive 12 V must be off for --allow-deploy. Old acceptance scripts/images stay intact.
"""
import hashlib
from pathlib import Path
import zero_async_clock_acceptance as deploy

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "safety_backups/adc-dma-raw-live-20261009"
PINNED = {
    "A": "fb98a49edeec94b696d616e990f822f1a8c10dccfd12f0308510e1747cda52ac",
    "B": "2404953e04567b896a2bc17eb5440a661110c75316626805e9197a90c6495ff0",
}


def pinned_image(slot):
    path = ROOT / f"foc2_app_{slot.lower()}/build/AdcDmaRaw20261009/foc2.bin"
    image = path.read_bytes()
    if deploy.image_info(image)[0] != slot or hashlib.sha256(image).hexdigest() != PINNED[slot]:
        raise RuntimeError("Exact offline-verified finite ADC DMA diagnostic required")
    return path, image


def main():
    # Reuse the established inactive-slot/protected-Flash/normal trial flow;
    # change only this process's image policy and evidence directory.
    known = {slot: deploy.KNOWN[slot] | {PINNED[slot]} for slot in "AB"}
    deploy.PINNED = PINNED
    deploy.KNOWN = known
    deploy.OUTPUT = OUTPUT
    deploy.pinned_image = pinned_image
    # locked_baseline's default captured the original KNOWN at definition time.
    original = deploy.locked_baseline
    deploy.locked_baseline = lambda data: original(data, known)
    deploy.main()
    print("ADC DMA DIAGNOSTIC DEPLOYMENT CHECK COMPLETE; no sample or motor action")


if __name__ == "__main__":
    main()
