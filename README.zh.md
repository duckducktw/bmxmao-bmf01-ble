# BMXMAO BMF-01 風扇 — Python BLE 控制

> [English](README.md) ｜ 繁體中文

用 Python 透過藍牙 LE 控制 BMXMAO **BMF-01**（「MAO Air Fan」智能聲控循環立扇，BLE 模組型號
**FY0002E**），脫離官方 App。

這台風扇對外只宣傳「語音聲控 + 紅外線遙控」，完全沒提到 App 或藍牙控制。實際上它的 BLE 模組跑的是
一套明文的 **UART-over-GATT** 協定（EasyCon / 易智控），本專案已完整逆向。

## 安裝

```bash
pip install bleak
```

## 用法

```bash
python3 fanctl.py status          # 讀取並解碼當前狀態
python3 fanctl.py on              # 開機
python3 fanctl.py off             # 關機
python3 fanctl.py speed 3         # 風速 1-7
python3 fanctl.py swing-v         # 上下擺頭 開（swing-v 0 = 關）
python3 fanctl.py swing-h         # 左右擺頭 開（swing-h 0 = 關）
python3 fanctl.py sleep           # 睡眠風 開（sleep 0 = 關）
python3 fanctl.py ai              # AI 風 開（ai 0 = 關）
python3 fanctl.py angle 120       # 擺頭角度：30 / 60 / 120 度
python3 fanctl.py timer 4         # 睡眠定時：小時（timer 0 = 關）

# 進階
python3 fanctl.py set a2 1        # 直接寫入任一 uart 暫存器
python3 fanctl.py toggle a2       # 翻轉二元開關
python3 fanctl.py scan            # 逐一翻每個開關並回報狀態變化（定位功能用）
```

預設用廣播名稱 `FY0002` 掃描裝置。要指定特定裝置，設定 `FAN_ADDR` 環境變數：

```bash
FAN_ADDR=XX:XX:XX:XX:XX:XX python3 fanctl.py status
```

每個指令執行後都會重新讀取裝置狀態（`3202`）並印出解碼結果，形成閉環確認——指令到底有沒有生效，
軟體就看得到，不用盯著風扇。

## 協定

完整幀格式、指令列表、狀態解碼見 [PROTOCOL.zh.md](PROTOCOL.zh.md)。簡版：

```
幀 = fe01 + 長度(2B 大端) + cmd(2B) + data
uart 寫入:  cmd=3203, data=<id><val>
查詢:       cmd=3004  -> 3202 <uart bytes>
```

已確認功能（皆經實機測試）：`a1`=電源、`d1`=風速（1-7）、`a2`=上下擺頭、`a5`=左右擺頭開/關、
`a3`=睡眠風、`a4`=AI 風、`c1`=擺頭角度（0=30°/1=60°/2=120°）、`d2`=定時（小時，0=關）。
暫存器 `a6-a8/b1-b4/c2` 可寫但無作用。角度/定時暫存器只在開機且關閉 AI/睡眠時才收值。

## 檔案

| 檔案 | 用途 |
|---|---|
| `easycon_fan.py` | 協定核心：幀組裝、狀態解碼、功能對應表 |
| `fanctl.py` | 命令行控制工具 |
| `PROTOCOL.md` / `PROTOCOL.zh.md` | 完整協定規格（英/中） |

## 怎麼逆向出來的

協定擷取自 EasyCon 官方 App 內嵌的微信小程式（`app-service.js` → `SendData.uartSend`、
`_uartDataProcess`、風扇頁 `pages/iot/fan`），並與 Home Assistant 的 `easycon_ble` 整合交叉比對
（兩者幀格式與握手一致）。風扇的 GATT 狀態回報（`3202`）扮演「軟體可觀測的 oracle」：寫一個暫存器、
重查、確認狀態改變——不需要看實體風扇。

## 授權

MIT — 見 [LICENSE](LICENSE)。

## 免責聲明

針對作者自有硬體的獨立互通性（interoperability）研究。與 BMXMAO、EasyCon 無任何從屬或背書關係。
商標歸各自所有者。使用風險自負。
