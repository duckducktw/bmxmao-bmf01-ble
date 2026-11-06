# BMXMAO BMF-01 Fan — Python BLE Control

> English ｜ [繁體中文](README.zh.md)

Control the BMXMAO **BMF-01** ("MAO Air Fan" voice-control circulator fan, BLE module
model **FY0002E**) from Python over Bluetooth LE, without the vendor app.

The fan is marketed as voice-control + IR-remote only, with no mention of app/Bluetooth
control. It turns out the BLE module speaks a plaintext **UART-over-GATT** protocol
(EasyCon / 易智控), fully reverse-engineered here.

## Install

```bash
pip install bleak
```

## Usage

```bash
python3 fanctl.py status          # read + decode current state
python3 fanctl.py on              # power on
python3 fanctl.py off             # power off
python3 fanctl.py speed 3         # fan speed 1-7
python3 fanctl.py swing-v         # vertical swing on (swing-v 0 = off)
python3 fanctl.py swing-h         # horizontal swing on (swing-h 0 = off)
python3 fanctl.py sleep           # sleep-wind mode on (sleep 0 = off)
python3 fanctl.py ai              # AI-wind mode on (ai 0 = off)
python3 fanctl.py angle 120       # swing angle: 30 / 60 / 120 degrees
python3 fanctl.py timer 4         # sleep timer: hours (timer 0 = off)

# advanced
python3 fanctl.py set a2 1        # write any uart register directly
python3 fanctl.py toggle a2       # flip a binary switch
python3 fanctl.py scan            # flip each switch, report state deltas (label discovery)
```

By default it discovers the fan by its advertised name `FY0002`. To target a specific
device set `FAN_ADDR`:

```bash
FAN_ADDR=XX:XX:XX:XX:XX:XX python3 fanctl.py status
```

Every command re-reads the device status (`3202`) afterwards and prints the decoded
state, so you get closed-loop confirmation that the command took effect.

## Protocol

See [PROTOCOL.md](PROTOCOL.md) for the full frame format, command list, and status
decoding. Short version:

```
frame = fe01 + len(2B BE) + cmd(2B) + data
uart write:  cmd=3203, data=<id><val>
query:       cmd=3004  -> 3202 <uart bytes>
```

Confirmed functions (all hardware-tested): `a1`=power, `d1`=speed (1-7),
`a2`=vertical swing, `a5`=horizontal swing on/off, `a3`=sleep mode, `a4`=AI mode,
`c1`=swing angle (0=30°/1=60°/2=120°), `d2`=timer (hours, 0=off).
Registers `a6-a8/b1-b4/c2` are writable but have no effect. The angle/timer registers
only take values with power on and AI/sleep off.

## Files

| File | Purpose |
|---|---|
| `easycon_fan.py` | Protocol core: frame build, status decode, function map |
| `fanctl.py` | Command-line control tool |
| `PROTOCOL.md` | Full protocol specification |

## How it was reverse-engineered

The protocol was extracted from the EasyCon companion app's embedded WeChat
mini-program (`app-service.js` → `SendData.uartSend`, `_uartDataProcess`, the fan page),
and cross-checked against the Home Assistant [`easycon_ble`] integration, which uses the
same frame format and handshake. The fan's GATT status report (`3202`) acts as a
software-observable oracle: write a register, re-query, confirm the state changed —
no need to watch the physical fan.

## License

MIT — see [LICENSE](LICENSE).

## Disclaimer

Independent interoperability research on hardware the author owns. Not affiliated with or
endorsed by BMXMAO or EasyCon. Trademarks belong to their respective owners. Use at your
own risk.
