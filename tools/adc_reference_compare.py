"""Offline OFF/ON known-input audit, no hardware calls and no outlier removal."""
import argparse
import json
from pathlib import Path
import statistics
from adc_reference_acceptance import PINNED
from adc_reference_report import verify_capture, require_status, require_supply, analyze


def audit_capture(capture, readback, power):
    if (capture.get("capture_pass") is not True or capture.get("sha256") != PINNED["B"] or
            capture.get("requested_supply_state") != power or capture.get("sample_commands") != 1 or
            capture.get("motion_commands") is not False or capture.get("thresholds_changed") is not False or
            capture.get("reset") is not False or capture.get("flash_write") is not False or
            not capture.get("host_quiet_after_sample_ack") or
            readback.get("pass") is not True or readback.get("image_sha256") != PINNED["B"] or
            readback.get("slot") != "B" or readback.get("mismatched_entries") != 0 or
            readback.get("crc32") != capture.get("crc32") or
            readback.get("after_status", {}).get("fw", {}).get("GEN") != capture.get("after_fw", {}).get("GEN")):
        raise ValueError("Exact one-shot, hard-locked capture and independent RAM audit required")
    fw=capture.get("after_fw",{})
    if any(fw.get(k) != v for k,v in (("CURRENT","B"),("CONFIRMED","B"),("ACTIVE","0"),("ATTEMPTS","0"),("PENDING","-"))):
        raise ValueError("Normally confirmed B required")
    triples=capture.get("triples",[])
    lines=[s for s in capture.get("uart",[]) if " OK ADC3PAR " in s and
           f"CRC={capture.get('crc32')}" in s and "STATE=4 " in s]
    if not lines: raise ValueError("Full terminal raw proof missing")
    for line in lines:
        if verify_capture(line,triples,power=power) != capture["crc32"]:
            raise ValueError("Whole capture CRC proof failed")
        require_status(line,terminal=True,power=power)
    supply=capture.get("supply_estimate",{})
    require_supply("1 OK ANALOG VOLT "+" ".join(f"{k}={v}" for k,v in supply.items()),power)
    result={"crc32":capture["crc32"],"generation":fw["GEN"],"power":power,"all":analyze(triples),
            "admission_bus_mv":int(capture["terminal"]["ADMIT_MV"]),
            "raw_uart_ram_match":True,"all_samples_retained":True,"filtering":False,
            "motor_qualified":False,"current_feedback_qualified":False}
    u,v=([t[i] for t in triples] for i in (0,1))
    mu,mv=statistics.median(u),statistics.median(v)
    du,dv=([x-mu for x in u],[x-mv for x in v])
    diff=[a-b for a,b in zip(u,v)]
    result["u_minus_v"]={"mean":statistics.mean(diff),"median":statistics.median(diff),
                         "stddev":statistics.pstdev(diff),"min":min(diff),"max":max(diff)}
    result["pearson_all_samples"]=(statistics.correlation(u,v) if statistics.pstdev(u) and statistics.pstdev(v) else None)
    result["deviation_from_each_channel_median"]={}
    for limit in (20,40,100):
        ui=[i for i,x in enumerate(du) if abs(x)>limit]; vi=[i for i,x in enumerate(dv) if abs(x)>limit]
        common=sorted(set(ui)&set(vi)); union=sorted(set(ui)|set(vi))
        result["deviation_from_each_channel_median"][str(limit)]={
            "strict_greater_than_counts":limit,"u_count":len(ui),"v_count":len(vi),
            "common_count":len(common),"union_count":len(union),
            "same_sign_common_count":sum(du[i]*dv[i]>0 for i in common),
            "indices_union":union,
            "events_union":[{"index":i,"u":u[i],"v":v[i],"du":du[i],"dv":dv[i]} for i in union]}
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("off","off-readback","on","on-readback","output"):
        parser.add_argument("--"+name,type=Path,required=True)
    args=parser.parse_args()
    off,on=(audit_capture(json.loads(getattr(args,p).read_text(encoding="utf-8")),
                          json.loads(getattr(args,p+"_readback").read_text(encoding="utf-8")),p.upper()) for p in ("off","on"))
    if off["generation"] != on["generation"]: raise ValueError("Different metadata generations; not same-image contrast")
    result={"off":off,"on":on,"same_image_sha256":PINNED["B"],"same_generation":True,
            "short_different_boots_not_failure_rate_measurement":True,
            "causal_root_cause_proven":False,"industrial_qualification":False,
            "source_paths":{n:str(getattr(args,n)) for n in ("off","off_readback","on","on_readback")}}
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({p:{"crc32":r["crc32"],"U":r["all"]["U"],"V":r["all"]["V"],
                         "pearson":r["pearson_all_samples"],"events":{k:{n:d[n] for n in ("u_count","v_count","common_count","same_sign_common_count")}
                         for k,d in r["deviation_from_each_channel_median"].items()}}
                      for p,r in (("OFF",off),("ON",on))},ensure_ascii=False),flush=True)


if __name__ == "__main__": main()
