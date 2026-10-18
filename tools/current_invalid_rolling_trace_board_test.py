"""Pinned CTR2 acquisition: OFF stage / ON no-START trial / OFF B restore.

No firmware rebuild or control-policy changes. HARD_OFF=0: this uses the
existing output-disabled READY path, never a motion command. Control pass and
successful capture of an expected CURRENT_INVALID fault remain separate.
"""
from contextlib import ExitStack
import json
from pathlib import Path
from unittest.mock import patch

import current_fault_trace_board_test as previous

ROOT, OUTPUT = previous.ROOT, previous.OUTPUT
IMAGE = ROOT/'foc2_app_a/build/CurrentInvalidRollingTrace/foc2.bin'
ELF = IMAGE.with_suffix('.elf')
SIZE = 229364
SHA = '47dfff9f3d3e80aea5c2621ae30fb8e94df2ee25a1fc4e8193f497522dc7a3d7'
ELF_SHA = 'd5370c056e93de8c67cbb11b3a6aa873004aba00be829df15d8c851f6a78670a'
PREFIX = 'current-invalid-rolling-trace-'
BASE_RECEIPT = OUTPUT/'current-fault-trace-restore-1792242777752566300.json'
BASE_SHA = '0c2390094ab15bebe2eed5c75e23f5a86dc1eb1ad6224cfc35630f16a8bc0caf'
BASE_META = (1112493908,3,2,0,0,623,229316,2376558905,210916,453748590,0,1550448665)
B_SHA = previous.B_SHA
BUILD_RECEIPT = ROOT/'tests/current_invalid_rolling_trace_build/receipt.json'
BUILD_RECEIPT_SHA = '43e7ad8609f58d95fd85c5067d938e609b825574776525b59f69e0b22f3b58a1'
_decode_previous = previous.decode


def image():
    data, elf, receipt_raw = IMAGE.read_bytes(), ELF.read_bytes(), BUILD_RECEIPT.read_bytes()
    digest = previous.candidate.digest
    if (len(data) != SIZE or digest(data) != SHA or digest(elf) != ELF_SHA or
            previous.candidate.image_info(data)[0] != 'A' or previous.candidate.MARKER not in data):
        raise ValueError('Exact offline-tested rolling trace A BIN/ELF required')
    if digest(receipt_raw) != BUILD_RECEIPT_SHA:
        raise ValueError('Reviewed offline receipt changed; review before hardware')
    receipt = json.loads(receipt_raw)
    if (any(receipt.get(k) is not False for k in ('hardware_access','motor_started',
            'boot_selection_changed','control_policy_changed')) or
            receipt.get('test_count') != 204 or receipt.get('passed_count') != 203 or
            receipt.get('all_images_linked') is not True):
        raise ValueError('Expected four-build/203-of-204 reviewed evidence required')
    failed = [t for t in receipt['tests'] if not t['success']]
    if (len(failed) != 1 or failed[0]['module'] != 'test_foc_path_profile' or
            failed[0]['failures'] != 1 or failed[0]['errors'] != 0):
        raise ValueError('Only the documented pre-existing source-hash assertion is reviewed')
    if not any(b['slot'] == 'a' and b['bin_sha256'] == SHA and
            b['elf_sha256'] == ELF_SHA and b['linked'] and
            b['memory']['frame_bytes'] == 72 and b['memory']['ram_ring'] == 1172
            for b in receipt['builds']):
        raise ValueError('CTR2 schema/build receipt mismatch')
    return data


def acquisition(header, frames, first_fault):
    """File-only evidence checks; never promote a fault to a control PASS."""
    if header['magic'] != 0x43545232:
        raise ValueError('CTR2 rolling trace required, not historical CTR1')
    if not header['frozen']:
        return dict(captured=False, status='CURRENT_INVALID_NOT_REPRODUCED')
    if (header['freeze_reason'] != 1 or not frames or not first_fault.get('valid') or
            first_fault.get('domain') != 2 or first_fault.get('fault_reason') != 11 or
            first_fault.get('adc_sample_count') != header['fault_seq'] or
            frames[-1]['seq'] != header['fault_seq']):
        raise ValueError('Frozen trace and same-session CURRENT_INVALID snapshot disagree')
    if len(frames) != 16:
        raise ValueError('Full 16-frame pre-fault window missing')
    final = frames[-1]
    if (final['protection_fault'] != 1 or final['protection_reason'] != 11 or
            final['discriminator_result'] != -1):
        raise ValueError('Final fault decision context missing')
    last_three = frames[-3:]
    if ([r['unresolved_consecutive_before'] for r in last_three] != [0,1,2] or
            any(r['discriminator_executed'] != 1 or r['decision_path'] != 3
                for r in last_three)):
        raise ValueError('Final three consecutive unresolved decisions not captured')
    for r in frames:
        d_old = max(abs(r['raw_u']-r['reference_u_before']),
                    abs(r['raw_v']-r['reference_v_before']))
        d_candidate = max(abs(r['raw_u']-r['candidate_u_before']),
                          abs(r['raw_v']-r['candidate_v_before']))
        if (d_old,d_candidate) != (r['d_old'],r['d_candidate']):
            raise ValueError('Before-state operands do not reproduce recorded distances')
    return dict(captured=True, status='CURRENT_INVALID_WINDOW_CAPTURED',
        fault_seq=header['fault_seq'], preceding_frames=15,
        unresolved_seqs=[r['seq'] for r in last_three], control_pass=False)


def decode(row, data):
    _decode_previous(row, data)
    if 'trace' not in row:
        row['acquisition'] = dict(captured=False, status='NO_MATCHING_A_RAM_CAPTURE')
        return
    t = row['trace']
    t['timing_scope'] = 'rolling binary trace until CURRENT_INVALID; probe overhead included'
    row['acquisition'] = acquisition(t['header'],t['frames'],row.get('first_fault',{}))
    report = previous.trace.table(t['header'],t['frames'])
    print(report, flush=True)
    print('ACQUISITION: '+row['acquisition']['status'], flush=True)


def main():
    # Scope module bindings to this invocation. Historical tools, tests and image
    # pins stay intact. Reuse only their already-tested transaction/no-START path.
    names = ('IMAGE','ELF','SHA','ELF_SHA','SIZE','PREFIX','BASE_RECEIPT',
             'BASE_SHA','BASE_META','B_SHA')
    values = {name:globals()[name] for name in names}
    candidate, tx = previous.candidate, previous.candidate.tx
    with ExitStack() as stack:
        stack.enter_context(patch.multiple(previous,**values,image=image,decode=decode))
        stack.enter_context(patch.multiple(candidate,**{n:getattr(candidate,n) for n in names},
            image=candidate.image))
        tx_names = ('IMAGE','SHA','SIZE','PREFIX','BASE_RECEIPT','BASE_SHA','BASE_META','B_SHA')
        stack.enter_context(patch.multiple(tx,**{n:getattr(tx,n) for n in tx_names},image=tx.image))
        stack.enter_context(patch.object(previous.trial,'load_stage',previous.trial.load_stage))
        return previous.main()


if __name__ == '__main__':
    raise SystemExit(main())
