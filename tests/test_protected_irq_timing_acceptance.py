import unittest
from pathlib import Path
from unittest.mock import patch
import protected_irq_timing_acceptance as accept

class TimingAcceptanceTests(unittest.TestCase):
    def test_new_profile_cost_collected_without_changing_legacy_queries(self):
        class Uart:
            def __init__(self): self.calls=[]
            def query(self,cmd):
                self.calls.append(cmd); return 'OK TRIG=POLY9_8 DWT=1 CPU_MAX_CYC=200'
            def encoder_diag(self): return {'dma':{}}
        uart=Uart()
        with patch.object(accept,'profile',type('Profile',(),{'REQUIRE_COST':True})):
            row=accept.read_sample(uart)
        self.assertEqual(row['cost']['CPU_MAX_CYC'],'200')
        self.assertEqual(uart.calls.count('MOTOR TEST COST'),1)
        uart=Uart()
        with patch.object(accept,'profile',type('Profile',(),{})):
            self.assertNotIn('cost',accept.read_sample(uart))
        self.assertNotIn('MOTOR TEST COST',uart.calls)
    def test_no_motion_or_fault_clear_even_before_write(self):
        class Port:
            def write(self,_): raise AssertionError('Must not touch UART')
        uart=accept.TimingConsole(Port())
        for cmd in ('MOTOR TEST SPEED','MOTOR TEST STOP','START','CLEAR','BOOT A','FW CONFIRM'):
            with self.subTest(cmd=cmd),self.assertRaises(ValueError): uart.query(cmd)
        uart.ends=1
        with self.assertRaises(ValueError): uart.query('FW END')
    def test_adc_budget_and_pair_checks(self):
        good='OK IRQ=90000 PAIRS=90000 MISS=0 PF=0 DWT=1 MAX_CYC=4000 LATE=9000'
        # LATE is an explicitly coarse remaining-to-boundary alarm, not a
        # counted dropped sample. Preserve it, but don't invent a zero value.
        self.assertEqual(accept.adc_timing(good)['LATE'],'9000')
        for a,b in (('MISS=0','MISS=1'),('PF=0','PF=1'),('DWT=1','DWT=0'),
                    ('MAX_CYC=4000','MAX_CYC=8500'),('MAX_CYC=4000','MAX_CYC=0')):
            with self.subTest(a=a),self.assertRaises(RuntimeError): accept.adc_timing(good.replace(a,b))
    def test_exact_profile_and_safe_cleanup_contract(self):
        source=Path(accept.__file__).read_text('utf-8')
        self.assertIn('source_profile=profile',source)
        self.assertIn("board.outputs('B',True)",source)
        self.assertIn("uart.query('ANALOG SAFE')",source)
        self.assertNotIn("uart.query('MOTOR TEST SPEED')",source)
        self.assertIn("slot,False",source)
    def test_encoder_fault_lines_collected_without_second_command(self):
        class Port:
            def __init__(self): self.rx=bytearray(); self.writes=[]
            @property
            def in_waiting(self): return len(self.rx)
            def write(self,data):
                self.writes.append(data)
                request=data.decode('ascii').split()[0]
                for body in (
                    'ENC DMA READS=53 FAIL=1 TIMEOUT=1 ST=2',
                    'ENC SNAP VALID=1 ST=2 PH=2 FR=0 START=100 NOW=300 DUE=300 GUARD=102 IPSR=28',
                    'ENC SPI SR=0x00000082 CR1=0x1 CR2=0x2 TIM_SR=0x1 TIM_DIER=0x1',
                    'ENC DMAHW ISR=0x00001000 RX_NDTR=0 TX_NDTR=0 RX_CCR=0x1 TX_CCR=0x1',
                    'ENC IRQ VALID=1 NOW=300 SR=0x4 DIER=0x6 CCR2=260 LATE_US=40 MAX_LATE_US=40',
                    'ENC DIAG DWT=1 READS=53 FAIL=1',
                    'ENC STACK VALID=1 FREE_B=1856 SAMPLES=31'):
                    self.rx.extend(f'{request} OK {body}\r\n'.encode('ascii'))
            def read(self,n):
                data=bytes(self.rx[:n]); del self.rx[:n]; return data
        port=Port(); uart=accept.TimingConsole(port)
        result=uart.encoder_diag()
        self.assertEqual(len(port.writes),1)
        self.assertEqual(result['snapshot']['PH'],'2')
        self.assertEqual(result['dma_hw']['RX_NDTR'],'0')
        self.assertEqual(result['spi']['SR'],'0x00000082')
        self.assertEqual(result['spi']['CR1'],'0x1')
        self.assertEqual(result['spi']['CR2'],'0x2')
        self.assertEqual(result['irq']['CCR2'],'260')
        self.assertEqual(result['irq']['LATE_US'],'40')
        self.assertEqual(result['stack']['FREE_B'],'1856')

if __name__=='__main__': unittest.main()
