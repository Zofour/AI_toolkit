package com.chatbox.filehub

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.net.URLEncoder
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.TimeUnit

/** 电脑端返回的一个目录项 / 媒体项 */
data class MediaEntry(
    val name: String,
    val path: String,
    val type: String,
    val size: Long,
    val mtime: Long,
) {
    val isDir: Boolean get() = type == "dir"
    val isImage: Boolean get() = type == "image"
    val isVideo: Boolean get() = type == "video"
    val isMedia: Boolean get() = isImage || isVideo
}

class ApiException(val code: Int, message: String) : Exception(message)

/**
 * 只读客户端：只会发 GET，没有任何写/删/改的能力。
 */
class Api(val baseUrl: String, private val token: String) {

    companion object {
        val client: OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(6, TimeUnit.SECONDS)
            .readTimeout(20, TimeUnit.SECONDS)
            .retryOnConnectionFailure(true)
            .build()

        fun enc(s: String): String = URLEncoder.encode(s, "UTF-8").replace("+", "%20")

        /** 允许用户只填 100.x.x.x:8730 */
        fun normalizeBase(input: String): String {
            var s = input.trim()
            if (s.isEmpty()) return s
            if (!s.startsWith("http://") && !s.startsWith("https://")) s = "http://$s"
            while (s.endsWith("/")) s = s.dropLast(1)
            return s
        }
    }

    fun fileUrl(path: String): String = "$baseUrl/f?path=${enc(path)}&t=$token"

    fun thumbUrl(path: String, w: Int): String = "$baseUrl/t?path=${enc(path)}&w=$w&t=$token"

    private suspend fun raw(path: String): String = withContext(Dispatchers.IO) {
        val sep = if (path.contains('?')) '&' else '?'
        val req = Request.Builder().url("$baseUrl$path${sep}t=$token").build()
        client.newCall(req).execute().use { resp ->
            val body = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) {
                throw ApiException(
                    resp.code, when (resp.code) {
                        401 -> "令牌不对"
                        403 -> "没有权限"
                        404 -> "路径不存在"
                        else -> "HTTP ${resp.code}"
                    }
                )
            }
            body
        }
    }

    /** 返回服务端电脑的名字 */
    suspend fun ping(): String = JSONObject(raw("/api/ping")).optString("name", "电脑")

    suspend fun list(path: String, sort: String = "name"): List<MediaEntry> {
        val o = JSONObject(raw("/api/list?path=${enc(path)}&sort=$sort"))
        val arr = o.optJSONArray("entries") ?: return emptyList()
        val out = ArrayList<MediaEntry>(arr.length())
        for (i in 0 until arr.length()) {
            val e = arr.getJSONObject(i)
            out.add(
                MediaEntry(
                    name = e.optString("name"),
                    path = e.optString("path"),
                    type = e.optString("type", "file"),
                    size = e.optLong("size"),
                    mtime = e.optLong("mtime"),
                )
            )
        }
        return out
    }
}

class Prefs(ctx: Context) {
    private val sp = ctx.applicationContext.getSharedPreferences("filehub", Context.MODE_PRIVATE)

    var baseUrl: String
        get() = sp.getString("base", DEFAULT_BASE) ?: DEFAULT_BASE
        set(v) = sp.edit().putString("base", v).apply()

    var token: String
        get() = sp.getString("token", DEFAULT_TOKEN) ?: DEFAULT_TOKEN
        set(v) = sp.edit().putString("token", v).apply()

    var configured: Boolean
        get() = sp.getBoolean("configured", false)
        set(v) = sp.edit().putBoolean("configured", v).apply()

    companion object {
        const val DEFAULT_BASE = "http://100.64.0.1:8730"
        const val DEFAULT_TOKEN = "CHANGE_ME_TOKEN"
    }
}

// ---------------------------------------------------------------- 小工具

fun humanSize(bytes: Long): String {
    if (bytes <= 0) return ""
    val units = arrayOf("B", "KB", "MB", "GB", "TB")
    var v = bytes.toDouble()
    var i = 0
    while (v >= 1024 && i < units.lastIndex) {
        v /= 1024; i++
    }
    return if (i == 0) "${bytes} B" else String.format(Locale.US, "%.1f %s", v, units[i])
}

fun humanDate(epochSec: Long): String {
    if (epochSec <= 0) return ""
    return SimpleDateFormat("yyyy-MM-dd HH:mm", Locale.getDefault()).format(Date(epochSec * 1000))
}
