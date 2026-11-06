#!/usr/bin/env python3
"""互動式功能確認工具 (BMXMAO BMF-01 / FY0002E)。

對每個「未知功能」的 uart 暫存器,每 5 秒開/關切換一次 (重複數輪),
你在風扇旁邊看它實際做什麼,然後輸入文字描述。全部存成 JSON + Markdown。

用法:
  python3 confirm_functions.py                # 確認預設未知清單
  python3 confirm_functions.py a2 a3 c1       # 只確認指定 id
  FAN_ADDR=XX:XX:... python3 confirm_functions.py

每個 id 的流程:
  - 二元開關 (a/b 群): 開5秒 → 關5秒,重複 3 輪
  - 枚舉 (c 群): 依序設 0,1,2,3,4,5 各停 5 秒
  然後提示你輸入觀察到的行為 (例: 擺頭 / 反轉 / 燈 / 霧化 / 無反應)。
  可輸入 'r' 重播一輪、's' 跳過、's!' 跳過其餘全部。

結果存於:
  functions_observed.json   機器可讀
  FUNCTIONS_OBSERVED.md     人類可讀對照表
"""
import asyncio
import json
import os
import struct
import sys
from datetime import datetime

from bleak import BleakClient, BleakScanner

import easycon_fan as P

# 預設要確認的未知功能 (已知的 a1/d1 不列入,但保留 c1 因模式語意未定案)
DEFAULT_UNKNOWN = ["a2", "a3", "a4", "a5", "a6", "a7", "a8",
                   "b1", "b2", "b3", "b4", "c1", "c2"]

HERE = os.path.dirname(os.path.abspath(__file__))
JSON_PATH = os.path.join(HERE, "functions_observed.json")
MD_PATH = os.path.join(HERE, "FUNCTIONS_OBSERVED.md")


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
            print(f"找不到風扇 ({P.DEVICE_NAME})。確認已開機且在範圍內。")
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


async def ainput(prompt):
    """非阻塞 input (不卡住 asyncio event loop)。"""
    loop = asyncio.get_event_loop()
    return (await loop.run_in_executor(None, lambda: input(prompt))).strip()


async def demo_switch(f, uid, rounds=3):
    """二元開關: 開5秒 關5秒 × rounds。"""
    for i in range(rounds):
        print(f"    [{uid}] 第{i+1}/{rounds}輪 → 開 (5秒)…", flush=True)
        await f.uart(uid, 1)
        await asyncio.sleep(5)
        print(f"    [{uid}] 第{i+1}/{rounds}輪 → 關 (5秒)…", flush=True)
        await f.uart(uid, 0)
        await asyncio.sleep(5)


async def demo_enum(f, uid, lo=0, hi=5):
    """枚舉: 依序設 lo..hi 各停 5 秒。"""
    for v in range(lo, hi + 1):
        print(f"    [{uid}] = {v} (5秒)…", flush=True)
        await f.uart(uid, v)
        await asyncio.sleep(5)
    await f.uart(uid, lo)


def save(results):
    with open(JSON_PATH, "w", encoding="utf-8") as fp:
        json.dump(results, fp, ensure_ascii=False, indent=2)
    lines = [
        "# BMF-01 功能實測對照表",
        "",
        f"> 實測時間: {datetime.now().strftime('%Y-%m-%d %H:%M')}  (肉眼確認)",
        "",
        "| uart id | 實測行為 | 類型 |",
        "|---|---|---|",
    ]
    for uid, rec in results.items():
        lines.append(f"| `{uid}` | {rec['behavior'] or '(未填)'} | {rec['kind']} |")
    with open(MD_PATH, "w", encoding="utf-8") as fp:
        fp.write("\n".join(lines) + "\n")


async def main():
    ids = sys.argv[1:] or DEFAULT_UNKNOWN
    # 續接已存檔結果
    results = {}
    if os.path.exists(JSON_PATH):
        try:
            results = json.load(open(JSON_PATH, encoding="utf-8"))
        except Exception:
            results = {}

    f = Fan()
    print("連線中…")
    await f.connect()
    base = await f.query()
    print(f"已連線。基線狀態 raw={base.get('_raw') if base else '?'}")
    # 確保開機 (有些功能關機時不作用)
    await f.uart("a1", 1)
    print("已確保開機 (a1=1)。\n")

    skip_rest = False
    try:
        for uid in ids:
            if skip_rest:
                break
            kind = "enum" if uid[0] == "c" else "switch"
            print(f"\n===== 確認 {uid} ({'枚舉0-5' if kind=='enum' else '二元開關'}) =====")
            print("    看好風扇,我開始切換。(可於提示時輸入 r 重播 / s 跳過 / s! 跳過其餘)")
            while True:
                if kind == "enum":
                    await demo_enum(f, uid)
                else:
                    await demo_switch(f, uid)
                ans = await ainput(f"  >>> {uid} 實際做了什麼? (描述 / r重播 / s跳過 / s!跳全部): ")
                if ans == "r":
                    continue
                if ans == "s":
                    print(f"    跳過 {uid}")
                    break
                if ans == "s!":
                    skip_rest = True
                    print("    跳過其餘全部")
                    break
                results[uid] = {"behavior": ans, "kind": kind,
                                "ts": datetime.now().isoformat(timespec="seconds")}
                save(results)
                print(f"    已存檔: {uid} = 「{ans}」")
                break
        # 收尾: 關再開,清掉測試殘留
        await f.uart("a1", 0)
        await asyncio.sleep(0.3)
        await f.uart("a1", 1)
        fin = await f.query()
        print(f"\n收尾狀態 raw={fin.get('_raw') if fin else '?'}")
    finally:
        await f.disconnect()

    print(f"\n完成。已確認 {len([r for r in results.values() if r['behavior']])} 項。")
    print(f"  JSON: {JSON_PATH}")
    print(f"  MD:   {MD_PATH}")

asyncio.run(main())
