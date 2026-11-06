#!/usr/bin/env python3
"""針對性探測: 角度(c群)/風類(b群)/定時。帶對前提後看狀態欄位收不收值。
前提: 開機 a1=1, 關AI a4=0, 關睡眠 a3=0, 風速手動 d1=4。
"""
import asyncio, struct, os, sys
from bleak import BleakClient, BleakScanner
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import easycon_fan as P
MAC=os.environ.get("FAN_ADDR")  # set FAN_ADDR to your fan's BLE MAC, or leave unset to scan by name

class F:
    def __init__(s): s.buf=bytearray(); s.cli=None; s.st=None
    def _f(s,_,d):
        s.buf.extend(d)
        while len(s.buf)>=4:
            if s.buf[0:2] not in (b"\xfe\x01",b"\x55\xaa"): s.buf.pop(0); continue
            ln=struct.unpack(">H",s.buf[2:4])[0]; tot=4+ln
            if len(s.buf)<tot: break
            fr=bytes(s.buf[:tot]); s.buf=s.buf[tot:]
            r=P.parse_frame(fr)
            if r and r[0]=="3202": s.st=P.decode_status(r[1])
    async def conn(s):
        d=None
        for _ in range(5):
            if MAC:
                d=await BleakScanner.find_device_by_address(MAC,timeout=15)
            else:
                d=await BleakScanner.find_device_by_name(P.DEVICE_NAME,timeout=15)
            if d: break
            await asyncio.sleep(3)
        if not d: print("找不到風扇"); sys.exit(2)
        s.cli=BleakClient(d,timeout=25); await s.cli.connect()
        await s.cli.start_notify(P.NOTIFY_UUID,s._f); await asyncio.sleep(0.8)
        await s.w(P.cmd_handshake()); await asyncio.sleep(0.5)
    async def w(s,raw): await s.cli.write_gatt_char(P.WRITE_UUID,raw,response=True); await asyncio.sleep(0.4)
    async def q(s):
        s.st=None; await s.w(P.cmd_query())
        for _ in range(10):
            if s.st is not None: break
            await asyncio.sleep(0.2)
        return s.st
    async def u(s,i,v): await s.w(P.cmd_uart(i,v))
    async def dc(s):
        try: await s.cli.stop_notify(P.NOTIFY_UUID)
        except: pass
        await s.cli.disconnect()

async def main():
    f=F(); print("連線中…"); await f.conn()
    print("基線:", (await f.q())["_raw"])
    # 設前提
    for i,v in [("a1",1),("a4",0),("a3",0),("d1",4)]:
        await f.u(i,v)
    base=await f.q(); print("前提設定後:", base["_raw"])
    def diff(before,after):
        return [(k,before.get(k),after.get(k)) for k in after if k!="_raw" and before.get(k)!=after.get(k)]

    print("\n=== 角度掃 c 群 (App: 角度=uart.c, d30/d60/d120) ===")
    for grp in ["c1","c2"]:
        for v in [0,1,2,3]:
            b=await f.q(); await f.u(grp,v); a=await f.q()
            ch=diff(b,a)
            print(f"  {grp}={v}: raw={a['_raw']} 變化={ch if ch else '無'}")
        await f.u(grp,0)

    print("\n=== 風類掃 b 群 (App: 風類=uart.b radio) ===")
    for grp in ["b1","b2","b3","b4"]:
        for v in [0,1,2,3]:
            b=await f.q(); await f.u(grp,v); a=await f.q()
            ch=diff(b,a)
            print(f"  {grp}={v}: raw={a['_raw']} 變化={ch if ch else '無'}")
        await f.u(grp,0)

    print("\n=== 定時掃 d 群 d2..d8 (1/2/4 可自由搭配→疑 bit-OR 或 小時值) ===")
    for grp in ["d2","d3","d4","d5","d6","d7","d8"]:
        b=await f.q(); await f.u(grp,7); a=await f.q()
        ch=diff(b,a)
        print(f"  {grp}=7: raw={a['_raw']} 變化={ch if ch else '無'}")
        await f.u(grp,0)

    fin=await f.q(); print("\n收尾:", fin["_raw"])
    await f.dc(); print("done")

asyncio.run(main())
