"""Pinned 105mA Coulomb A OFF/ON comparison. Default files-only; one START/run."""
import json
from pathlib import Path
import sys
import zlib
import friction_fsm_board as base

TMP=base.TMP
RESTORE=TMP/'friction-cal-restore-1792493964050693700.json'
BASE_SHA='f6e511212486bc4804265c88cd8fb21d9019664fd0e704a4933e889fd066fb5e'
PREVIOUS_A_SHA='f4231c660daab2cbc3dc955bee7057416c3e0b041da6d74471e0959159ab73d6'
IMAGE=base.old.ROOT/'foc2_app_a/build/Tightening240rpmFriction105OnCandidate/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='3adf71acf9579d455f9e0f27e27d121a863c570cde9f0baabb65b9f587ef2899'
ELF_SHA='362662765bc56615f6d264e1356eeae9585603ecbf0693ca960cdbdb44cad406'
ORIGINAL_CONFIGURE=base.configure_baseline


def image():
    data=IMAGE.read_bytes()
    cmds=json.loads((IMAGE.parent/'compile_commands.json').read_text('utf-8'))
    cmd=next(c['command'] for c in cmds if c['file'].endswith('/Core/Src/main.c'))
    base.support.support.require_baud(cmd)
    required=('FOC_INTENT_FSM_CANDIDATE','FOC_PWM_COMMON_MODE_ENABLE',
        'FOC_RUNDOWN240_CANDIDATE','FOC_RUNDOWN240_TRAVEL20000',
        'FOC_ADC_COUNTS_100_40_CANDIDATE','FOC_SPEED_PI_ANTI_WINDUP',
        'FOC_SPEED_SB3_DISABLE_CANDIDATE','FOC_SPEED_SCURVE_CANDIDATE',
        'FOC_ACCEL_FEEDFORWARD_CANDIDATE','FOC_ACCEL_FF_ENABLED_DEFAULT',
        'FOC_SPEED_FRICTION_CANDIDATE','FOC_FRICTION_ENABLED_DEFAULT')
    if (len(data)!=217420 or base.old.zero.digest(data)!=SHA or
        base.old.zero.digest(ELF.read_bytes())!=ELF_SHA or base.hw.image_info(data)[0]!='A' or
        any(cmd.count('-D'+k+'=1')!=1 for k in required) or
        any(k in cmd for k in ('-DFOC_SPEED_LEGACY_AW_COMPARE','-DFOC_FRICTION_CALIBRATION_DIAG')) or
        any(k not in cmd for k in ('-DSPEED_FRICTION_I_A=0.105f',
          '-DSPEED_FRICTION_DEADBAND_RPM=2.0f','-DSPEED_ACCEL_FF_KA_A_PER_RPM_S=0.0001875f',
          'firmware_common/pw_log_tokenized_override'))):
        raise ValueError('Exact offline-tested 105mA A BIN/ELF/flags required')
    for marker in (b' CM=85',b'SPEED_CTRL=FR1',b'INTENT_FSM_CANDIDATE; manual START only',
        b'METHOD=TWO_SAMPLE',b'TRIP_MA=4000',b'RPM=240 LEASE_US=12000000',
        b'RUNDOWN240: RAM=240rpm TRIP=300rpm SAVE=OFF',b'TRAVEL=20000deg RAM only'):
        if marker not in data:raise ValueError('Pinned control/protection marker absent')
    if b'FRC C seq=' in data or b'AFF C seq=' in data:
        raise ValueError('Tokenized dictionary must remain outside BIN')
    return data


def configure(path):
    path=path.resolve()
    if path!=RESTORE.resolve():
        # Subsequent ON run may select an exact 105mA B restore receipt.
        # This retains the original stringent same-image/ELF/boot/B/private checks.
        if path==base.ROOT_RESTORE.resolve():
            raise ValueError('Use B796 or a same-image 105mA restore, not historical root')
        return ORIGINAL_CONFIGURE(path)
    ORIGINAL_CONFIGURE(base.ROOT_RESTORE)
    root=base.baseline()
    r=json.loads(path.read_text('utf-8'))
    capture=Path(r.get('final_capture','')).resolve()
    if (capture.parent!=TMP.resolve() or r.get('mode')!='restore' or
        r.get('image_sha256')!=PREVIOUS_A_SHA or r.get('motor_commands')!=0 or
        any(r.get(k) is not True for k in ('pass_','all_app_private_unchanged',
            'b_application_not_run','final_cpu_halted','final_outputs_off'))):
        raise ValueError('Exact halted B796 restore required')
    raw=capture.read_bytes();meta=base.old.zero.latest_meta(raw);off=r.get('outputs',{})
    if (len(raw)!=0x80000 or base.old.zero.digest(raw)!=BASE_SHA or
        r.get('final_sha256')!=BASE_SHA or list(meta)!=r.get('metadata') or
        meta[2:10]!=(2,0,0,796,212964,2770216733,227964,627317606) or
        base.old.zero.digest(raw[0x8000:0x8000+212964])!=PREVIOUS_A_SHA or
        zlib.crc32(raw[0x40000:0x40000+meta[8]])!=meta[9] or
        raw[:0x8000]!=root[:0x8000] or raw[0x40000:0x7e800]!=root[0x40000:0x7e800] or
        raw[0x7f800:]!=root[0x7f800:] or off.get('VTOR')!=0x08040000 or
        not off.get('DHCSR',0)&0x20000 or off.get('SD',0x40)&0x40 or
        off.get('BDTR',0xC000)&0xC000 or off.get('CCER',1)):
        raise ValueError('B796 baseline identity/preservation/output mismatch')
    base.BASE=capture;base.BASE_SHA=BASE_SHA;base.EXPECT_META=meta;base.BASE_RESTORE_RECEIPT=path


def install():
    base.IMAGE,base.ELF,base.SHA,base.ELF_SHA=IMAGE,ELF,SHA,ELF_SHA
    base.FRICTION_A=.105
    base.image=image;base.configure_baseline=configure


def main():
    install()
    # Powered/restore operations inherit their validated stage/run baseline.
    if not any(x in sys.argv for x in ('--baseline-restore','--execute-powered','--restore-b-drive-off')):
        sys.argv+=['--baseline-restore',str(RESTORE)]
    return base.main()


if __name__=='__main__':raise SystemExit(main())
