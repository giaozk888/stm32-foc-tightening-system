"""Read-only Modbus TCP / upload-server acceptance probe. Never writes coils/registers."""
import argparse
import json
import os
import socket
import struct
from urllib.request import Request, urlopen

def exact(s, n):
    out=bytearray()
    while len(out)<n:
        data=s.recv(n-len(out))
        if not data:raise RuntimeError("incomplete TCP response")
        out.extend(data)
    return bytes(out)

def read_inputs(host, port, addr, quantity, transaction):
    q=struct.pack(">HHHBBHH",transaction,0,6,1,4,addr,quantity)
    with socket.create_connection((host,port),timeout=3) as s:
        s.settimeout(3);s.sendall(q);head=exact(s,7)
        tid,proto,length,unit=struct.unpack(">HHHB",head)
        if tid!=transaction or proto or unit!=1 or not 2<=length<=254:
            raise RuntimeError("invalid MBAP response")
        data=exact(s,length-1)
        if data[0]==0x84:raise RuntimeError(f"Modbus exception {data[1]} (4 means no fresh STM32 observation)")
        if len(data)!=2+2*quantity or data[0]!=4 or data[1]!=2*quantity:
            raise RuntimeError("invalid register reply")
        return struct.unpack(">"+"H"*quantity,data[2:])

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--esp-ip",required=True)
    p.add_argument("--port",type=int,default=502)
    p.add_argument("--server",help="Server origin, e.g. https://example or http://192.168.137.10:8088")
    args=p.parse_args()
    r=read_inputs(args.esp_ip,args.port,0,8,501)
    if r[0]!=1 or r[2]!=0:raise RuntimeError("not the expected locked gateway observation map")
    print(f"Gateway schema={r[0]} wifi={bool(r[1]&1)} fresh={bool(r[1]&2)} CONTROL=LOCKED quality=0x{r[3]:X} age_ms={(r[4]<<16)|r[5]}")
    if r[1]&2:
        r=read_inputs(args.esp_ip,args.port,0,40,502)
        u32=lambda i:(r[i]<<16)|r[i+1]
        signed=lambda i:u32(i)-(2**32 if u32(i)&0x80000000 else 0)
        # Fresh transport does not make every measurement valid. In safe mode
        # the stored Iq may be an old value; honor the firmware validity flags.
        encoder_valid = bool(r[15] & 1)
        iq_valid = bool(r[15] & 2)
        position = signed(18)/100 if encoder_valid else "unavailable"
        rpm = signed(20)/10 if encoder_valid else "unavailable"
        iq = signed(22) if iq_valid else "unavailable"
        bus = u32(24) if not (r[3] & (2 | 16)) else "unavailable"
        print(f"seq={u32(6)} run={u32(10)} stage={r[13]} outcome={r[14]} flags=0x{r[15]:X} fault={r[16]} safe={bool(r[15]&8)} position_deg={position} rpm={rpm} iq_ma={iq} bus_est_mv={bus} (diagnostic estimate, not calibrated)")
        print(f"uploaded={u32(30)} queued={u32(32)} dropped={u32(34)} http_fail={u32(36)} rejected={u32(38)}")
    if args.server:
        token=os.environ.get("TIGHTEN_API_TOKEN","")
        if not token:raise RuntimeError("set TIGHTEN_API_TOKEN locally; never put it in a URL")
        req=Request(args.server.rstrip("/")+"/api/v1/summary",headers={"Authorization":"Bearer "+token})
        with urlopen(req,timeout=5) as reply:data=json.load(reply)
        if data["control_enabled"]:raise RuntimeError("unexpected unlocked server")
        print(f"Server stored={data['samples']} results={data['results']} CONTROL=LOCKED")
    print("Read-only probe complete. No motion/relay/write command sent.")

if __name__=="__main__":main()
