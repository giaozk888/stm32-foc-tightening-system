"""Decode a stopped/frozen capture only. Never opens a device or sends commands.

Requires same-session full Flash/RAM and VTOR, checked against the given ELF/BIN.
All current columns are the protection's signed ADC counts, NOT measured amps.
"""
import argparse
import hashlib
from pathlib import Path
import struct
import foc_path_profile_report as schema

HEADER = struct.Struct('<IIIHH12B')
FRAME = struct.Struct('<11Bb4BII5H3h4Hf')
NAMES = ('timer_down hardware_valid compare_executed over_mask confirm_active confirm_cycles good_samples '
         'protection_fault protection_result protection_reason discriminator_executed '
         'discriminator_result pi_frozen pwm_frozen events pending_before '
         'seq sample_us raw_u raw_v zero_u zero_v limit_counts iu_counts iv_counts '
         'iw_counts ccr1 ccr2 ccr3 timer_cnt electrical_angle').split()
HEADER_V2 = struct.Struct('<IIHH8B')
FRAME_V2 = struct.Struct('<11Bb4BII5H3h4Hf6HI4B')
NAMES_V2 = NAMES + ('reference_u_before reference_v_before candidate_u_before '
    'candidate_v_before d_old d_candidate unresolved_consecutive_before '
    'state_before pwm_pending_before decision_path before_reserved').split()


def decode(raw):
    if len(raw) < HEADER.size:
        raise ValueError('Trace size mismatch')
    magic = struct.unpack_from('<I', raw)[0]
    rolling = magic == 0x43545232
    header, frame, names = (HEADER_V2, FRAME_V2, NAMES_V2) if rolling else (HEADER, FRAME, NAMES)
    if len(raw) != header.size + 16*frame.size:
        raise ValueError('Trace size mismatch')
    fields = header.unpack_from(raw)
    keys = ('magic trigger_seq fault_seq frame_bytes capacity write_index count '
            'current_index open triggered frozen trigger_index fault_index '
            'recovering post_remaining freeze_reason reserved').split()
    if rolling:
        keys = ('magic fault_seq frame_bytes capacity write_index count current_index '
            'open frozen freeze_reason reserved0 reserved1').split()
    t = dict(zip(keys, fields))
    if (t['magic'] not in (0x43545231, 0x43545232) or t['frame_bytes'] != frame.size or
            t['capacity'] != 16 or not 0 <= t['count'] <= 16 or
            any(t[k] >= 16 for k in (('write_index','current_index') if rolling else
                ('write_index','current_index','trigger_index','fault_index')))):
        raise ValueError('Invalid trace schema/index')
    rows = []
    for i in range(t['count']):
        slot = (t['write_index']-t['count']+i) & 15
        row = dict(zip(names, frame.unpack_from(raw, header.size+slot*frame.size)))
        if rows and ((row['seq']-rows[-1]['seq']) & 0xffffffff) != 1:
            raise ValueError('Trace is not consecutive ADC pairs')
        row['slot'] = slot
        delta = (row['seq']-t.get('trigger_seq',0)) & 0xffffffff
        delta = delta if delta < 0x80000000 else delta-0x100000000
        row['phase'] = ('FAULT' if row['protection_fault'] else
            'TRIGGER' if row['events'] & 1 else 'RECOVERY' if row['events'] & 2 else
            f'PRE{delta}' if t.get('triggered') and delta < 0 else
            'CONFIRM' if row['confirm_active'] else 'POST' if t.get('triggered') else 'ROLL')
        rows.append(row)
    return t, rows


def table(t, rows):
    if t['magic'] == 0x43545232:
        return rolling_table(t, rows)
    lines = [f"TRACE frozen={t['frozen']} reason={t['freeze_reason']} count={t['count']} "
             f"trigger_seq={t['trigger_seq']} fault_seq={t['fault_seq']}",
        'ADC_W/OFF_W=NA (W reconstructed); CURRENT_UNIT=counts; SECTOR=NA',
        'CCR=preload register readback before pair protection, NOT active latch; '
        'CNT/DIR=pair-processing point, NOT trigger aperture',
        '| phase | seq | us | U/V/W raw | U/V/W offset | Iu/Iv/Iw counts | abs U/V | limit | '
        'confirm cycles/good | over phase | fault/reason | disc exec/result | PI/PWM freeze | '
        'CCR1/2/3 | angle(rad)/sector | CNT/DIR |',
        '|---|---:|---:|---|---|---|---|---:|---|---|---|---|---|---|---|---|']
    for r in rows:
        comp = r['compare_executed']
        currents = '/'.join(str(r[k]) for k in ('iu_counts','iv_counts','iw_counts')) if comp else 'NA'
        abs_uv = f"{abs(r['iu_counts'])}/{abs(r['iv_counts'])}" if comp else 'NA'
        over = ''.join(x for i,x in enumerate('UVW') if r['over_mask'] & (1 << i)) or '-'
        if not comp:
            over = 'NA'
        ccr = '/'.join(str(r[k]) for k in ('ccr1','ccr2','ccr3')) if r['hardware_valid'] else 'NA'
        disc = str(r['discriminator_result']) if r['discriminator_executed'] else 'NOT_EXECUTED'
        lines.append(f"| {r['phase']} | {r['seq']} | {r['sample_us']} | {r['raw_u']}/{r['raw_v']}/NA | "
            f"{r['zero_u']}/{r['zero_v']}/NA | {currents} | {abs_uv} | {r['limit_counts']} | "
            f"{r['confirm_active']}:{r['confirm_cycles']}/4 good={r['good_samples']} | {over} | "
            f"{r['protection_fault']}/{r['protection_reason']} | {r['discriminator_executed']}/{disc} | "
            f"{r['pi_frozen']}/{r['pwm_frozen']} | {ccr} | {r['electrical_angle']:.7g}/NA | "
            f"{r['timer_cnt']}/{r['timer_down']} |")
    lines.append('Classification: D — requires physical context/independent evidence; '
                 'this tool does not infer real current or EMI from a final sample.')
    return '\n'.join(lines)


def rolling_table(t, rows):
    lines = [f"CTR2 rolling trace: frozen={t['frozen']} fault_seq={t['fault_seq']} "
        f"count={t['count']}; CUR_CONFIRM event=1 entry / 2 recovery; never freezes",
        'BEFORE operands/state captured before discriminator mutation. Distances are '
        'max(abs(U delta),abs(V delta)) in raw ADC counts. NOT_EXECUTED means no decision.',
        'PWM_PENDING=valid pending at pair processing, after IRQ entry commit; '
        'distinct from CUR_CONFIRM and from PWM generation. ADC_W=reconstructed, not measured.',
        '| seq | raw U/V | state before | reference before U/V | candidate before U/V | '
        'd_old/d_candidate | unresolved before | DISC_EXEC | decision/path | CUR_CONFIRM '
        'before→after | PI_EXEC | PWM_PENDING | PWM_GENERATED | fault/reason |',
        '|---:|---|---|---|---|---|---:|---:|---|---|---:|---|---:|---|']
    paths = {0:'NONE', 1:'NORMAL', 2:'SUSPECT', 3:'UNRESOLVED'}
    decisions = {-1:'FAULT', 0:'HOLD', 1:'USE'}
    for r in rows:
        executed = r['discriminator_executed']
        decision = (decisions.get(r['discriminator_result'], 'INVALID') + '/' +
            paths.get(r['decision_path'], 'INVALID')) if executed else 'NOT_EXECUTED'
        pending = {0:'NA(unbound)', 1:'0', 2:'1'}.get(r['pwm_pending_before'], 'INVALID')
        lines.append(f"| {r['seq']} | {r['raw_u']}/{r['raw_v']} | {r['state_before']} | "
            f"{r['reference_u_before']}/{r['reference_v_before']} | "
            f"{r['candidate_u_before']}/{r['candidate_v_before']} | "
            f"{r['d_old']}/{r['d_candidate']} | {r['unresolved_consecutive_before']} | "
            f"{executed} | {decision} | {r['pending_before']}→{r['confirm_active']} | "
            f"{1-r['pi_frozen']} | {pending} | {1-r['pwm_frozen']} | "
            f"{r['protection_fault']}/{r['protection_reason']} |")
    lines.append('16 filled frames retain 15 preceding ADC pairs + fault; no post-fault overwrite. '
        'This trace alone does not establish whether the physical signal is current or interference.')
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--elf', type=Path, required=True)
    parser.add_argument('--ram', type=Path, required=True)
    parser.add_argument('--flash', type=Path, required=True)
    parser.add_argument('--vtor', type=lambda x: int(x, 0), required=True)
    args = parser.parse_args()
    ram, flash = args.ram.read_bytes(), args.flash.read_bytes()
    image = args.elf.with_suffix('.bin').read_bytes()
    if len(ram) != 0x20000 or len(flash) != 0x80000 or args.vtor not in (0x08008000,0x08040000):
        raise ValueError('Full same-session SRAM/Flash and A/B VTOR required')
    offset = args.vtor-0x08000000
    if flash[offset:offset+len(image)] != image:
        raise ValueError('Captured running slot does not match ELF sibling BIN')
    symbols = schema.symbols(args.elf)
    address, size = symbols['foc_current_fault_trace']
    if size not in (860, 1172) or not 0 <= address-0x20000000 <= len(ram)-size:
        raise ValueError('Wrong trace layout/address')
    t, rows = decode(ram[address-0x20000000:address-0x20000000+size])
    print('BIN SHA256='+hashlib.sha256(image).hexdigest())
    print('ELF SHA256='+hashlib.sha256(args.elf.read_bytes()).hexdigest())
    print(table(t, rows))
    # The existing timing capture remains independent, not synthetic host time.
    address, size = symbols['cl_current_cycles']
    if size != 36:
        raise ValueError('Unexpected wall timing schema')
    c = struct.unpack_from('<9I', ram, address-0x20000000)
    print(f'FOC wall_max_cycles={c[1]} wall_max_us={c[1]/170:.5f} deadline_miss={c[8]}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
