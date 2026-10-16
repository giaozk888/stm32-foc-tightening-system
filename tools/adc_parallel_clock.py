"""Read-only register proof for ADC12 + ADC345 SYSCLK/4 and PA8 analog."""
import re
from foc_adc_ram_test import require_async_adc_clock
CLOCK_ADDRESSES = (0x50000308, 0x50000708, 0x40021088, 0x40012C28, 0x40012C2C,
                   0x48000000, 0x4800000C)
def require_async_registers(output):
    regs = {int(a,16):int(v,16) for a,v in re.findall(
        r"(?im)^0x([0-9A-F]+)\s*:\s*([0-9A-F]{8})\s*$",output)}
    if set(regs) != set(CLOCK_ADDRESSES):
        raise RuntimeError("Incomplete parallel ADC clock/pin readback")
    require_async_adc_clock(regs[0x50000308], regs[0x40021088])
    if (regs[0x50000708] & 0x003F001F) != 0x00080000:
        raise RuntimeError("ADC345 must be independent asynchronous /4")
    if (regs[0x40021088] & 0xC0000000) != 0x80000000:
        raise RuntimeError("ADC345 kernel must use SYSCLK")
    if regs[0x40012C28] != 0 or regs[0x40012C2C] != 4249:
        raise RuntimeError("TIM1 geometry changed")
    if ((regs[0x48000000] >> 16) & 3) != 3 or ((regs[0x4800000C] >> 16) & 3) != 0:
        raise RuntimeError("PA8 must be analog, without pull-up/down")
    return {f"0x{a:08X}":f"{v:08X}" for a,v in regs.items()}
