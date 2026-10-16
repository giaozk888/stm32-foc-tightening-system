"""Read-only preservation of the failed median compute trial. No reset/halt/write.

Full Flash remains in the existing administrator-only private directory.
Only the exact previously-built APP binary and non-secret fault registers
are exported. Reject a different image or changed protected Flash.
"""
import hashlib
import json
import re
import subprocess
import time

from median_control_acceptance import ROOT, OUTPUT, SHA
from zero_retest_deploy import CLI, SN, latest_meta

ADDRESSES = (0xE000ED08, 0xE000ED28, 0xE000ED2C, 0xE000ED38,
             0xE000ED04, 0xE000E010, 0xE000E014, 0xE000E018,
             0x40012C00, 0x40012C20, 0x40012C44, 0x4002104C,
             0x48000814, 0x20000264, 0x20008180)


def main():
    run = str(time.time_ns())
    private = OUTPUT/'private'
    result = dict(read_only=True, reset=False, halt=False, hardware_write=False,
                  sampling=False, motion=False, steps=[], pass_=False)
    target = OUTPUT/f'fault-inspect-{run}.json'

    def cli(*args):
        if args[0] not in ('-u', '-r32', '-r8', '-coreReg'):
            raise ValueError('Read-only operations required')
        process = subprocess.run([CLI, '-c', 'port=SWD', 'mode=HOTPLUG',
                                  'freq=1000', 'sn='+SN, *map(str, args)],
                                 capture_output=True, text=True, errors='replace', timeout=30)
        output = process.stdout+process.stderr
        result['steps'].append(dict(args=list(map(str,args)),code=process.returncode,output=output))
        if process.returncode or 'Error:' in output:
            raise RuntimeError('Inspection failed; no reset or retry')
        return output

    try:
        # Do not alter or weaken the existing private directory ACL.
        before = (private/'1791790407413310900-before.bin').read_bytes()
        capture = private/f'{run}-fault.bin'
        cli('-u','0x08000000','0x80000',capture)
        actual = capture.read_bytes()
        if len(before)!=0x80000 or len(actual)!=0x80000:
            raise RuntimeError('Complete private Flash captures required')
        result['private_capture'] = str(capture)
        result['metadata'] = list(latest_meta(actual))
        app = actual[0x8000:0x8000+202496]
        if hashlib.sha256(app).hexdigest()!=SHA:
            raise RuntimeError('Current A differs from failed trial; do not archive another image')
        regions = ((0,0x8000),(0x40000,0x7E800),(0x7F800,0x80000))
        if any(before[a:b]!=actual[a:b] for a,b in regions):
            raise RuntimeError('Bootloader/B/KVS/parameters changed')
        artifacts = OUTPUT/'artifacts'
        artifacts.mkdir(exist_ok=True)
        archived = artifacts/'failed-compute-a-original.bin'
        if archived.exists() and archived.read_bytes()!=app:
            raise RuntimeError('Preserve existing artifact')
        if not archived.exists(): archived.write_bytes(app)
        result.update(archived_app=str(archived), image_sha256=SHA, protected_flash_unchanged=True)
        args=[]
        for address in ADDRESSES: args.extend(('-r32',hex(address),'4'))
        output = cli(*args)
        regs = {int(a,16):int(v,16) for a,v in
                re.findall(r'(?im)^0x([0-9A-F]+)\s*:\s*([0-9A-F]{8})\s*$',output)}
        if set(regs)!=set(ADDRESSES): raise RuntimeError('Incomplete register read')
        result['registers']={f'{a:08X}':f'{v:08X}' for a,v in regs.items()}
        result['core']=cli('-coreReg','PC','LR','MSP','PSP','XPSR')
        result['stack']=cli('-r32','0x2001FF58','112')
        result['rtos_started']=cli('-r8','0x20002F7E','1')
        result['timer_off']=(regs[0x40012C00]&1)==0 and regs[0x40012C20]==0 and (regs[0x40012C44]&0xC000)==0
        result['gpio_output_unreadable_clock_off']=(regs[0x4002104C]&4)==0
        result['fault_bfar_valid']=bool(regs[0xE000ED28]&(1<<15))
        result['pass_']=True
        print('READ-ONLY PRESERVATION PASS: failed A archived; B/bootloader/KVS/parameters unchanged.')
        print('Metadata: confirmed=%d pending=%d attempts=%d generation=%d'%tuple(result['metadata'][2:6]))
        print('Timer off=%s; GPIO clock off=%s; CFSR=%08X'%
              (result['timer_off'],result['gpio_output_unreadable_clock_off'],regs[0xE000ED28]))
    finally:
        target.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        print('Evidence: '+str(target))


if __name__=='__main__': main()
