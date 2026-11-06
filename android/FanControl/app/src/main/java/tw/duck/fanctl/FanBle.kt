package tw.duck.fanctl

import android.annotation.SuppressLint
import android.bluetooth.*
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanResult
import android.content.Context
import android.os.Handler
import android.os.Looper
import java.util.LinkedList
import java.util.Queue

/**
 * Manages the BLE link to the fan: scan by name -> connect -> notify -> handshake.
 * Writes are serialized through a queue because GATT allows one outstanding op.
 */
@SuppressLint("MissingPermission")
class FanBle(private val context: Context) {

    interface Listener {
        fun onStatus(msg: String)
        fun onState(state: FanState)
        fun onReady(ready: Boolean)
        fun onDeviceFound(device: BluetoothDevice, name: String, rssi: Int)
        fun onScanFinished()
    }

    var listener: Listener? = null

    private val main = Handler(Looper.getMainLooper())
    private val adapter: BluetoothAdapter? =
        (context.getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager).adapter

    private var gatt: BluetoothGatt? = null
    private var writeChar: BluetoothGattCharacteristic? = null
    private var notifyChar: BluetoothGattCharacteristic? = null

    private val rxBuf = ArrayList<Byte>()
    private val writeQueue: Queue<ByteArray> = LinkedList()
    private var writing = false
    private var scanning = false
    private val seen = HashSet<String>()

    private fun status(m: String) = main.post { listener?.onStatus(m) }

    /** Scan and report every BLE device found (UI picks one). */
    fun scan() {
        val a = adapter
        if (a == null || !a.isEnabled) { status("請先打開藍牙"); return }
        val scanner = a.bluetoothLeScanner ?: run { status("無法啟動掃描"); return }
        seen.clear()
        status("搜尋裝置中…")
        scanning = true
        scanner.startScan(scanCallback)
        main.postDelayed({
            if (scanning) { scanning = false; scanner.stopScan(scanCallback); main.post { listener?.onScanFinished() } }
        }, 8000)
    }

    fun stopScan() {
        if (scanning) { scanning = false; adapter?.bluetoothLeScanner?.stopScan(scanCallback) }
    }

    private val scanCallback = object : ScanCallback() {
        override fun onScanResult(callbackType: Int, result: ScanResult) {
            val dev = result.device
            val addr = dev.address ?: return
            if (!seen.add(addr)) return
            val name = dev.name ?: result.scanRecord?.deviceName ?: ""
            main.post { listener?.onDeviceFound(dev, name, result.rssi) }
        }
        override fun onScanFailed(errorCode: Int) { status("掃描失敗: $errorCode") }
    }

    /** Connect to a device the user picked from the scan list. */
    fun connectTo(device: BluetoothDevice) {
        stopScan()
        status("連線中…")
        connect(device)
    }

    private fun connect(device: BluetoothDevice) {
        gatt = device.connectGatt(context, false, gattCallback, BluetoothDevice.TRANSPORT_LE)
    }

    private val gattCallback = object : BluetoothGattCallback() {
        override fun onConnectionStateChange(g: BluetoothGatt, st: Int, newState: Int) {
            if (newState == BluetoothProfile.STATE_CONNECTED) {
                status("已連線，探索服務…")
                main.post { g.discoverServices() }
            } else if (newState == BluetoothProfile.STATE_DISCONNECTED) {
                status("連線中斷")
                cleanup()
                main.post { listener?.onReady(false) }
            }
        }

        override fun onServicesDiscovered(g: BluetoothGatt, st: Int) {
            val svc = g.getService(Protocol.SERVICE_UUID) ?: run { status("找不到服務"); return }
            writeChar = svc.getCharacteristic(Protocol.WRITE_UUID)
            notifyChar = svc.getCharacteristic(Protocol.NOTIFY_UUID)
            if (writeChar == null || notifyChar == null) { status("找不到特徵"); return }
            g.setCharacteristicNotification(notifyChar, true)
            val cccd = notifyChar!!.getDescriptor(
                java.util.UUID.fromString("00002902-0000-1000-8000-00805f9b34fb"))
            cccd?.let {
                it.value = BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
                g.writeDescriptor(it)
            }
        }

        override fun onDescriptorWrite(g: BluetoothGatt, d: BluetoothGattDescriptor, st: Int) {
            // notifications ready -> handshake, then query
            enqueue(Protocol.cmdHandshake())
            enqueue(Protocol.cmdQuery())
            status("已就緒")
            main.post { listener?.onReady(true) }
        }

        override fun onCharacteristicWrite(g: BluetoothGatt, c: BluetoothGattCharacteristic, st: Int) {
            writing = false
            drain()
        }

        @Deprecated("Deprecated in Java")
        override fun onCharacteristicChanged(g: BluetoothGatt, c: BluetoothGattCharacteristic) {
            val v = c.value ?: return
            handleRx(v)
        }
    }

    private fun handleRx(chunk: ByteArray) {
        synchronized(rxBuf) {
            for (b in chunk) rxBuf.add(b)
            // try to parse frames
            while (rxBuf.size >= 4) {
                // header must be fe01 or 55aa
                val h0 = rxBuf[0].toInt() and 0xFF
                val h1 = rxBuf[1].toInt() and 0xFF
                if (!((h0 == 0xFE && h1 == 0x01) || (h0 == 0x55 && h1 == 0xAA))) {
                    rxBuf.removeAt(0); continue
                }
                val len = ((rxBuf[2].toInt() and 0xFF) shl 8) or (rxBuf[3].toInt() and 0xFF)
                val total = 4 + len
                if (rxBuf.size < total) break
                val frame = ByteArray(total) { rxBuf[it] }
                repeat(total) { rxBuf.removeAt(0) }
                val parsed = Protocol.parseFrame(frame) ?: continue
                if (parsed.first == "3202") {
                    val state = Protocol.decodeStatus(parsed.second)
                    main.post { listener?.onState(state) }
                }
            }
        }
    }

    /** Public: send a uart command then re-query to refresh state. */
    fun uart(id: String, value: Int) {
        enqueue(Protocol.cmdUart(id, value))
        enqueue(Protocol.cmdQuery())
    }

    fun refresh() = enqueue(Protocol.cmdQuery())

    private fun enqueue(bytes: ByteArray) {
        synchronized(writeQueue) { writeQueue.add(bytes) }
        drain()
    }

    private fun drain() {
        val g = gatt ?: return
        val wc = writeChar ?: return
        synchronized(writeQueue) {
            if (writing || writeQueue.isEmpty()) return
            val next = writeQueue.poll() ?: return
            writing = true
            if (android.os.Build.VERSION.SDK_INT >= 33) {
                g.writeCharacteristic(wc, next, BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT)
            } else {
                @Suppress("DEPRECATION")
                wc.value = next
                @Suppress("DEPRECATION")
                wc.writeType = BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT
                @Suppress("DEPRECATION")
                g.writeCharacteristic(wc)
            }
        }
    }

    private fun cleanup() {
        writeChar = null; notifyChar = null; writing = false
        synchronized(writeQueue) { writeQueue.clear() }
        synchronized(rxBuf) { rxBuf.clear() }
    }

    fun stop() {
        try { gatt?.disconnect() } catch (_: Exception) {}
        try { gatt?.close() } catch (_: Exception) {}
        gatt = null
        cleanup()
    }
}
