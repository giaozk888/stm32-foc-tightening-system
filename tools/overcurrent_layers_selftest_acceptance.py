"""One pinned inactive-B synthetic selftest deployment; never energizes power.

Requires explicitly authorized diagnostic flash/reset and physical drive 12 V
OFF. Only official local UART pw_transfer writes APP B; SWD is read-only.
No sampling, motion, force-confirmation, parameter write or automatic retry.
Full Flash captures contain private configuration: administrator/SYSTEM only.
"""
import argparse
import hashlib
import json
import struct
import subprocess
import time
import zlib
from firmware_transfer_iap import ROOT, Uart, stage, image_info, DEFAULT_CLIENT, fields
from zero_retest_deploy import CLI, SN, DiagnosticUart, compare_flash, latest_meta, require_confirmed, require_service
from zero_span100_acceptance import ADDRESSES, require_registers, require_new_service, observe_trial
from powered_boot_probe import require_staged

IMAGE=ROOT/'foc2_app_b/build/OvercurrentLayersSelftest20261013/foc2.bin'
SHA='eaf40163a8f8e957d170abb1f27f4ebe03384fb0b93ef09d33a48f7ede5b467b'
OLD_A='df82475772349bbe91765c1f18003a2ee6bc889927ec78f68e5bbea01a0098a0'
OLD_B='f28c542de515976dba674e139a624763d15fdf536ca6e570cfc7a712df73d7a1'
OUTPUT=ROOT/'safety_backups/overcurrent-layers-selftest-20261013'
GEN=433

def image():
    data=IMAGE.read_bytes()
    if image_info(data)[0]!='B' or hashlib.sha256(data).hexdigest()!=SHA:
        raise RuntimeError('Exact offline-tested locked selftest B required')
    for marker in (b'OC_LAYERS INPUT=SYNTHETIC', b'HARD_SIM_MA=5000 ACTUAL_LIMIT_MA=4000',
                   b'SYNTHETIC_SELFTEST_ONLY_NO_ACQUISITION'):
        if marker not in data: raise RuntimeError('Selftest marker absent')
    if b'OPEN_LOAD_ONLY' in data: raise RuntimeError('Switching profile forbidden')
    pc=(struct.unpack_from('<I',data,4)[0]&~1)-0x08040000
    if data[pc:pc+2]!=b'\x72\xb6': raise RuntimeError('Reset IRQ mask absent')
    return data

def baseline(data):
    if len(data)!=0x80000: raise RuntimeError('Complete baseline required')
    m=latest_meta(data)
    if m[2:6]!=(1,0,0,GEN) or m[8:10]!=(0,0) or m[6]!=146636:
        raise RuntimeError('Only exact confirmed A433 with rolled-back B admitted')
    a=data[0x8000:0x8000+m[6]]
    b=data[0x40000:0x40000+203928]
    if (hashlib.sha256(a).hexdigest()!=OLD_A or zlib.crc32(a)!=m[7] or
            hashlib.sha256(b).hexdigest()!=OLD_B):
        raise RuntimeError('Active A or physical old B does not match preserved artifacts')
    return dict(current='A',generation=m[5],fallback_sha256=OLD_A,
                old_B_sha256=OLD_B,old_B_metadata_invalidated=True)

def require_selftest(line):
    row=fields(line)
    expected=(('INPUT','SYNTHETIC'),('DONE','1'),('CASES','6'),('CHECKS','36'),
              ('FAIL','0x00000000'),('SOFT_MA','4000'),('HARD_SIM_MA','5000'),
              ('ACTUAL_LIMIT_MA','4000'),('LOCK','1'),('MOTOR_QUALIFIED','0'))
    if any(row.get(k)!=v for k,v in expected):
        raise RuntimeError('Synthetic selftest failed or output lock absent: '+line)
    return row

class Console(DiagnosticUart):
    def __init__(self,port):
        super().__init__(port); self.commit_ready=False; self.ends=0
    def dispatch(self,line):
        super().dispatch(line); Uart.dispatch(self,line)
    def query(self,text,timeout=2):
        if text not in ('FW STATUS','ZERO STATUS','ANALOG SAFE STATUS','OC LAYERS SELFTEST'):
            raise ValueError('Read-only locked queries only')
        self.request+=1
        self.port.write(f'{self.request} {text}\r\n'.encode('ascii'))
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            line=self.read_line(.05)
            if line is None: continue
            self.dispatch(line)
            if line.startswith(f'{self.request} '):
                if not line.startswith(f'{self.request} OK '): raise RuntimeError(line)
                return line
        raise TimeoutError('No reply: '+text)
    def command(self,text,timeout=5):
        if text=='FW END':
            if not self.commit_ready or self.ends: raise ValueError('One readback-verified commit only')
            self.ends+=1
        elif self.commit_ready:
            raise ValueError('No additional stage after commit admission')
        return super().command(text,timeout)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-deploy',action='store_true')
    parser.add_argument('--drive-12v-off',action='store_true')
    args=parser.parse_args()
    if not args.allow_deploy or not args.drive_12v_off:
        parser.error('Explicit diagnostic flash/reset authorization and physical drive OFF required')
    data=image()
    if not DEFAULT_CLIENT.is_file(): raise RuntimeError('Official native client missing')
    OUTPUT.mkdir(parents=True,exist_ok=True)
    private=OUTPUT/'private'; private.mkdir(exist_ok=True)
    subprocess.run(['icacls',str(private),'/inheritance:r','/grant:r',
                    '*S-1-5-18:(OI)(CI)F','*S-1-5-32-544:(OI)(CI)F'],
                   check=True,capture_output=True)
    run=str(time.time_ns()); target=OUTPUT/f'deploy-{run}.json'
    record=dict(pass_=False,input='synthetic',image_sha256=SHA,steps=[],
                motion_commands=False,current_sampling=False,force_confirm=False,
                existing_auxiliary_analog_monitor=True,
                motor_qualified=False,actual_current_limit_A=4,simulated_boundary_A=5,
                automatic_retry=False,direct_flash_write=False)
    port=uart=None
    def cli(*tokens):
        if tokens[0] not in ('-u','-r32'): raise ValueError('Read-only SWD only')
        p=subprocess.run([CLI,'-c','port=SWD','mode=HOTPLUG','freq=1000','sn='+SN,
                          *map(str,tokens)],capture_output=True,text=True,errors='replace',timeout=30)
        out=p.stdout+p.stderr
        record['steps'].append(dict(args=list(map(str,tokens)),code=p.returncode,output=out))
        if p.returncode or 'Error:' in out: raise RuntimeError('Read failed; no reset/retry')
        return out
    def outputs(slot):
        return require_registers(cli(*(x for a in ADDRESSES for x in ('-r32',hex(a),'4'))),slot)
    def capture(name):
        path=private/f'{run}-{name}.bin'; cli('-u','0x08000000','0x80000',path)
        content=path.read_bytes()
        if len(content)!=0x80000: raise RuntimeError('Incomplete private backup')
        record[name+'_backup']=str(path)
        return content
    try:
        import serial
        port=serial.Serial(port=None,baudrate=115200,timeout=.02,write_timeout=2)
        port.dtr=port.rts=False; port.port='COM5'; port.open(); uart=Console(port)
        record['before_fw']=fw=require_confirmed(uart.query('FW STATUS'),'A')
        if int(fw['GEN'])!=GEN: raise RuntimeError('Unexpected baseline generation')
        record['before_zero']=require_service(uart.query('ZERO STATUS'))
        record['before_outputs']=outputs('A')
        original=capture('before'); record['baseline']=baseline(original)
        print('BASELINE PASS: exact A433; output lock and full private backup verified.',flush=True)
        stage(uart,IMAGE,DEFAULT_CLIENT,allow_reset=False)
        staged=capture('staged')
        record['staged_flash']=compare_flash(original,staged,data,'B',staged=True)
        if original[:0x40000]!=staged[:0x40000] or original[0x78000:]!=staged[0x78000:]:
            raise RuntimeError('Staging changed bytes outside inactive B')
        record['staged_outputs']=outputs('A')
        fw=uart.query('FW STATUS')
        require_staged(fw,'SOURCE=SWD SD=0 MOE=0 CEN=0',data)
        if fields(fw)['GEN']!=str(GEN): raise RuntimeError('Staging changed generation')
        require_service(uart.query('ZERO STATUS'))
        uart.commit_ready=True
        print('READBACK PASS: B exact; all other Flash unchanged. Requesting one locked trial.',flush=True)
        try:
            record['commit_reply']=uart.command('FW END',20)
        except TimeoutError:
            record['commit_ack_timeout']=True  # outcome unknown: observe only, NEVER resend
        record['trial_fw']=observe_trial(uart,'B')
        # BootMeta confirmation precedes the APP's automatic reset by 150 ms.
        # Drain through reset, then verify the confirmed service freshly.
        until=time.monotonic()+2
        while time.monotonic()<until: uart.poll(.05)
        record['selftest']=require_selftest(uart.query('OC LAYERS SELFTEST',3))
        for _ in range(10):
            require_new_service(uart.query('ZERO STATUS'))
            interval=time.monotonic()+.3
            while time.monotonic()<interval: uart.poll(min(.05,interval-time.monotonic()))
        record['final_fw']=require_confirmed(uart.query('FW STATUS'),'B')
        record['final_zero']=require_new_service(uart.query('ZERO STATUS'))
        record['selftest_after_reset']=require_selftest(uart.query('OC LAYERS SELFTEST'))
        record['final_outputs']=outputs('B')
        actual=capture('final')
        record['final_flash']=compare_flash(original,actual,data,'B')
        record['pass_']=True
        print('MCU SYNTHETIC SELFTEST PASS: 6 cases, 36 checks; B normally confirmed; outputs locked; NOT motor qualification.',flush=True)
    except BaseException as error:
        record['failure']=str(error)
        raise
    finally:
        if uart: record['uart']=uart.lines
        if port: port.close()
        target.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print('Evidence: '+str(target),flush=True)

if __name__=='__main__': main()
