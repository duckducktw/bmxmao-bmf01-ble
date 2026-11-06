# EasyCon UART Fan — BLE Protocol Spec

> English ｜ [繁體中文](PROTOCOL.zh.md)

Reverse-engineered control protocol for BMXMAO **BMF-01** ("MAO Air Fan" voice-control
circulator fan), whose BLE module reports model **FY0002E**. The same EasyCon (易智控)
UART-over-GATT protocol is shared by other EasyCon-based appliances.

> **Control is over a GATT connection, not advertising.** Plaintext, no encryption.

## Connection

| Role | UUID |
|---|---|
| Service | `fa879af4-d601-420c-b2b4-07ffb528dde3` |
| Write (write) | `b02eaeaa-f6bc-4a7e-bc94-f7b7fc8ded0b` |
| Notify | `10e2fde2-d7fe-4845-b3f3-a32010ebb095` |

Discover by advertised device name `FY0002`. No AES authentication is required on this
model (some EasyCon light models send a `0102` challenge expecting a `0100` echo; this fan
does not — it is controllable right after connecting).

## Frame format

```
fe01 + len(2B big-endian) + cmd(2B) + data
```

`55aa` would be an AES-encrypted frame header; unused on this model.

## Commands

| Action | cmd | data | Notes |
|---|---|---|---|
| Handshake | `5011` | — | reply `5012 02 07 <model ascii> <fw ascii>` (e.g. `FY0002E` / `1.0`) |
| Query status | `3004` | — | reply `3202 <uart bytes>` |
| UART write | `3203` | `<id><val>` | id e.g. `a1`/`d1`/`c1`; val 1 byte (2 bytes if >255) |

## Status (`3202`) decoding

Let `arr` be the bytes after the `3202` prefix:

```
arr[0]   -> a1..a8   (1 bit each, LSB first)
arr[1]   -> b1..b4   (2 bits each)
arr[2]   -> c1 (low nibble), c2 (high nibble)
arr[3..] -> d1..d15  (1 byte each)      # getUartDataById('dN') == arr[N+2]
```

Writing a uart id mirrors straight into the corresponding status field, so after any write
you can re-query `3004` and confirm the change — a software-observable state oracle.

## Function map

| Function | uart id | Type | Confidence | Notes |
|---|---|---|---|---|
| Power | `a1` | switch 0/1 | **proven** | turning off zeroes `d1`; on restores last speed (power-gate effect) |
| Speed | `d1` | level 1–7 | **proven** | matches the "7-speed" spec; continuous level (the app's "1/2/4" wind-power buttons are just a display shortcut, the firmware only stores a 1–7 value here) |
| Vertical swing | `a2` | switch 0/1 | **proven** | up/down oscillation |
| Horizontal swing | `a5` | switch 0/1 | **proven** | left/right oscillation on/off (angle set separately) |
| Sleep-wind mode | `a3` | switch 0/1 | **proven** | |
| AI-wind mode | `a4` | switch 0/1 | **proven** | |
| Swing angle | `c1` | enum | **proven** | 0=30°, 1=60°, 2=120° |
| Timer | `d2` | hours | **proven** | sleep timer, stored as the total number of hours (0=off); value mirrors into `d3`. The app's "1/2/4 h" checkboxes are just a UI that adds up to a single total — the firmware stores that sum, not a bitmask |
| (no effect) | `a6`–`a8`, `b1`–`b4`, `c2` | — | confirmed no-op | writable but no observable behaviour |

All functions above were confirmed by hardware testing (eyeball + state oracle; see
`confirm_functions.py` and `probe_angle_timer.py`). The swing angle and timer registers
only accept values once power is on and AI/sleep modes are off. Earlier notes that `c1`
"only beeps" were an artefact of probing without those preconditions.

## Source of truth

Protocol extracted from the EasyCon app's embedded WeChat mini-program (`app-service.js`):
`SendData.uartSend/uartFlip`, `_uartDataProcess`, `btnEntity` uart id list, and the fan page
(`pages/iot/fan`). Cross-checked against the Home Assistant `easycon_ble` integration, which
uses the same frame format and handshake.
