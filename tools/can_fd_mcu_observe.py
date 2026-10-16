"""Bounded UART read-only queries, retaining secondary CAN HEALTH replies."""
import argparse
import json
from pathlib import Path
import re
import time
import serial

ROOT=Path(__file__).resolve().parents[1]
COMMANDS=('FW STATUS','ANALOG SAFE STATUS','STATUS')


def observe(args):
    evidence=args.evidence.resolve()
    if not evidence.is_relative_to(ROOT/'safety_backups') or evidence.exists() or not 10<=args.seconds<=300:
        raise RuntimeError('Fresh workspace evidence and bounded duration required')
    evidence.mkdir(parents=True)
    bus=serial.Serial(port=None,baudrate=115200,timeout=.1,write_timeout=2)
    bus.dtr=bus.rts=False
    bus.port=args.port
    records=[]
    started=time.monotonic()
    sequence=57000
    try:
        bus.open()
        with (evidence/'mcu.jsonl').open('x',encoding='utf-8') as stream:
            print('MCU OBSERVER READY: fixed read-only commands; DTR/RTS false',flush=True)
            while time.monotonic()-started<args.seconds:
                for command in COMMANDS:
                    sequence+=1
                    bus.write(f'{sequence} {command}\r\n'.encode())
                    deadline=time.monotonic()+5
                    got=False
                    tail_deadline=deadline
                    while time.monotonic()<tail_deadline:
                        line=bus.readline().decode(errors='replace').strip()
                        matching=line.startswith(f'{sequence} OK ') or line.startswith(f'{sequence} ERR ')
                        health=line.startswith('CAN HEALTH ')
                        if matching or health:
                            record={'elapsed_s':time.monotonic()-started,'query':command,'line':line}
                            stream.write(json.dumps(record)+'\n');stream.flush()
                            records.append(record)
                            if matching:
                                if ' ERR ' in line: raise RuntimeError(line)
                                got=True;tail_deadline=time.monotonic()+.18
                            if command=='ANALOG SAFE STATUS' and matching and 'LATCHED=1 SD=0 MOE=0 FOC=0' not in line:
                                raise RuntimeError('Power-off safe latch not proven')
                            if health:
                                print(line,flush=True)
                            if command=='FW STATUS' and matching and not all(k in line for k in
                                ('CURRENT=B','CONFIRMED=B','PENDING=-','ACTIVE=0')):
                                raise RuntimeError('Unexpected running MCU slot')
                    if not got: raise TimeoutError(command)
                time.sleep(.2)
    finally:
        if bus.is_open:bus.close()
        (evidence/'summary.json').write_text(json.dumps({'records':records,'motor_commands_sent':False,
            'commands':list(COMMANDS),'duration_s':time.monotonic()-started},indent=2),encoding='utf-8')
        print('MCU OBSERVER STOPPED',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',default='COM5')
    parser.add_argument('--evidence',required=True,type=Path)
    parser.add_argument('--seconds',type=int,default=180)
    observe(parser.parse_args())
