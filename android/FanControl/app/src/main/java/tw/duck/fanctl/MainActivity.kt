package tw.duck.fanctl

import android.Manifest
import android.bluetooth.BluetoothDevice
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.view.View
import android.widget.ArrayAdapter
import android.widget.AdapterView
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import tw.duck.fanctl.databinding.ActivityMainBinding

class MainActivity : AppCompatActivity(), FanBle.Listener {

    private lateinit var b: ActivityMainBinding
    private lateinit var ble: FanBle
    private var ready = false
    private var updatingUi = false

    // scan dialog state
    private val foundDevices = ArrayList<BluetoothDevice>()
    private val foundLabels = ArrayList<String>()
    private var scanDialog: AlertDialog? = null
    private var scanAdapter: ArrayAdapter<String>? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        b = ActivityMainBinding.inflate(layoutInflater)
        setContentView(b.root)
        ble = FanBle(this)
        ble.listener = this
        setupSpinners()
        wireUi()
        setControlsEnabled(false)
    }

    private fun setupSpinners() {
        // speed 1..7
        val speeds = (1..7).map { "$it 段" }
        ArrayAdapter(this, android.R.layout.simple_spinner_item, speeds).also {
            it.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
            b.speedSpinner.adapter = it
        }
        b.speedSpinner.setSelection(3)
        // timer 0..12
        val timers = (0..12).map { if (it == 0) "關閉" else "$it 小時" }
        ArrayAdapter(this, android.R.layout.simple_spinner_item, timers).also {
            it.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
            b.timerSpinner.adapter = it
        }
    }

    private fun neededPerms(): Array<String> =
        if (Build.VERSION.SDK_INT >= 31)
            arrayOf(Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT)
        else
            arrayOf(Manifest.permission.ACCESS_FINE_LOCATION)

    private fun hasPerms(): Boolean =
        neededPerms().all { ContextCompat.checkSelfPermission(this, it) == PackageManager.PERMISSION_GRANTED }

    private fun wireUi() {
        b.btnConnect.setOnClickListener {
            if (!hasPerms()) ActivityCompat.requestPermissions(this, neededPerms(), 1)
            else startScan()
        }
        b.btnOn.setOnClickListener { if (ready) ble.uart("a1", 1) }
        b.btnOff.setOnClickListener { if (ready) ble.uart("a1", 0) }

        b.speedSpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(p: AdapterView<*>?, v: View?, pos: Int, id: Long) {
                if (!updatingUi && ready) ble.uart("d1", pos + 1)
            }
            override fun onNothingSelected(p: AdapterView<*>?) {}
        }
        b.timerSpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(p: AdapterView<*>?, v: View?, pos: Int, id: Long) {
                if (!updatingUi && ready) ble.uart("d2", pos)
            }
            override fun onNothingSelected(p: AdapterView<*>?) {}
        }

        b.swVertical.setOnCheckedChangeListener { _, c -> if (!updatingUi && ready) ble.uart("a2", if (c) 1 else 0) }
        b.swHorizontal.setOnCheckedChangeListener { _, c -> if (!updatingUi && ready) ble.uart("a5", if (c) 1 else 0) }
        b.swSleep.setOnCheckedChangeListener { _, c -> if (!updatingUi && ready) ble.uart("a3", if (c) 1 else 0) }
        b.swAi.setOnCheckedChangeListener { _, c -> if (!updatingUi && ready) ble.uart("a4", if (c) 1 else 0) }

        b.angleGroup.addOnButtonCheckedListener { _, checkedId, isChecked ->
            if (updatingUi || !ready || !isChecked) return@addOnButtonCheckedListener
            val v = when (checkedId) { R.id.angle30 -> 0; R.id.angle60 -> 1; R.id.angle120 -> 2; else -> return@addOnButtonCheckedListener }
            ble.uart("c1", v)
        }
    }

    private fun startScan() {
        foundDevices.clear(); foundLabels.clear()
        scanAdapter = ArrayAdapter(this, android.R.layout.simple_list_item_1, foundLabels)
        scanDialog = AlertDialog.Builder(this)
            .setTitle("選擇裝置（搜尋中…）")
            .setAdapter(scanAdapter) { _, which ->
                ble.stopScan()
                ble.connectTo(foundDevices[which])
            }
            .setNegativeButton("取消") { d, _ -> ble.stopScan(); d.dismiss() }
            .create()
        scanDialog?.show()
        ble.scan()
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (grantResults.isNotEmpty() && grantResults.all { it == PackageManager.PERMISSION_GRANTED }) startScan()
        else b.statusText.text = "需要藍牙權限才能連線"
    }

    private fun setControlsEnabled(on: Boolean) {
        b.btnOn.isEnabled = on; b.btnOff.isEnabled = on
        b.speedSpinner.isEnabled = on; b.timerSpinner.isEnabled = on
        b.swVertical.isEnabled = on; b.swHorizontal.isEnabled = on
        b.swSleep.isEnabled = on; b.swAi.isEnabled = on
        for (i in 0 until b.angleGroup.childCount) b.angleGroup.getChildAt(i).isEnabled = on
    }

    // ---- FanBle.Listener ----
    override fun onStatus(msg: String) { b.statusText.text = msg }

    override fun onDeviceFound(device: BluetoothDevice, name: String, rssi: Int) {
        // only list supported fans (advertised name FY0002), hide everything else
        if (name != Protocol.DEVICE_NAME) return
        val label = "$name   ${rssi}dBm"
        foundLabels.add(label)
        foundDevices.add(device)
        scanAdapter?.notifyDataSetChanged()
    }

    override fun onScanFinished() {
        scanDialog?.setTitle(if (foundLabels.isEmpty()) "找不到風扇，請靠近並重試" else "選擇風扇")
    }

    override fun onReady(r: Boolean) {
        ready = r
        setControlsEnabled(r)
        scanDialog?.dismiss()
    }

    override fun onState(state: FanState) {
        updatingUi = true
        val on = state.a1 == 1
        b.statusText.text = buildString {
            append(if (on) "● 電源：開\n" else "○ 電源：關\n")
            append("風速：${state.d1} / 7\n")
            append("上下擺頭：${if (state.a2 == 1) "開" else "關"}   左右擺頭：${if (state.a5 == 1) "開" else "關"}\n")
            append("角度：${if (state.angleDeg > 0) "${state.angleDeg}°" else "-"}   ")
            append("睡眠：${if (state.a3 == 1) "開" else "關"}   AI：${if (state.a4 == 1) "開" else "關"}\n")
            append("定時：${if (state.d2 == 0) "關" else "${state.d2} 小時"}")
        }
        if (state.d1 in 1..7) b.speedSpinner.setSelection(state.d1 - 1)
        b.timerSpinner.setSelection(state.d2.coerceIn(0, 12))
        b.swVertical.isChecked = state.a2 == 1
        b.swHorizontal.isChecked = state.a5 == 1
        b.swSleep.isChecked = state.a3 == 1
        b.swAi.isChecked = state.a4 == 1
        when (state.c1) {
            0 -> b.angleGroup.check(R.id.angle30)
            1 -> b.angleGroup.check(R.id.angle60)
            2 -> b.angleGroup.check(R.id.angle120)
        }
        updatingUi = false
    }

    override fun onDestroy() {
        super.onDestroy()
        ble.stop()
    }
}
