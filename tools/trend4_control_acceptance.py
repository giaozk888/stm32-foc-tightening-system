"""Stage the pinned hard-off Trend4 compute B from exact locked A429.

Drive 12 V must be physically off. Only official UART pw_transfer can write
the inactive APP. This phase never commits, resets, samples or enables power.
Flash captures contain private configuration and stay in the restricted folder.
"""
import argparse
import hashlib
import json
import struct
import subprocess
import time
from firmware_transfer_iap import ROOT, DEFAULT_CLIENT, image_info, stage
from median_control_acceptance import Console
from zero_async_clock_acceptance import locked_baseline
from zero_retest_deploy import CLI, SN, compare_flash, require_confirmed, require_service
from zero_span100_acceptance import ADDRESSES, require_registers
from powered_boot_probe import require_staged
from stable_zero_acceptance import fields

IMAGE=ROOT/'foc2_app_b/build/Trend4Compute20261013/foc2.bin'
SHA='f28c542de515976dba674e139a624763d15fdf536ca6e570cfc7a712df73d7a1'
OLD_A='df82475772349bbe91765c1f18003a2ee6bc889927ec78f68e5bbea01a0098a0'
OLD_B='97f9b23bfe9acec0c35246f149cc4a57bde9d539e163f0ce49f989c1527f4b11'
OUTPUT=ROOT/'safety_backups/trend4-control-20261013'
BASELINE_GENERATION=429

def image():
    data=IMAGE.read_bytes()
    if image_info(data)[0]!='B' or hashlib.sha256(data).hexdigest()!=SHA:
        raise RuntimeError('Exact offline-tested Trend4 B required')
    for marker in (b'MEDIAN=0 SPIKE3=0 TREND4=1 DELAY_PAIRS=1 FILTER_REV=3',
                   b'COMPUTE_ONLY=1 MOTOR_QUALIFIED=0',b'SD=MOE=CCER=0'):
        if marker not in data: raise RuntimeError('Missing hard-off/four-point marker')
    if b'OPEN_LOAD_ONLY' in data: raise RuntimeError('No bridge-switching profile')
    pc=(struct.unpack_from('<I',data,4)[0]&~1)-0x08040000
    if data[pc:pc+2]!=b'\x72\xb6': raise RuntimeError('Reset IRQ mask missing')
    return data

def baseline(data):
    row=locked_baseline(data,known={'A':frozenset((OLD_A,)),'B':frozenset((OLD_B,))})
    if row['current']!='A' or row['generation']!=BASELINE_GENERATION:
        raise RuntimeError('Require exact confirmed locked A429; never guess inactive slot')
    return row

class StageConsole(Console):
    def __init__(self,port): super().__init__(port,commit=False)
    def query(self,text,timeout=2):
        if text not in ('FW STATUS','ZERO STATUS','ANALOG SAFE STATUS'):
            raise ValueError('Stage permits read-only service queries only')
        return super().query(text,timeout)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('stage',))
    parser.add_argument('--drive-12v-off',action='store_true')
    args=parser.parse_args()
    if not args.drive_12v_off: parser.error('Physically OFF drive power required')
    data=image()
    if not DEFAULT_CLIENT.is_file(): raise RuntimeError('Official native transfer client missing')
    OUTPUT.mkdir(parents=True,exist_ok=True)
    private=OUTPUT/'private'; private.mkdir(exist_ok=True)
    subprocess.run(['icacls',str(private),'/inheritance:r','/grant:r',
                    '*S-1-5-18:(OI)(CI)F','*S-1-5-32-544:(OI)(CI)F'],
                   check=True,capture_output=True)
    run=str(time.time_ns()); target=OUTPUT/f'stage-{run}.json'
    record=dict(pass_=False,mode='stage',image_sha256=SHA,steps=[],
                motion_commands=False,reset_requested=False,force_confirm=False,
                motor_qualified=False,automatic_retry=False)
    port=uart=None
    def cli(*tokens):
        if tokens[0] not in ('-u','-r32'): raise ValueError('Read-only SWD probe')
        result=subprocess.run([CLI,'-c','port=SWD','mode=HOTPLUG','freq=1000','sn='+SN,
                               *map(str,tokens)],capture_output=True,text=True,
                              errors='replace',timeout=30)
        out=result.stdout+result.stderr
        record['steps'].append(dict(args=list(map(str,tokens)),code=result.returncode,output=out))
        if result.returncode or 'Error:' in out: raise RuntimeError('SWD read failed; no retry')
        return out
    def outputs():
        return require_registers(cli(*(x for a in ADDRESSES for x in ('-r32',hex(a),'4'))),'A')
    def capture(name):
        path=private/f'{run}-{name}.bin'
        cli('-u','0x08000000','0x80000',path)
        content=path.read_bytes()
        if len(content)!=0x80000: raise RuntimeError('Incomplete private backup')
        record[name+'_backup']=str(path)
        return content
    try:
        import serial
        port=serial.Serial(port=None,baudrate=115200,timeout=.02,write_timeout=2)
        port.dtr=port.rts=False; port.port='COM5'; port.open()
        uart=StageConsole(port)
        record['before_fw']=fw=require_confirmed(uart.query('FW STATUS'),'A')
        if int(fw['GEN'])!=BASELINE_GENERATION: raise RuntimeError('Unexpected generation')
        record['before_zero']=require_service(uart.query('ZERO STATUS'))
        record['before_outputs']=outputs()
        original=capture('before'); record['baseline']=baseline(original)
        stage(uart,IMAGE,DEFAULT_CLIENT,allow_reset=False)
        staged=capture('staged')
        record['protected_flash']=compare_flash(original,staged,data,'B',staged=True)
        if original[:0x40000]!=staged[:0x40000] or original[0x78000:]!=staged[0x78000:]:
            raise RuntimeError('Bytes outside inactive B changed')
        record['after_outputs']=outputs()
        line=uart.query('FW STATUS'); require_staged(line,'SOURCE=SWD SD=0 MOE=0 CEN=0',data)
        record['staged_fw']=fields(line)
        if record['staged_fw']['GEN']!=str(BASELINE_GENERATION):
            raise RuntimeError('Staging changed metadata generation')
        record['after_zero']=require_service(uart.query('ZERO STATUS'))
        record['pass_']=True
        print('TREND4 STAGE PASS: B exact; A/bootloader/KVS/parameters/metadata unchanged; NO RESET.',flush=True)
    except BaseException as error:
        record['failure']=str(error)
        raise
    finally:
        if uart: record['uart']=uart.lines
        if port: port.close()
        target.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print('Evidence: '+str(target),flush=True)

if __name__=='__main__': main()
