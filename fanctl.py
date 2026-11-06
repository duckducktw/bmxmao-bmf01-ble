#!/usr/bin/env python3
"""BMXMAO BMF-01 fan control CLI (EasyCon UART-over-GATT protocol).

Usage:
  python3 fanctl.py status              # read + decode current state
  python3 fanctl.py on | off            # power
  python3 fanctl.py speed <1-7>         # fan speed level
  python3 fanctl.py swing-v [0|1]       # vertical swing (up/down) on/off
  python3 fanctl.py swing-h [0|1]       # horizontal swing (~120 deg) on/off
  python3 fanctl.py sleep [0|1]         # sleep-wind mode
  python3 fanctl.py ai [0|1]            # AI-wind mode
  python3 fanctl.py angle <30|60|120>   # horizontal swing angle
  python3 fanctl.py timer <hours>       # sleep timer in hours (0 = off)
  python3 fanctl.py set <id> <val>      # advanced: write any uart register (e.g. a2, c1, d1)
  python3 fanctl.py toggle <id>         # advanced: flip a binary switch (read XOR 1)
  python3 fanctl.py scan                # advanced: flip each switch and report state deltas

The protocol has a status report (3202), so every action is verified by
re-reading state afterwards — no guesswork, closed-loop in software.

Env:
  FAN_ADDR   optional BLE MAC to connect directly (skips name scan)
"""
import asyncio
import os
import struct
import sys

from bleak import BleakClient, BleakScanner

import easycon_fan as P


async def find():
    addr = os.environ.get("FAN_ADDR")
    for _ in range(5):
        if addr:
            d = await BleakScanner.find_device_by_address(addr, timeout=15)
        else:
            d = await BleakScanner.find_device_by_name(P.DEVICE_NAME, timeout=15)
        if d:
            return d
        await asyncio.sleep(3)
    return None


class Fan:
    def __init__(self):
        self.buf = bytearray()
        self.cli = None
        self.status = None

    def _feed(self, _s, data):
        self.buf.extend(data)
        while len(self.buf) >= 4:
            if self.buf[0:2] not in (b"\xfe\x01", b"\x55\xaa"):
                self.buf.pop(0)
                continue
            ln = struct.unpack(">H", self.buf[2:4])[0]
            tot = 4 + ln
            if len(self.buf) < tot:
                break
            fr = bytes(self.buf[:tot])
            self.buf = self.buf[tot:]
            r = P.parse_frame(fr)
            if r and r[0] == "3202":
                self.status = P.decode_status(r[1])

    async def connect(self):
        dev = await find()
        if not dev:
            print(f"Fan not found ({P.DEVICE_NAME}). Make sure it is powered and in range.")
            sys.exit(2)
        self.cli = BleakClient(dev, timeout=25)
        await self.cli.connect()
        await self.cli.start_notify(P.NOTIFY_UUID, self._feed)
        await asyncio.sleep(0.8)
        await self._write(P.cmd_handshake())
        await asyncio.sleep(0.5)

    async def _write(self, raw):
        await self.cli.write_gatt_char(P.WRITE_UUID, raw, response=True)
        await asyncio.sleep(0.4)

    async def query(self):
        self.status = None
        await self._write(P.cmd_query())
        for _ in range(10):
            if self.status is not None:
                break
            await asyncio.sleep(0.2)
        return self.status

    async def uart(self, uart_id, val):
        await self._write(P.cmd_uart(uart_id, val))

    async def disconnect(self):
        try:
            await self.cli.stop_notify(P.NOTIFY_UUID)
        except Exception:
            pass
        await self.cli.disconnect()


def show(st):
    if not st:
        print("  (no status reply)")
        return
    print(f"  power(a1)={'ON' if st.get('a1') else 'OFF'}  speed(d1)={st.get('d1')}  mode(c1)={st.get('c1')}")
    print(f"  other switches: a2={st.get('a2')} a3={st.get('a3')} a4={st.get('a4')} a5={st.get('a5')}")
    print(f"  raw={st.get('_raw')}")


async def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    cmd = args[0]
    f = Fan()
    await f.connect()
    try:
        if cmd == "status":
            show(await f.query())
        elif cmd == "on":
            await f.uart("a1", 1)
            print("power ON ->")
            show(await f.query())
        elif cmd == "off":
            await f.uart("a1", 0)
            print("power OFF ->")
            show(await f.query())
        elif cmd == "speed":
            v = int(args[1])
            assert 1 <= v <= 7, "speed 1-7"
            await f.uart("a1", 1)
            await f.uart("d1", v)
            print(f"speed={v} ->")
            show(await f.query())
        elif cmd == "swing-v":
            v = int(args[1]) if len(args) > 1 else 1
            await f.uart("a2", v)
            print(f"vertical swing={v} ->")
            show(await f.query())
        elif cmd == "swing-h":
            v = int(args[1]) if len(args) > 1 else 1
            await f.uart("a5", v)
            print(f"horizontal swing={v} ->")
            show(await f.query())
        elif cmd == "sleep":
            v = int(args[1]) if len(args) > 1 else 1
            await f.uart("a3", v)
            print(f"sleep mode={v} ->")
            show(await f.query())
        elif cmd == "ai":
            v = int(args[1]) if len(args) > 1 else 1
            await f.uart("a4", v)
            print(f"AI mode={v} ->")
            show(await f.query())
        elif cmd == "angle":
            # 0=30deg, 1=60deg, 2=120deg
            m = {"30": 0, "60": 1, "120": 2}
            raw = args[1]
            v = m.get(raw, int(raw))
            await f.uart("c1", v)
            print(f"swing angle set (c1={v}) ->")
            show(await f.query())
        elif cmd == "timer":
            v = int(args[1]) if len(args) > 1 else 0
            await f.uart("d2", v)
            print(f"timer={v}h (0=off) ->")
            show(await f.query())
        elif cmd == "set":
            uid, v = args[1], int(args[2])
            await f.uart(uid, v)
            print(f"{uid}={v} ->")
            show(await f.query())
        elif cmd == "toggle":
            uid = args[1]
            st = await f.query()
            cur = st.get(uid, 0)
            await f.uart(uid, 0 if cur else 1)
            print(f"{uid}: {cur}->{0 if cur else 1}")
            show(await f.query())
        elif cmd == "scan":
            base = await f.query()
            print("baseline:")
            show(base)
            for aid in ["a2", "a3", "a4", "a5", "a6", "a7", "a8", "b1", "b2", "b3", "b4", "c2"]:
                b4 = (await f.query()).get("_raw")
                await f.uart(aid, 1)
                on = (await f.query()).get("_raw")
                await f.uart(aid, 0)
                off = (await f.query()).get("_raw")
                mark = "<-- responds" if on != b4 or off != b4 else ""
                print(f"  {aid}: before={b4} on={on} off={off} {mark}")
            await f.uart("a1", 0)
            await f.uart("a1", 1)
        else:
            print(__doc__)
    finally:
        await f.disconnect()


asyncio.run(main())
