"""One authorized recovery to the original hard-locked B, with drive power OFF.

No firmware programming, direct Flash metadata write, sampling, motion,
forced confirmation or automatic reset retries. The existing bootloader
consumes a CRC-protected SRAM START_TRIAL request for the exact original B.
"""
import argparse
import hashlib
import json
import re
import struct
import subprocess
import time
import zlib

from median_control_acceptance import OUTPUT, SHA as FAILED_A_SHA
from zero_median_contrast import image as original_image
from zero_retest_deploy import CLI, SN, latest_meta, DiagnosticUart, require_service, require_confirmed
from zero_span100_acceptance import ADDRESSES, require_registers, require_new_service
from firmware_transfer_iap import fields, image_info

FAULT_CAPTURE = OUTPUT/'private/1791791541597116000-fault.bin'
MAILBOX_ADDRESS = 0x2001FFC0
META_START, META_END = 0x7E800, 0x7F800


def baseline(data, saved):
    if len(data)!=0x80000 or data!=saved:
        raise RuntimeError('Exact preserved fault Flash required; no restore of changed state')
    meta=latest_meta(data)
    if meta[2:6]!=(1,0,0,411):
        raise RuntimeError('Only failed confirmed A generation 411 admitted')
    b=original_image('B')[1]
    a=data[0x8000:0x8000+meta[6]]
    if (hashlib.sha256(a).hexdigest()!=FAILED_A_SHA or image_info(a)[0]!='A' or
            zlib.crc32(a)!=meta[7] or data[0x40000:0x40000+len(b)]!=b or
            meta[8:10]!=(len(b),zlib.crc32(b))):
        raise RuntimeError('Failed A/original locked B hash or metadata mismatch')
    return meta, b


def mailbox(b):
    if b!=original_image('B')[1] or image_info(b)[0]!='B':
        raise RuntimeError('Only exact original locked B may be requested')
    # Wire layout follows BootMailbox_t, NOT the caller's argument order:
    # magic, version, command, requester_slot, target_slot, size, image CRC.
    # START_TRIAL=2, requester=A=1, target=B=2.
    payload=struct.pack('<7I',0x584F424D,1,2,1,2,len(b),zlib.crc32(b))
    return struct.unpack('<8I',payload+struct.pack('<I',zlib.crc32(payload)))


def require_protected(before, after, b):
    if len(after)!=0x80000 or before[:META_START]!=after[:META_START] or before[META_END:]!=after[META_END:]:
        raise RuntimeError('Flash outside existing boot metadata changed')
    old,new=latest_meta(before),latest_meta(after)
    if new[2:5]!=(2,0,0) or new[5]!=414 or new[6:10]!=old[6:10]:
        raise RuntimeError('Expected normal bootloader confirmation of unchanged B, generation 414')
    if after[0x40000:0x40000+len(b)]!=b:
        raise RuntimeError('Original B changed')
    return dict(all_app_bootloader_kvs_parameters_unchanged=True, confirmed='B',generation=new[5])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--restore-locked-b',action='store_true')
    p.add_argument('--drive-12v-off',action='store_true')
    args=p.parse_args()
    if not args.restore_locked_b or not args.drive_12v_off:
        p.error('Explicit B recovery authorization and drive 12 V OFF required')
    run=str(time.time_ns())
    private=OUTPUT/'private'
    target=OUTPUT/f'restore-b-{run}.json'
    result=dict(pass_=False, reset_requests=0, firmware_written=False,
                direct_metadata_write=False, force_confirm=False,
                sampling=False,motion=False,automatic_retry=False,steps=[])
    port=uart=None
    authorized_words=None
    request_written=False

    def cli(*tokens):
        nonlocal request_written
        if tokens[0]=='-w32':
            exact=('-w32',hex(MAILBOX_ADDRESS),'0','-w32',hex(MAILBOX_ADDRESS+4),
                   *(hex(w) for w in authorized_words[1:]),'-w32',hex(MAILBOX_ADDRESS),hex(authorized_words[0]))
            if request_written or tuple(tokens)!=exact:
                raise ValueError('Only one verified SRAM trial request allowed')
            request_written=True
        elif tokens[0]=='-rst':
            if tuple(tokens)!=('-rst',) or not request_written or result['reset_requests']:
                raise ValueError('One recovery reset only')
            result['reset_requests']=1
        elif tokens[0] not in ('-u','-r32','-r8'):
            raise ValueError('No other hardware mutation allowed')
        process=subprocess.run([CLI,'-c','port=SWD','mode=HOTPLUG','freq=1000','sn='+SN,
                                *map(str,tokens)],capture_output=True,text=True,errors='replace',timeout=30)
        output=process.stdout+process.stderr
        result['steps'].append(dict(args=list(map(str,tokens)),code=process.returncode,output=output))
        if process.returncode or 'Error:' in output:
            raise RuntimeError('SWD failure; no reset retry')
        return output

    def capture(name):
        path=private/f'{run}-restore-{name}.bin'
        cli('-u','0x08000000','0x80000',str(path))
        result[name+'_backup']=str(path)
        return path.read_bytes()

    try:
        before=capture('before')
        meta,b=baseline(before,FAULT_CAPTURE.read_bytes())
        result['before_metadata']=list(meta)
        result['target_sha256']=hashlib.sha256(b).hexdigest()
        authorized_words=mailbox(b)
        result['actual_bootloader_command']=authorized_words[2]
        result['actual_requester_slot']=authorized_words[3]
        pre=cli('-r32','0xE000ED08','4','-r32','0x40012C00','4',
                '-r32','0x40012C20','4','-r32','0x40012C44','4',
                '-r32','0xE000ED28','4','-r8','0x20002D34','1')
        regs={int(a,16):int(v,16) for a,v in re.findall(r'(?im)^0x([0-9A-F]+)\s*:\s*([0-9A-F]+)\s*$',pre)}
        if (len(regs)!=6 or regs[0xE000ED08]!=0x08008000 or regs[0x40012C00]&1 or
                regs[0x40012C20] or regs[0x40012C44]&0xC000 or
                regs[0xE000ED28]!=0x400 or regs[0x20002D34]!=0):
            raise RuntimeError('Fault/timer state changed or original B inherited RTOS gate is not zero')
        import serial
        port=serial.Serial(port=None,baudrate=115200,timeout=.02,write_timeout=2)
        port.dtr=port.rts=False
        port.port='COM5'; port.open()
        uart=DiagnosticUart(port)
        cli('-w32',hex(MAILBOX_ADDRESS),'0','-w32',hex(MAILBOX_ADDRESS+4),
            *(hex(w) for w in authorized_words[1:]),'-w32',hex(MAILBOX_ADDRESS),hex(authorized_words[0]))
        readback=cli('-r32',hex(MAILBOX_ADDRESS),'32')
        lines=re.findall(r'(?im)^0x[0-9A-F]+\s*:\s*((?:[0-9A-F]{8}(?:\s+|$))+)',readback)
        values=tuple(int(v,16) for line in lines for v in line.split())
        if values!=authorized_words:
            raise RuntimeError('SRAM trial request readback mismatch; no reset')
        result['mailbox_verified']=True
        cli('-rst')
        print('One recovery reset requested; waiting for original B normal locked-service confirmation.',flush=True)
        deadline=time.monotonic()+38
        seen=False
        while time.monotonic()<deadline:
            try:
                zero=require_new_service(uart.query('ZERO STATUS',.6))
                fw=fields(uart.query('FW STATUS',.6))
            except TimeoutError: continue
            if fw.get('CURRENT')!='B':
                raise RuntimeError('Unexpected APP during recovery; no retry')
            seen=True
            if fw.get('CONFIRMED')=='B' and fw.get('PENDING')=='-':
                result['confirmed_fw']=require_confirmed(' '.join(f'{k}={v}' for k,v in fw.items()),'B')
                break
            uart.poll(.05)
        else:
            raise TimeoutError('Original B did not normally confirm; no forced confirmation/retry')
        result['final_zero']=require_new_service(uart.query('ZERO STATUS'))
        if result['final_zero'].get('MEDIAN')!='1' or result['final_zero'].get('ADC_OWNER')!='1':
            raise RuntimeError('Wrong locked B profile')
        result['safe_status']=fields(uart.query('ANALOG SAFE STATUS'))
        if any(result['safe_status'].get(k)!=v for k,v in
               (('LATCHED','1'),('SD','0'),('MOE','0'),('FOC','0'))):
            raise RuntimeError('Output lock proof failed')
        tokens=[]
        for address in ADDRESSES: tokens.extend(('-r32',hex(address),'4'))
        result['final_registers']=require_registers(cli(*tokens),'B')
        after=capture('after')
        result['protected_flash']=require_protected(before,after,b)
        result['final_fw']=require_confirmed(uart.query('FW STATUS'),'B')
        result['final_zero']=require_new_service(uart.query('ZERO STATUS'))
        result['pass_']=True
        print('LOCKED B RESTORE PASS: normal confirmation; SD/MOE/CCER/CEN/FOC=0; no firmware write or sampling.',flush=True)
    except BaseException as e:
        result['failure']=str(e)
        raise
    finally:
        if uart: result['uart']=uart.lines
        if port: port.close()
        target.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        print('Evidence: '+str(target),flush=True)


if __name__=='__main__': main()
