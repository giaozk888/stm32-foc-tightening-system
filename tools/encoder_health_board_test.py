"""Pinned health-synchronized A; hard-OFF, single trial, offline by default."""
import json
import sys
import time
import encoder_foc_first_board_test as previous
from health_confirmation_wait import StartupFault, wait_health_confirmation

base = previous.base
ROOT, OUTPUT, PRIVATE = previous.ROOT, previous.OUTPUT, previous.PRIVATE
IMAGE = ROOT/'foc2_app_a/build/EncoderHealthReview/EncoderFocFirst/foc2.bin'
ELF = IMAGE.with_suffix('.elf')
SHA = 'c7eb539311b572e451589ec93b8c8eb4bdddcc4938e3c82c2f0911c45f434408'
ELF_SHA = '03407e5b186b9de756557b5fdcf2b955b9ca71cb0c56ed66e1f7f09443c9caea'
SIZE = 228964
PREFIX = 'encoder-health-'
BASE_RECEIPT = OUTPUT/'encoder-health-restore-1792221718168887100.json'
BASE_SHA = '1c0fc9f186e6222abaf94e0c3825b290ee29bf5055059b4d575fca623f9c942e'
BASE_META = (1112493908,3,2,0,0,611,228964,3734682205,210916,453748590,0,3589413415)
_restore = base.tx.restore


def wait_confirmation(uart, row):
    try:
        wait_health_confirmation(uart, row, base.prior.fields)
    except StartupFault:
        # Preserve the existing one-shot fault capture/diagnostic drain. A
        # timeout here is NOT a reason to resume startup or repeat activation.
        row['sample'] = base.prior.sample(uart)
        end = time.monotonic() + 5.5
        while time.monotonic() < end:
            uart.poll(.05)
        raise


def restore(row, run, data, receipt):
    stopped = base.tx.read_receipt(receipt, 'trial')
    vtor = stopped.get('snapshot_vtor')
    if vtor == 0x08008000:
        return _restore(row, run, data, receipt)
    if vtor != 0:
        raise ValueError('Restore requires stopped new A or captured bootloader owner')
    # Normal health confirmation resets into the bootloader. Its stopped VTOR
    # is 0, not A. Keep all existing halt/off/full-Flash/metadata checks, but
    # require that precise captured owner; never decode its RAM as application.
    original_gate = base.tx.prior.off_gate
    def boot_gate(expected):
        if expected != 0x08008000:
            raise ValueError('Unexpected restore gate target')
        return original_gate(0)
    base.tx.prior.off_gate = boot_gate
    row['restore_from_stopped_bootloader'] = True
    try:
        return _restore(row, run, data, receipt)
    finally:
        base.tx.prior.off_gate = original_gate


def image():
    data = IMAGE.read_bytes()
    receipt = json.loads((ROOT/'tests/foc_adaptive_build/encoder_health_evidence/receipt.json').read_text())
    if (len(data) != SIZE or base.tx.digest(data) != SHA or
        base.tx.digest(ELF.read_bytes()) != ELF_SHA or base.prior.image_info(data)[0] != 'A' or
        receipt.get('hardware_access') is not False or receipt.get('test_count') != 132 or
        not any(b.get('app') == 'foc2_app_a' and b.get('profile') == 'EncoderFocFirst' and
            b.get('bin_sha256') == SHA and b.get('elf_sha256') == ELF_SHA for b in receipt['builds']) or
        not any(t.get('module') == 'test_encoder_foc_first' and t.get('passed') == 7
                for t in receipt['tests'])):
        raise ValueError('Exact health-synchronized A BIN/ELF/offline receipt required')
    for marker in (b'NAME=FAST_CURRENT_REJECT HARD_OFF=1', b'METHOD=TWO_SAMPLE',
                   b'FILTER=NONE OC=RAW_CONFIRM_4', b'PWM COMMIT', b'HYPOTHETICAL PWM',
                   b'SERVICE_WALL_INCLUDING_CHILDREN'):
        if marker not in data: raise ValueError('Missing hard-off/attribution identity')
    return data


def configure():
    for key in ('IMAGE','ELF','SHA','ELF_SHA','SIZE','PREFIX','BASE_RECEIPT','BASE_SHA','BASE_META'):
        setattr(previous, key, globals()[key])
    previous.image = image
    previous.configure()
    base.configure = configure
    base.tx.restore = restore
    base.wait_confirmation = wait_confirmation


def main():
    configure()
    if len(sys.argv) == 1:
        image(); previous.verify()
        print('OFFLINE PASS: pinned health-synchronized A / B611 fallback / no devices')
        return 0
    return base.main()


if __name__ == '__main__': raise SystemExit(main())
