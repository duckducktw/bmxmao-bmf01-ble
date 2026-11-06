package tw.duck.fanctl

/**
 * EasyCon UART fan BLE protocol (BMXMAO BMF-01 / FY0002E).
 * Ported from the reverse-engineered easycon_fan.py.
 *
 * Frame:  fe01 + len(2B BE) + cmd(2B) + data
 *   uartSend(id,val): cmd=3203, data = id(1B) + val(1B)
 *   query status:     cmd=3004 -> reply 3202 <uart bytes>
 *   handshake:        cmd=5011 -> reply 5012 <model><fw>
 */
object Protocol {
    val SERVICE_UUID = java.util.UUID.fromString("fa879af4-d601-420c-b2b4-07ffb528dde3")
    val WRITE_UUID   = java.util.UUID.fromString("b02eaeaa-f6bc-4a7e-bc94-f7b7fc8ded0b")
    val NOTIFY_UUID  = java.util.UUID.fromString("10e2fde2-d7fe-4845-b3f3-a32010ebb095")
    const val DEVICE_NAME = "FY0002"

    /** Build a raw frame from a hex command + hex data. */
    private fun frame(cmdHex: String, dataHex: String = ""): ByteArray {
        val payload = hexToBytes(cmdHex + dataHex)
        val out = ByteArray(2 + 2 + payload.size)
        out[0] = 0xFE.toByte(); out[1] = 0x01.toByte()
        out[2] = ((payload.size shr 8) and 0xFF).toByte()
        out[3] = (payload.size and 0xFF).toByte()
        System.arraycopy(payload, 0, out, 4, payload.size)
        return out
    }

    /** uartSend: 3203 + id + value (1 byte; 2 bytes if >255). */
    fun cmdUart(uartId: String, value: Int): ByteArray {
        val v = if (value <= 255) "%02x".format(value) else "%04x".format(value)
        return frame("3203", uartId + v)
    }

    fun cmdQuery(): ByteArray = frame("3004")
    fun cmdHandshake(): ByteArray = frame("5011")

    /** Parse one fe01/55aa frame -> Pair(cmdHex, dataBytes). null if incomplete. */
    fun parseFrame(raw: ByteArray): Pair<String, ByteArray>? {
        if (raw.size < 4) return null
        val len = ((raw[2].toInt() and 0xFF) shl 8) or (raw[3].toInt() and 0xFF)
        if (raw.size < 4 + len) return null
        val payload = raw.copyOfRange(4, 4 + len)
        if (payload.size < 2) return null
        val cmd = "%02x%02x".format(payload[0].toInt() and 0xFF, payload[1].toInt() and 0xFF)
        val data = payload.copyOfRange(2, payload.size)
        return Pair(cmd, data)
    }

    /** Decode the data part of a 3202 reply into named fields. */
    fun decodeStatus(data: ByteArray): FanState {
        val arr = IntArray(data.size) { data[it].toInt() and 0xFF }
        val s = FanState(raw = arr)
        if (arr.isNotEmpty()) {
            s.a1 = (arr[0] shr 0) and 1
            s.a2 = (arr[0] shr 1) and 1
            s.a3 = (arr[0] shr 2) and 1
            s.a4 = (arr[0] shr 3) and 1
            s.a5 = (arr[0] shr 4) and 1
        }
        if (arr.size >= 3) {
            s.c1 = arr[2] and 0x0F
        }
        if (arr.size >= 4) s.d1 = arr[3]   // speed
        if (arr.size >= 5) s.d2 = arr[4]   // timer
        return s
    }

    private fun hexToBytes(hex: String): ByteArray {
        val clean = hex.trim()
        return ByteArray(clean.length / 2) {
            ((Character.digit(clean[it * 2], 16) shl 4) + Character.digit(clean[it * 2 + 1], 16)).toByte()
        }
    }
}

/** Decoded fan state. */
data class FanState(
    var a1: Int = 0,   // power
    var a2: Int = 0,   // vertical swing
    var a3: Int = 0,   // sleep mode
    var a4: Int = 0,   // AI mode
    var a5: Int = 0,   // horizontal swing
    var c1: Int = 0,   // swing angle 0=30 1=60 2=120
    var d1: Int = 0,   // speed 1-7
    var d2: Int = 0,   // timer hours
    val raw: IntArray = IntArray(0)
) {
    val angleDeg: Int get() = when (c1) { 0 -> 30; 1 -> 60; 2 -> 120; else -> -1 }
}
