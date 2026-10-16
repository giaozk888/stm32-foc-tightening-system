"""Pinned locked A failure-neighborhood capture; no motor/bridge commands.
Reuse tested inactive-slot staging with an exact B426 baseline. Separate powered
one-shot reads frozen records only after capture ends; no polling during sampling.
"""
import csv
import re
import isolated_spike_acceptance as base
from switch_feedback_acceptance import Console
SHA='df82475772349bbe91765c1f18003a2ee6bc889927ec78f68e5bbea01a0098a0'
FALLBACK_B='97f9b23bfe9acec0c35246f149cc4a57bde9d539e163f0ce49f989c1527f4b11'

class TraceConsole(base.SpikeConsole):
    def query(self,text,timeout=2):
        if text=='ZERO TRACE STATUS' or re.fullmatch(r'ZERO TRACE (READ|EXTREME) [0-9]{1,3}',text):
            self.request+=1; request=self.request
            self.port.write(f'{request} {text}\r\n'.encode('ascii'))
            until=base.time.monotonic()+timeout
            while base.time.monotonic()<until:
                line=self.read_line(.05)
                if line is None: continue
                self.dispatch(line)
                if line.startswith(f'{request} '):
                    if not line.startswith(f'{request} OK '): raise RuntimeError(line)
                    return line
            raise TimeoutError('No read ACK: '+text)
        return super().query(text,timeout)

def parse_point(line):
    f=base.fields(line)
    p={'index':int(f['INDEX']),'seq':int(f['SEQ']),'mask':int(f['MASK'])}
    for label in ('A','B','C','FILTER'):
        values=tuple(map(int,f[label].split(',')))
        if len(values)!=2 or any(not 0<=v<=4095 for v in values):
            raise RuntimeError('Invalid point codes')
        p[label.lower()]=values
    if p['mask'] not in range(4): raise RuntimeError('Invalid mask')
    expected=0
    for ch in range(2):
        a,b,c=(p[label][ch] for label in ('a','b','c'))
        spike=abs(a-c)<=60 and abs(a-b)>60 and abs(b-c)>60 and (b>max(a,c) or b<min(a,c))
        expected|=int(spike)<<ch
        if p['filter'][ch]!=(a if spike else b): raise RuntimeError('Firmware filter mismatch')
    if p['mask']!=expected: raise RuntimeError('Firmware mask mismatch')
    return p

def collect(uart,record,target):
    line=uart.query('ZERO TRACE STATUS'); meta=base.fields(line)
    record['trace_line']=line; record['trace']=meta
    if meta.get('TRACE')!='1' or meta.get('DONE')!='1' or meta.get('DELAY_PAIRS')!='1':
        raise RuntimeError('Trace is not immutable/complete')
    n=int(meta['ROWS'])
    if not 1<=n<=64: raise RuntimeError('Invalid trace length')
    record['points']=points=[]
    for i in range(n):
        p=parse_point(uart.query(f'ZERO TRACE READ {i}')); points.append(p)
        if p['index']!=i: raise RuntimeError('Index mismatch')
        if i and (p['seq']!=points[i-1]['seq']+1 or
                  p['a']!=points[i-1]['b'] or p['b']!=points[i-1]['c']):
            raise RuntimeError('Raw sample order/overlap mismatch')
    record['extrema']=extrema=[]
    if meta.get('EXTREMA')=='1':
        for i in range(4):
            p=parse_point(uart.query(f'ZERO TRACE EXTREME {i}')); extrema.append(p)
            if p['index']!=i: raise RuntimeError('Witness index mismatch')
    if meta['HIT']=='1':
        trigger=int(meta['CENTER'])
        if meta['REASON']!=record['zero']['REASON']: raise RuntimeError('Failure reason mismatch')
        if int(meta['POST'])!=16 or n!=49 or points[0]['seq']!=trigger-32 or points[-1]['seq']!=trigger+16:
            raise RuntimeError('Missing complete pre/post neighborhood')
        if int(meta['PHYSICAL'])!=int(record['filter']['PAIRS'])+16:
            raise RuntimeError('Calibration/post-sampling accounting mismatch')
        if meta['REASON']=='3' and len(extrema)==4:
            expected=f"{extrema[0]['filter'][0]}:{extrema[1]['filter'][0]},{extrema[2]['filter'][1]}:{extrema[3]['filter'][1]}"
            if expected!=meta['RANGE']: raise RuntimeError('Window extrema evidence mismatch')
    record['neighborhood_csv']=str(target.with_suffix('.csv'))
    with target.with_suffix('.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.writer(stream)
        writer.writerow(('center_seq','relative_to_failure','post_failure_raw_only','raw_u','raw_v','filtered_u','filtered_v','spike_mask','prev_u','prev_v','next_u','next_v'))
        for p in points:
            writer.writerow((p['seq'],p['seq']-int(meta['CENTER']),int(meta['HIT']=='1' and p['seq']>int(meta['CENTER'])),*p['b'],*p['filter'],p['mask'],*p['a'],*p['c']))
    print(line,flush=True)
    print('TRACE READ PASS: chronological raw neighborhood + exact C-filter/mask crosscheck',flush=True)

def configure():
    base.IMAGE=base.ROOT/'foc2_app_a/build/ZeroFailureTrace20261012/foc2.bin'
    base.SHA=SHA; base.OLD_B=FALLBACK_B
    base.OUTPUT=base.ROOT/'safety_backups/zero-failure-trace-20261012'
    base.TARGET_SLOT='A'; base.BASELINE_SLOT='B'; base.BASELINE_GENERATION='426'
    base.SpikeConsole=TraceConsole; base.CAPTURE_EXTRA=collect
    original_image=base.image
    def trace_image():
        data=original_image()
        if b'ZERO_TRACE_%s' not in data or b'TRACE=1 DONE=' not in data:
            raise RuntimeError('Failure trace marker missing')
        return data
    base.image=trace_image

if __name__=='__main__':
    configure(); base.main()
