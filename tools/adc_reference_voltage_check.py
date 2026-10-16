"""Read-only check of locked reference B and cached supply estimates. No SAMPLE/reset."""
import json
import subprocess
import time
from adc_reference_acceptance import OUTPUT, require_fresh_reference
from adc_reference_sample import ReferenceUart
from adc_parallel_acceptance import CLI, SN, ADDRESSES, require_registers
from zero_retest_deploy import require_confirmed
from zero_retest_sample import fields


def main():
    prefix=OUTPUT/f"voltage-check-{time.time_ns()}"
    result={"pass":False,"sample_commands":0,"motion_commands":False,"reset":False,
            "flash_write":False,"halt":False,"target_ram_write":False,"steps":[]}
    port=None
    def read(addresses):
        command=[]
        for a in addresses: command.extend(("-r32",hex(a),"4"))
        p=subprocess.run([CLI,"-c","port=SWD","mode=HOTPLUG","freq=1000","sn="+SN,*command],
                         capture_output=True,text=True,errors="replace",timeout=30)
        output=p.stdout+p.stderr
        result["steps"].append({"args":command,"code":p.returncode,"output":output})
        if p.returncode or "Error:" in output: raise RuntimeError("Read-only probe failed")
        return output
    try:
        result["before_registers"]=require_registers(read(ADDRESSES),"B")
        import serial
        port=serial.Serial(port=None,baudrate=115200,timeout=.02,write_timeout=1)
        port.dtr=port.rts=False; port.port="COM5"; port.open(); uart=ReferenceUart(port)
        result["fw"]=require_confirmed(uart.query("FW STATUS",3),"B")
        result["fresh_service"]=require_fresh_reference(uart)
        result["voltages"]=[]
        for _ in range(3):
            result["voltages"].append(fields(uart.query("ANALOG VOLT")))
            time.sleep(.15)
        result["uart"]=uart.lines; port.close(); port=None
        # GPIOC analog mode/pull, ADC2 regular mux, ELF-associated cached PC4/5
        # pair. Background owner continues; this is not a simultaneous snapshot.
        result["diagnostic_register_output"]=read((0x48000800,0x4800080C,0x50000130,0x20002DBC))
        result["cached_raw_word_address_source"]="AdcReference20261010 ELF analog_live_pc5_raw=0x20002DBC, pc4_raw=0x20002DBE"
        result["not_simultaneous_with_uart_voltage"] = True
        result["after_registers"]=require_registers(read(ADDRESSES),"B")
        result["pass"]=True
        print(json.dumps({"fw":result["fw"],"estimates":result["voltages"],
                          "diagnostic_register_output":result["diagnostic_register_output"]},ensure_ascii=False),flush=True)
    except BaseException as error:
        result["failure"]=str(error); raise
    finally:
        if port is not None: port.close()
        prefix.with_suffix(".json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print("Evidence: "+str(prefix.with_suffix(".json")),flush=True)


if __name__ == "__main__": main()
