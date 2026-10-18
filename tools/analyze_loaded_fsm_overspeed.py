"""Offline replay of the exact 2026-10-18 loaded-B overspeed capture.

Reads existing Flash/RAM and the matching ELF. No serial/debugger imports or
controller changes. Derived speed integral is valid for completed SPEED frames
only, not the interrupted first-fault frame.
"""
import hashlib
import json
from pathlib import Path
import struct

from foc_path_profile_report import symbols
from loaded_fsm_snapshot_report import decode

ROOT = Path(__file__).resolve().parents[1]
PREFIX = ROOT/'tmp/loaded-fsm-motion-1792300223073650000'
IMAGE = ROOT/'foc2_app_b/build/LoadedFsmTrial/foc2.bin'
ELF = IMAGE.with_suffix('.elf')
IMAGE_SHA = '1fd1afa9156bb72e71d42a16378d1e0a2cc76d167d9037dd5b3a869d63256826'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def analyze():
    flash = Path(str(PREFIX)+'-flash.bin').read_bytes()
    ram = Path(str(PREFIX)+'-ram.bin').read_bytes()
    image = IMAGE.read_bytes()
    table = symbols(ELF)
    if (len(flash) != 0x80000 or len(ram) != 0x20000
            or digest(image) != IMAGE_SHA
            or flash[0x40000:0x40000+len(image)] != image
            or struct.unpack_from('<I', image, 4)[0] != (table['Reset_Handler'][0] | 1)):
        raise ValueError('Exact captured B image and corresponding ELF required')
    address, size = table['cl_startup']
    if size != 2000:
        raise ValueError('Unexpected ARM startup trace layout')
    offset = address-0x20000000
    start, flags, off_us, total, active, frozen, fault_valid, _ = struct.unpack_from(
        '<4I4B', ram, offset+33*60)
    if not frozen or active or not fault_valid or flags != 1024 or total < 32:
        raise ValueError('Frozen original overspeed trace required')
    rows = []
    for seq in range(total-32, total):
        v = struct.unpack_from('<3I4H10f', ram, offset+(seq % 32)*60)
        row = dict(zip(('elapsed_us','adc_seq','encoder_us','angle_raw','adc_u','adc_v',
                        'reserved','ref_rpm','instant_rpm','filtered_rpm','iq_ref_A',
                        'id_A','iq_A','vd_V','vq_V','current_int_d_V','current_int_q_V'),v))
        row['speed_p_A'] = .003*(row['ref_rpm']-row['filtered_rpm'])
        row['speed_integral_inferred_A'] = row['iq_ref_A']-row['speed_p_A']
        rows.append(row)
    errors = dict(raw_speed_rpm=[], lpf_rpm=[], inferred_speed_integral_A=[])
    for prev, row in zip(rows, rows[1:]):
        dt_us = (row['encoder_us']-prev['encoder_us']) & 0xffffffff
        dt = dt_us*1e-6
        delta = (row['angle_raw']-prev['angle_raw']+8192) % 16384-8192
        instant = -delta*60/(16384*dt)
        filtered = prev['filtered_rpm']+dt/(.020+dt)*(row['instant_rpm']-prev['filtered_rpm'])
        error = row['ref_rpm']-row['filtered_rpm']
        integral = prev['speed_integral_inferred_A']
        bleed = (abs(row['filtered_rpm']) >= 5 and abs(error) >= 5
                 and error*row['filtered_rpm'] < 0 and integral*row['filtered_rpm'] > 0)
        inferred = max(0,integral-5*dt) if bleed else integral+.020*error*dt
        errors['raw_speed_rpm'].append(abs(instant-row['instant_rpm']))
        errors['lpf_rpm'].append(abs(filtered-row['filtered_rpm']))
        errors['inferred_speed_integral_A'].append(abs(inferred-row['speed_integral_inferred_A']))
        row.update(dt_us=dt_us, raw_delta=delta, existing_overspeed_bleed=bleed)
    max_errors = {key:max(values) for key,values in errors.items()}
    if (max_errors['raw_speed_rpm'] > .001 or max_errors['lpf_rpm'] > .001
            or max_errors['inferred_speed_integral_A'] > 1e-5):
        raise ValueError('Replay does not reproduce the captured controller')
    result = dict(image_sha256=IMAGE_SHA, ram_sha256=digest(ram),
        flash_sha256=digest(flash), elf_sha256=digest(ELF.read_bytes()),
        offline_only=True, motor_commands=0, controller_modified=False,
        startup=dict(start_us=start,off_us=off_us,total_completed_frames=total),
        max_replay_error=max_errors, rows=rows, snapshot=decode(ram),
        supported_findings=[
            '31 successive angle deltas are all in one direction, -4..-31 counts.',
            'Sample timestamps are 993..1008 us apart; no speed timebase compression in this window.',
            'Raw speed and 20 ms LPF reproduce the completed outer-loop trace.',
            'Inferred speed PI integral reproduces the existing integration and 5 A/s bleed.',
            'All 32 completed frames command positive Iq, including after speed exceeds target.',
            'The 0.4 A output saturation anti-windup condition is not reached in this window.'
        ], remaining_unknowns=[
            'The trace alone cannot independently certify physical shaft motion or exclude sustained magnetic/encoder error.',
            'The reason for low initial movement (mechanical resistance/load, angle/current phase alignment, supply behavior) is not captured.',
            'No independently measured torque or shaft speed is available.'
        ])
    target = Path(str(PREFIX)+'-overspeed-analysis.json')
    target.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print('OFFLINE REPLAY PASS:',target)
    print(json.dumps(max_errors,indent=2))
    print('elapsed_ms instant_rpm filtered_rpm P_mA inferred_I_mA IqRef_mA')
    for index in (0,10,11,14,18,24,31):
        row=rows[index]
        print('%.3f %.2f %.2f %.1f %.1f %.1f' % (
            row['elapsed_us']/1000,row['instant_rpm'],row['filtered_rpm'],
            row['speed_p_A']*1000,row['speed_integral_inferred_A']*1000,row['iq_ref_A']*1000))
    return result


if __name__ == '__main__':
    analyze()
