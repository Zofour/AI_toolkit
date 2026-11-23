package com.chatbox.bridge

import org.json.JSONObject

/** 一条服务端推送事件（原样 JSON + 便捷取值）。 */
data class BridgeEvent(val raw: JSONObject) {
    val type: String get() = raw.optString("type")
    val sessionId: String? get() = raw.optString("sessionId").takeIf { it.isNotBlank() }
    val messageId: String? get() = raw.optString("messageId").takeIf { it.isNotBlank() }
    val seq: Int get() = raw.optInt("seq")
    val ts: Long get() = raw.optLong("ts")
    val data: JSONObject get() = raw.optJSONObject("data") ?: JSONObject()
    fun text(): String = data.optString("text")
}

data class SessionMeta(
    val id: String,
    val title: String,
    val updated: Long,
    val seq: Int,
    val last: String,
)

/** 时间线条目类型：user / assistant / reason(思考) / tool(调用) / tool_result(结果) */
data class Message(
    val id: String,
    val kind: String,
    val text: String,
    val done: Boolean,
    val name: String? = null,
    val error: String? = null,
    val ts: Long = 0,
    val turnId: String? = null,
    val blob: String? = null,
)

enum class ConnState { DISCONNECTED, CONNECTING, CONNECTED, ERROR }
