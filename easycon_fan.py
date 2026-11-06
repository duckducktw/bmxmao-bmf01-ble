#!/usr/bin/env python3
"""EasyCon UART fan BLE protocol core (BMXMAO BMF-01 / FY0002E).

Reverse-engineered from the EasyCon (易智控) companion app's embedded
WeChat mini-program. Control is over a GATT connection (NOT advertising),
plaintext, no encryption — a simple UART passthrough protocol.

Frame:  fe01 + len(2B BE) + cmd(2B) + data
Commands:
  uartSend(id, val): cmd=3203, data = id(1B) + val(1B; 2B if >255)
  query status:      cmd=3004  -> reply 3202 <uart bytes>
  handshake:         cmd=5011  -> reply 5012 <model><fw>
Status 3202 decode (arr = bytes):
  arr[0]  -> a1..a8  (1 bit each, LSB first)
  arr[1]  -> b1..b4  (2 bits each)
  arr[2]  -> c1 (low nibble), c2 (high nibble)
  arr[3..]-> d1..d15 (1 byte each)   # getUartDataById('dN') == arr[N+2]
"""
import struct

# GATT handles (stable across devices on this EasyCon module)
SERVICE_UUID = "fa879af4-d601-420c-b2b4-07ffb528dde3"
WRITE_UUID   = "b02eaeaa-f6bc-4a7e-bc94-f7b7fc8ded0b"
NOTIFY_UUID  = "10e2fde2-d7fe-4845-b3f3-a32010ebb095"

# Advertised device name used to discover the fan (no hard-coded MAC).
DEVICE_NAME = "FY0002"


def frame(cmd_hex: str, data_hex: str = "") -> bytes:
    p = bytes.fromhex(cmd_hex + data_hex)
    return b"\xfe\x01" + struct.pack(">H", len(p)) + p


def cmd_uart(uart_id: str, value: int) -> bytes:
    """Build a uartSend frame: 3203 + id + value. uart_id e.g. 'a1'/'d1'/'c1'."""
    v = f"{value:02x}" if value <= 255 else f"{value:04x}"
    return frame("3203", uart_id + v)


def cmd_query() -> bytes:
    return frame("3004")


def cmd_handshake() -> bytes:
    return frame("5011")


def parse_frame(raw: bytes):
    """Split one fe01/55aa frame -> (cmd_hex, data_hex). None if incomplete."""
    if len(raw) < 4:
        return None
    ln = struct.unpack(">H", raw[2:4])[0]
    if len(raw) < 4 + ln:
        return None
    payload = raw[4:4 + ln]
    return payload[:2].hex(), payload[2:].hex()


def decode_status(data_hex: str) -> dict:
    """Decode the data part of a 3202 reply (without the '3202' prefix)."""
    arr = [int(data_hex[2 * i:2 * i + 2], 16) for i in range(len(data_hex) // 2)]
    out = {"_raw": arr}
    if len(arr) >= 1:
        for r in range(8):
            out[f"a{r + 1}"] = (arr[0] >> r) & 1
    if len(arr) >= 2:
        for c in range(4):
            out[f"b{c + 1}"] = (arr[1] >> (2 * c)) & 3
    if len(arr) >= 3:
        out["c1"] = arr[2] & 0x0F
        out["c2"] = (arr[2] >> 4) & 0x0F
    for n in range(1, 16):
        if len(arr) >= n + 3:
            out[f"d{n}"] = arr[n + 2]
    return out


# Function map.  All entries below confirmed by eyeball test on real hardware
# (BMF-01 / FY0002E, 2026-11). "proven" = verified against the physical fan.
FUNCTION_MAP = {
    "power":           {"id": "a1", "kind": "switch", "status": "proven",
                        "desc": "Power (turning off zeroes d1; on restores it)"},
    "speed":           {"id": "d1", "kind": "level", "range": (1, 7), "status": "proven",
                        "desc": "Fan speed, 7 levels (app '1/2/4' wind-power buttons are display-only)"},
    "swing_vertical":  {"id": "a2", "kind": "switch", "status": "proven",
                        "desc": "Vertical swing (up/down oscillation)"},
    "swing_horizontal":{"id": "a5", "kind": "switch", "status": "proven",
                        "desc": "Horizontal swing on/off (angle is set separately, see note)"},
    "mode_sleep":      {"id": "a3", "kind": "switch", "status": "proven",
                        "desc": "Sleep-wind mode"},
    "mode_ai":         {"id": "a4", "kind": "switch", "status": "proven",
                        "desc": "AI-wind mode"},
    "swing_angle":     {"id": "c1", "kind": "enum", "range": (0, 2), "status": "proven",
                        "desc": "Horizontal swing angle: 0=30deg, 1=60deg, 2=120deg"},
    "timer":           {"id": "d2", "kind": "level", "range": (0, 255), "status": "proven",
                        "desc": "Timer: total hours (0=off), mirrors into d3; app '1/2/4h' checkboxes just sum to one total"},
}

# Registers that are writable but produced NO observable effect on this model
# (reserved / unused by BMF-01 firmware).
NO_EFFECT_IDS = ["a6", "a7", "a8", "b1", "b2", "b3", "b4", "c2"]

# Every writable uart id (for advanced / scan use)
ALL_IDS = ["a1", "a2", "a3", "a4", "a5", "a6", "a7", "a8", "b1", "b2", "b3", "b4",
           "c1", "c2", "d1", "d2", "d3", "d4", "d5", "d6", "d7", "d8"]
