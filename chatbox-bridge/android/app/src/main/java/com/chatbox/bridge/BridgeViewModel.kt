package com.chatbox.bridge

import android.app.Application
import android.content.Intent
import androidx.lifecycle.AndroidViewModel
import kotlinx.coroutines.flow.MutableStateFlow

class BridgeViewModel(app: Application) : AndroidViewModel(app) {
    private val settings = Settings(app)

    val state = BridgeRepo.state
    val sessions = BridgeRepo.sessions
    val messages = BridgeRepo.messages
    val canControl = BridgeRepo.canControl
    val controlError = BridgeRepo.controlError
    val newSession = BridgeRepo.newSession

    fun createSession() = BridgeRepo.createSession()

    fun sendMessage(text: String, sessionId: String? = null) = BridgeRepo.sendMessage(text, sessionId)

    fun blobUrl(name: String) = BridgeRepo.blobUrl(name)

    val configured = MutableStateFlow(settings.configured)
    val wsUrl = MutableStateFlow(settings.wsUrl)
    val token = MutableStateFlow(settings.token)
    val notifyLocal = MutableStateFlow(settings.notifyLocal)

    fun saveAndConnect(url: String, tk: String, notify: Boolean) {
        settings.wsUrl = url
        settings.token = tk
        settings.notifyLocal = notify
        wsUrl.value = url.trim()
        token.value = tk.trim()
        notifyLocal.value = notify
        configured.value = settings.configured
        val ctx = getApplication<Application>()
        val i = Intent(ctx, BridgeService::class.java)
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O) {
            ctx.startForegroundService(i)
        } else {
            ctx.startService(i)
        }
    }

    fun disconnect() {
        val ctx = getApplication<Application>()
        ctx.stopService(Intent(ctx, BridgeService::class.java))
    }

    fun openSession(sid: String) = BridgeRepo.openSession(sid)

    fun deleteSession(sid: String) = BridgeRepo.deleteSession(sid)
}
