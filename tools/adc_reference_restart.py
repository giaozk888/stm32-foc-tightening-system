"""One authorized hard-locked B reset between OFF/ON runs; never Flash/SAMPLE."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time
from adc_reference_acceptance import OUTPUT, PINNED, pinned_image, require_fresh_reference
from adc_reference_sample import deployment_identity, ReferenceUart
from adc_reference_report import require_status, require_supply
from adc_parallel_acceptance import CLI, SN, ADDRESSES, require_registers
from adc_owner_acceptance import require_owner_service
from zero_retest_deploy import require_confirmed
from zero_span100_acceptance import BASES


def prior_identity(deployment, capture, readback):
    slot, generation = deployment_identity(deployment)
    if (capture.get("capture_pass") is not True or capture.get("sha256") != PINNED["B"] or
            capture.get("after_fw", {}).get("CURRENT") != slot or
            capture.get("after_fw", {}).get("GEN") != generation or
            capture.get("requested_supply_state") != "OFF" or
            capture.get("terminal", {}).get("POWER") != "OFF" or
            readback.get("pass") is not True or readback.get("slot") != slot or
            readback.get("image_sha256") != PINNED["B"] or
            readback.get("mismatched_entries") != 0 or
            readback.get("crc32") != capture.get("crc32") or
            readback.get("after_status", {}).get("fw", {}).get("GEN") != generation):
        raise RuntimeError("Exact successful OFF capture and independent RAM verification required")
    return slot, generation, capture["crc32"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("deployment", "capture", "readback"):
        parser.add_argument("--"+name, type=Path, required=True)
    for name in ("allow-one-reset", "drive-12v-off", "motor-leads-disconnected"):
        parser.add_argument("--"+name, action="store_true")
    args = parser.parse_args()
    if not (args.allow_one_reset and args.drive_12v_off and args.motor_leads_disconnected):
        parser.error("Current authorized reset, power-off and disconnected conditions required")
    slot, generation, prior_crc = prior_identity(*[
        json.loads(getattr(args,n).read_text(encoding="utf-8")) for n in ("deployment","capture","readback")])
    _, image = pinned_image(slot)
    prefix = OUTPUT / f"reset-{time.time_ns()}"
    result = {"pass":False,"reset_user_authorized":True,"drive_12v_off_user_confirmed":True,
              "motor_leads_disconnected_user_confirmed":True,"reset_commands":0,"sample_commands":0,
              "flash_write":False,"target_ram_write":False,"halt":False,"motion_commands":False,"steps":[],
              "deployment":str(args.deployment),"prior_capture":str(args.capture),"prior_readback":str(args.readback)}
    port = None

    def cli(*arguments):
        p = subprocess.run([CLI,"-c","port=SWD","mode=HOTPLUG","freq=1000","sn="+SN,
                            *map(str,arguments)],capture_output=True,text=True,errors="replace",timeout=30)
        output = p.stdout+p.stderr
        result["steps"].append({"args":list(map(str,arguments)),"code":p.returncode,"output":output})
        if p.returncode or "Error:" in output:
            raise RuntimeError("SWD operation failed; never retry reset")
        return output

    def hardware():
        command=[]
        for a in ADDRESSES: command.extend(("-r32",hex(a),"4"))
        return require_registers(cli(*command),slot)

    def code_check(suffix):
        path=prefix.with_suffix(suffix)
        cli("-u",hex(BASES[slot]),hex(len(image)),path)
        if path.read_bytes() != image: raise RuntimeError("Exact hard-locked B code mismatch")
        return hashlib.sha256(image).hexdigest()

    def console():
        import serial
        p=serial.Serial(port=None,baudrate=115200,timeout=.02,write_timeout=1)
        p.dtr=p.rts=False; p.port="COM5"; p.open()
        return p, ReferenceUart(p)

    try:
        result["before_hardware"]=hardware(); result["before_image_sha256"]=code_check(".before-code.bin")
        port,uart=console()
        result["before_fw"]=require_confirmed(uart.query("FW STATUS",3),slot)
        if result["before_fw"]["GEN"] != generation: raise RuntimeError("Generation changed before reset")
        result["before_zero"]=require_owner_service(uart.query("ZERO STATUS"))
        result["before_raw"]=require_status(uart.raw_query("ADC PAR STATUS"),terminal=True,power="OFF")
        if result["before_raw"]["CRC"] != prior_crc: raise RuntimeError("Prior OFF capture changed")
        result["supply_off_estimate"]=require_supply(uart.query("ANALOG VOLT"),"OFF")
        result["before_uart"]=uart.lines; port.close(); port=None
        result["reset_commands"]=1; cli("-rst")
        print("One locked reset issued; wait 25 s before startup query; no SAMPLE.",flush=True)
        time.sleep(25)
        port,uart=console()
        result["after_fw"]=require_confirmed(uart.query("FW STATUS",5),slot)
        if result["after_fw"]["GEN"] != generation: raise RuntimeError("Generation changed after reset")
        result["fresh_service"]=require_fresh_reference(uart)
        result["after_uart"]=uart.lines; port.close(); port=None
        result["after_hardware"]=hardware(); result["after_image_sha256"]=code_check(".after-code.bin")
        result["pass"]=True
        print("REFERENCE RESET PASS: same confirmed B, fresh unsampled, outputs locked; no Flash.",flush=True)
    except BaseException as error:
        result["failure"]=str(error); raise
    finally:
        if port is not None: port.close()
        prefix.with_suffix(".json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print("Evidence: "+str(prefix.with_suffix(".json")),flush=True)


if __name__ == "__main__": main()
