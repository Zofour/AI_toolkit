package com.ollama.mobile

import android.content.Context

class Settings(ctx: Context) {

    private val sp = ctx.getSharedPreferences("ollama_mobile", Context.MODE_PRIVATE)

    var serverUrl: String
        get() = sp.getString("server_url", DEFAULT_URL) ?: DEFAULT_URL
        set(v) = sp.edit().putString("server_url", v).apply()

    /** 备用地址：主地址（Tailscale）连不上时自动回退，例如家里同一 Wi-Fi 的局域网 IP */
    var backupUrl: String
        get() = sp.getString("backup_url", "http://192.168.1.100:11434") ?: ""
        set(v) = sp.edit().putString("backup_url", v).apply()

    var keepAlive: String
        get() = sp.getString("keep_alive", "5m") ?: "5m"
        set(v) = sp.edit().putString("keep_alive", v).apply()

    var systemPrompt: String
        get() = sp.getString("system_prompt", "") ?: ""
        set(v) = sp.edit().putString("system_prompt", v).apply()

    var lastModel: String
        get() = sp.getString("last_model", "") ?: ""
        set(v) = sp.edit().putString("last_model", v).apply()

    companion object {
        /** 默认就是本机电脑的 Tailscale IP，换机时在设置里改 */
        const val DEFAULT_URL = "http://100.64.0.1:11434"
    }
}
