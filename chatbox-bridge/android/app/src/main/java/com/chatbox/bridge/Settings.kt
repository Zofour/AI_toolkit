package com.chatbox.bridge

import android.content.Context

/** 手机端持久化设置（SharedPreferences）。 */
class Settings(ctx: Context) {
    private val sp = ctx.applicationContext.getSharedPreferences("bridge_settings", Context.MODE_PRIVATE)

    var wsUrl: String
        get() = sp.getString("wsUrl", "") ?: ""
        set(v) = sp.edit().putString("wsUrl", v.trim()).apply()

    var token: String
        get() = sp.getString("token", "") ?: ""
        set(v) = sp.edit().putString("token", v.trim()).apply()

    var notifyLocal: Boolean
        get() = sp.getBoolean("notifyLocal", true)
        set(v) = sp.edit().putBoolean("notifyLocal", v).apply()

    val configured: Boolean get() = wsUrl.isNotBlank() && token.isNotBlank()

    /** 由 ws://... 推导 REST base http://... */
    fun httpBase(): String {
        var u = wsUrl.trim().removeSuffix("/")
        if (u.endsWith("/ws")) u = u.dropLast(3)
        return u.replaceFirst("ws://", "http://").replaceFirst("wss://", "https://")
    }
}
