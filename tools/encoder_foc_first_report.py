"""Exact-image decoder for lower-priority encoder IRQs; no device access."""
import struct
import deadline_attribution_report as previous


def decode(elf, ram, flash, vtor):
    result = previous.decode(elf, ram, flash, vtor)
    symbols = previous.pipeline.base.schema.symbols(elf)
    def word(name):
        addr, size = symbols[name]
        off = addr - 0x20000000
        if size != 4 or not 0 <= off <= len(ram) - 4:
            raise ValueError('Invalid encoder diagnostic word: ' + name)
        return struct.unpack_from('<I', ram, off)[0]
    for name in ('TIM2', 'DMA1_CH4_RX', 'DMA1_CH5_TX'):
        irq = result['irq'][name]
        irq['service_wall_cycles_including_children'] = irq.pop('exclusive_total_cycles')
        irq['adc_preemption_contributor'] = False
    values = result['priorities']['values']
    # The firmware inventory checks the enabled TIM6_DAC priority as well.
    result['encoder_priority_verified'] = bool(
        result['priorities']['ok'] and not result['priorities']['unexpected'] and
        values['ADC'] == 2 and all(values[n] == 3 for n in
            ('TIM2', 'DMA1_CH4_RX', 'DMA1_CH5_TX', 'TIM7')))
    result['encoder_events'] = {name: word('encoder_' + name) for name in
        ('deferred_service_count', 'timer_event_count', 'rx_event_count',
         'tx_error_count', 'period_count')}
    result['encoder_preempt_semantics'] = (
        'NVIC-verified lower-priority sources cannot preempt ADC; service wall may include ADC children')
    return result
