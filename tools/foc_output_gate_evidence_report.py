"""Binary gate evidence decoder, called only after enclosing image/capture proof.

No serial/debugger/flash operations. Registers are inputs to the failed check,
not a claim of simultaneous reads or proof of which writer changed them.
"""
import re
import struct
from pathlib import Path
import subprocess
from foc_path_profile_report import symbols

FIELDS=('valid','version','mismatch','caller_pc','ipsr','dwt','timer_us',
        'seq_before','seq_after','state_before','state_used','state_after',
        'odr','bdtr_moe_read','cr1','bdtr_aoe_read','ccer','sr','primask','armed')
SIZE=4*len(FIELDS)
BITS={1:'CEN_OFF',2:'AOE_ON',4:'SD_UNEXPECTED',8:'MOE_UNEXPECTED',16:'CCER_UNEXPECTED'}

def decode_bytes(data):
    if len(data)!=SIZE:raise ValueError('Gate evidence ABI size mismatch')
    row=dict(zip(FIELDS,struct.unpack('<20I',data)))
    if not row['valid']:return dict(status='NO_FAILED_PREDICATE_CAPTURED')
    if row['valid']!=1 or row['version']!=1:raise ValueError('Gate evidence publication/version invalid')
    running=row['state_used']==2
    # STM32G474 checked original predicate: PC6 ODR, MOE15, AOE14, CEN0.
    bad=(0 if row['cr1']&1 else 1) | (2 if row['bdtr_aoe_read']&(1<<14) else 0)
    if bool(row['odr']&(1<<6))!=running:bad|=4
    if bool(row['bdtr_moe_read']&(1<<15))!=running:bad|=8
    if row['ccer']!=(0x555 if running else 0):bad|=16
    if bad!=row['mismatch'] or not bad:raise ValueError('Captured predicate/context inconsistent')
    row.update(status='MEASURED_FAILED_PREDICATE',
        failed_inputs=[name for bit,name in BITS.items() if bad&bit],
        observation_spanned_adc_or_state_change=(row['seq_before']!=row['seq_after'] or
            len({row['state_before'],row['state_used'],row['state_after']})!=1),
        writer_attribution='NOT_PROVEN_BY_REGISTER_READS',
        caller_pc_hex=hex(row['caller_pc']))
    return row

def decode(ram,elf):
    table=symbols(elf)
    if 'cl_output_gate_evidence' not in table:return dict(status='NOT_BUILT_IN_THIS_ELF')
    address,size=table['cl_output_gate_evidence'];offset=address-0x20000000
    if size!=SIZE or offset<0 or offset+size>len(ram):raise ValueError('Gate evidence ELF/SRAM bounds mismatch')
    row=decode_bytes(ram[offset:offset+size])
    if row['status']=='MEASURED_FAILED_PREDICATE':
        pc=row['caller_pc']
        # Return PC refers to AFTER the call. Symbolize preceding Thumb halfword.
        tool=Path('D:/software/arm/bin/arm-none-eabi-addr2line.exe')
        p=subprocess.run([str(tool),'-f','-e',str(elf),hex((pc&~1)-2)],
                         capture_output=True,text=True,check=True)
        row['caller_location']=p.stdout.strip().splitlines()
        header=Path(elf).parents[2]/'Drivers/CMSIS/Device/ST/STM32G4xx/Include/stm32g474xx.h'
        if header.exists():
            names={int(value)+16:name for name,value in re.findall(
                r'\b(\w+_IRQn)\s*=\s*(-?\d+)',header.read_text('utf-8'))}
            row['irq_name']=names.get(row['ipsr'],'Thread' if not row['ipsr'] else 'UNKNOWN_EXCEPTION')
    return row
