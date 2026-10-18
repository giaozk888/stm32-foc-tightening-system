"""Offline ELF/SRAM decoder. No serial/debugger/flash/motor operations.

Default: list the instrumented image and mark all runtime results unmeasured.
With captures: require matching complete Flash + the same capture's VTOR; never
decode an arbitrary old SRAM layout as the current build's timing evidence.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess

ROOT=Path(__file__).resolve().parents[1]
NM=Path('D:/software/arm/bin/arm-none-eabi-nm.exe')
STAGES=('adc_read','raw_diagnostics','current_validation','clarke_park',
        'current_pi_and_limit','inverse_park','svpwm','duty_dispatch','other_diagnostics')


def symbols(elf):
    out=subprocess.run([str(NM),'-S','-n',str(elf)],capture_output=True,text=True,check=True).stdout
    return {m[4]:(int(m[1],16),int(m[2],16)) for m in re.finditer(
        r'^([0-9a-f]+) ([0-9a-f]+) ([A-Za-z]) (\S+)$',out,re.M)}


def phase(words):
    n,invalid,total,cpu=words[:4]
    return dict(status='MEASURED' if n else 'NOT_MEASURED',frames=n,invalid=invalid,
        normal_total_max_cycles=total if n else None,
        normal_total_max_us=total/170 if n else None,
        normal_cpu_max_us=cpu/170 if n else None,
        stages={name:dict(wall_max_cycles=words[4+i],wall_max_us=words[4+i]/170,
            cpu_max_cycles=words[13+i],cpu_max_us=words[13+i]/170) if n else None
            for i,name in enumerate(STAGES)},
        worst_frame=dict(total_cycles=words[22],irq_union_cycles=words[23],
            wall_cycles=dict(zip(STAGES,words[24:33])),
            irq_cycles=dict(zip(STAGES,words[33:42]))) if n else None)


def timer_point(words):
    return dict(dwt=words[0],cnt=words[1],observation_span_cycles=words[2],
        down=bool(words[3]&0xff),valid=bool((words[3]>>8)&0xff))


def pwm(words):
    n,invalid,late,writes,suppressed,margin,next_uev,write_cycles=words[:8]
    margin=struct.unpack('<i',struct.pack('<I',margin))[0]
    return dict(status='MEASURED' if n else 'NOT_MEASURED',points=n,invalid=invalid,
        actual_ccr_writes=writes,late_update_count=late,possible_suppressed_uev_count=suppressed,
        pwm_update_margin_ticks_min=margin if n else None,
        pwm_update_margin_us_min=margin/170 if n else None,
        next_uev_ticks_min=next_uev if n else None,
        cycles_ccr_write_max=write_cycles if writes and n else None,
        ccr_write_max_us=write_cycles/170 if writes and n else None,
        worst_entry=timer_point(words[8:12]),last_write_begin=timer_point(words[12:16]),
        last_write_end=timer_point(words[16:20]),worst_margin_point=timer_point(words[20:24]),
        geometry=dict(zip(('CR1','CR2','ARR','PSC','RCR','CCMR1','CCMR2','ADC1_JSQR'),words[24:32])))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--elf',type=Path,default=ROOT/'foc2_app_a/build/FastPathTiming/foc2.elf')
    p.add_argument('--ram',type=Path)
    p.add_argument('--flash',type=Path)
    p.add_argument('--vtor',type=lambda s:int(s,0),help='VTOR from the SAME halted capture')
    a=p.parse_args()
    image=a.elf.with_suffix('.bin').read_bytes()
    sym=symbols(a.elf)
    result=dict(status='WAITING_MANUAL_BOARD_VALIDATION',image_bytes=len(image),
        bin_sha256=hashlib.sha256(image).hexdigest(),
        elf_sha256=hashlib.sha256(a.elf.read_bytes()).hexdigest(),
        control_algorithms_changed=False,stages=STAGES,
        runtime_note='No host timing or synthetic counters are MCU measurements.')
    if a.ram or a.flash or a.vtor is not None:
        if not (a.ram and a.flash and a.vtor is not None):
            p.error('--ram, --flash and --vtor must be supplied together')
        if a.vtor not in (0x08008000,0x08040000): p.error('unexpected VTOR')
        flash=a.flash.read_bytes(); offset=a.vtor-0x08000000
        if len(flash)!=512*1024 or flash[offset:offset+len(image)]!=image:
            p.error('complete Flash capture does not match this exact image at VTOR')
        if struct.unpack_from('<I',image,4)[0]!=sym['Reset_Handler'][0]|1:
            p.error('ELF/BIN reset entry mismatch')
        ram=a.ram.read_bytes()
        def words(name,size):
            addr,actual=sym[name]; index=addr-0x20000000
            if actual!=size or index<0 or index+size>len(ram):
                raise ValueError('RAM/schema mismatch: '+name)
            return struct.unpack_from('<'+'I'*(size//4),ram,index)
        result['status']='OFFLINE_CAPTURE_DECODED_NOT_MOTOR_QUALIFICATION'
        result['phases']=phase(words('foc_path_profile',168))
        cycles=words('cl_current_cycles',36)
        result['outer_adc_including_profile_reducer']=dict(
            normal_total_max_cycles=cycles[3],normal_total_max_us=cycles[3]/170,
            overall_max_cycles=cycles[1],deadline_miss_count=cycles[8])
        result['actual_ccr']=pwm(words('foc_pwm_write_profile',128))
        result['hypothetical_duty_point']=pwm(words('foc_pwm_duty_profile',128))
        result['irq_inclusive_max_cycles']=words('foc_profile_irq_max',16)
        result['irq_calls']=words('foc_profile_irq_calls',16)
        result['warning_verdict']='UNRESOLVED_NO_ACTUAL_CCR_WRITES' if not result['actual_ccr']['actual_ccr_writes'] else 'REVIEW_SAME_FRAME_TIMING'
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__': main()
