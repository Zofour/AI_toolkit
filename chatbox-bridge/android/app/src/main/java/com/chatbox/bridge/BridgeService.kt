package com.chatbox.bridge

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

/**
 * 前台服务：常驻连接（App 退到后台/锁屏也保持 WS），并在收到新回复时本地通知。
 */
class BridgeService : Service() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        createChannels()
        startAsForeground(buildOngoing("正在连接…"))

        val s = Settings(this)
        if (s.configured) {
            BridgeRepo.start(s.wsUrl, s.token)
        } else {
            updateOngoing(buildOngoing("尚未配置服务器"))
        }

        scope.launch {
            BridgeRepo.state.collect { st -> onState(st) }
        }
        scope.launch {
            BridgeRepo.events.collect { ev ->
                if (ev.type == "msg.done" && Settings(this@BridgeService).notifyLocal) {
                    val text = ev.data.optString("text").take(160)
                    val err = ev.data.optString("error")
                    if (text.isNotBlank() || err.isNotBlank()) {
                        notifyReply(if (err.isNotBlank()) "发送出错：$err" else text)
                    }
                }
            }
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val s = Settings(this)
        if (s.configured) BridgeRepo.start(s.wsUrl, s.token)
        return START_STICKY
    }

    override fun onDestroy() {
        BridgeRepo.stop()
        scope.coroutineContext[kotlinx.coroutines.Job]?.cancel()
        super.onDestroy()
    }

    private fun onState(st: ConnState) {
        val text = when (st) {
            ConnState.CONNECTED -> "已连接，实时接收中"
            ConnState.CONNECTING -> "正在连接…"
            ConnState.DISCONNECTED -> "已断开"
            ConnState.ERROR -> "连接失败，自动重试中"
        }
        updateOngoing(buildOngoing(text))
    }

    // ---------------- notifications
    private fun createChannels() {
        val mgr = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            mgr.createNotificationChannel(
                NotificationChannel(CH_ONGOING, "桥接状态", NotificationManager.IMPORTANCE_LOW)
            )
            mgr.createNotificationChannel(
                NotificationChannel(CH_REPLY, "新回复", NotificationManager.IMPORTANCE_DEFAULT)
            )
        }
    }

    private fun contentIntent(): PendingIntent {
        val i = Intent(this, MainActivity::class.java)
        i.flags = Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or
                (if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) PendingIntent.FLAG_IMMUTABLE else 0)
        return PendingIntent.getActivity(this, 0, i, flags)
    }

    private fun buildOngoing(text: String): Notification =
        Notification.Builder(this, CH_ONGOING)
            .setContentTitle("Chatbox 桥")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.stat_notify_sync)
            .setOngoing(true)
            .setContentIntent(contentIntent())
            .build()

    private fun startAsForeground(n: Notification) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(NOTIF_ONGOING, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        } else {
            startForeground(NOTIF_ONGOING, n)
        }
    }

    private fun updateOngoing(n: Notification) {
        val mgr = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        mgr.notify(NOTIF_ONGOING, n)
    }

    private fun notifyReply(text: String) {
        val mgr = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val n = Notification.Builder(this, CH_REPLY)
            .setContentTitle("Chatbox 新回复")
            .setContentText(text)
            .setStyle(Notification.BigTextStyle().bigText(text))
            .setSmallIcon(android.R.drawable.stat_notify_chat)
            .setAutoCancel(true)
            .setContentIntent(contentIntent())
            .build()
        mgr.notify(NOTIF_REPLY, n)
    }

    companion object {
        private const val CH_ONGOING = "bridge_ongoing"
        private const val CH_REPLY = "bridge_reply"
        private const val NOTIF_ONGOING = 1001
        private const val NOTIF_REPLY = 1002
    }
}
