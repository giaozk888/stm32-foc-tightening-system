"""Read-only independent RAM/code verification of the PA1-only capture. No reset/halt/write."""
import argparse
import hashlib
import json
import re
import struct
import subprocess
import time
from pathlib import Path
from adc_pa1_only_acceptance import OUTPUT, PINNED, pinned_image
from adc_pa1_only_report import require_status, verify_capture
from adc_parallel_acceptance import CLI, SN, ADDRESSES, ParallelUart
from zero_span100_acceptance import BASES, require_registers
from adc_owner_acceptance import require_owner_service
from zero_retest_deploy import require_confirmed


def main(*, output_dir=OUTPUT, image_hashes=PINNED, image_provider=pinned_image,
         expected_slot="B", capture_mask=2, status_checker=require_status,
         capture_verifier=verify_capture, pass_label="PA1 SWD READBACK",
         pass_description="4096 PA1 values + unsampled zero padding match",
         capacity=4096, stored_channels=3):
    if (capacity, stored_channels) not in ((4096, 3), (8192, 2)):
        raise ValueError("Only exact validated raw layouts admitted")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    args = parser.parse_args()
    capture = json.loads(args.capture.read_text(encoding="utf-8"))
    if (expected_slot not in ("A", "B") or capture.get("capture_pass") is not True or
            capture.get("sha256") != image_hashes[expected_slot] or
            capture.get("after_fw", {}).get("CURRENT") != expected_slot or
            capture.get("all", {}).get("capture_mask") != capture_mask or len(capture.get("triples", [])) != capacity):
        raise RuntimeError("Complete pinned capture required before probe access")
    image_path, image = image_provider(expected_slot)
    symbol_output = subprocess.run([r"D:\software\arm\bin\arm-none-eabi-nm.exe", "-S", "-a",
                                    str(image_path.with_suffix(".elf"))], check=True,
                                   capture_output=True, text=True).stdout
    matches = re.findall(r"(?m)^([0-9a-fA-F]+) ([0-9a-fA-F]+) b raw$", symbol_output)
    if len(matches) != 1:
        raise RuntimeError("Raw-array symbol must be unique")
    address, size = (int(value,16) for value in matches[0])
    if size != capacity*stored_channels*2 or not 0x20000000 <= address < address + size <= 0x2001FFC0:
        raise RuntimeError("Unexpected raw buffer layout")
    prefix = output_dir / f"readback-{time.time_ns()}"
    result = {"pass":False,"capture":str(args.capture),"slot":expected_slot,"raw_address":hex(address),
              "bytes":size,"reset":False,"halt":False,"flash_write":False,"target_ram_write":False,
              "sample_commands":0,"steps":[]}
    port = uart = None
    def cli(*arguments):
        p = subprocess.run([CLI,"-c","port=SWD","mode=HOTPLUG","freq=1000","sn="+SN,
                            *map(str,arguments)],capture_output=True,text=True,errors="replace",timeout=30)
        output=p.stdout+p.stderr
        result["steps"].append({"args":list(map(str,arguments)),"code":p.returncode,"output":output})
        if p.returncode or "Error:" in output: raise RuntimeError("Read-only SWD operation failed")
        return output
    def hardware():
        command=[]
        for a in ADDRESSES: command.extend(("-r32",hex(a),"4"))
        return require_registers(cli(*command),expected_slot)
    def status():
        fw=require_confirmed(uart.query("FW STATUS",3),expected_slot)
        if fw["GEN"] != capture["after_fw"]["GEN"]: raise RuntimeError("Generation changed")
        zero=require_owner_service(uart.query("ZERO STATUS"))
        line=uart.raw_query("ADC PAR STATUS")
        raw=status_checker(line,terminal=True)
        if capture_verifier(line,capture["triples"]) != capture["crc32"]: raise RuntimeError("Capture changed")
        return {"fw":fw,"zero":zero,"raw":raw}
    try:
        result["before_hardware"]=hardware()
        import serial
        port=serial.Serial(port=None,baudrate=115200,timeout=.02,write_timeout=1)
        port.dtr=port.rts=False; port.port="COM5"; port.open(); uart=ParallelUart(port)
        result["before_status"]=status()
        active=prefix.with_suffix(".active-code.bin")
        cli("-u",hex(BASES[expected_slot]),hex(len(image)),active)
        if active.read_bytes() != image: raise RuntimeError("Active image differs from pinned ELF-associated code")
        result["image_sha256"]=hashlib.sha256(image).hexdigest()
        raw_path=prefix.with_suffix(".raw.bin"); cli("-u",hex(address),hex(size),raw_path)
        raw=raw_path.read_bytes()
        if len(raw) != size: raise RuntimeError("Incomplete RAM readback")
        values=struct.unpack(f"<{capacity*stored_channels}H",raw)
        w = values[2*capacity:] if stored_channels == 3 else (0,)*capacity
        triples=list(zip(values[:capacity],values[capacity:2*capacity],w))
        mismatch=[i for i,t in enumerate(triples) if list(t)!=capture["triples"][i]]
        result["mismatched_entries"]=len(mismatch); result["first_mismatches"]=mismatch[:16]
        result["raw_sha256"]=hashlib.sha256(raw).hexdigest()
        if mismatch: raise RuntimeError("Independent RAM differs from UART export")
        line=uart.raw_query("ADC PAR STATUS")
        result["crc32"]=capture_verifier(line,triples)
        result["after_status"]=status(); result["after_hardware"]=hardware()
        result["pass"]=True
        print(pass_label + " PASS: " + pass_description + "; CRC="+result["crc32"],flush=True)
    except BaseException as error:
        result["failure"]=str(error); raise
    finally:
        if port is not None: port.close()
        result["uart"]=uart.lines if uart else []
        prefix.with_suffix(".json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print("Evidence: "+str(prefix.with_suffix(".json")),flush=True)


if __name__ == "__main__": main()
