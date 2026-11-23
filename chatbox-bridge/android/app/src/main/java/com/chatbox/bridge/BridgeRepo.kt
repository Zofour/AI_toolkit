package com.chatbox.bridge

import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * 全局单例：唯一的 WebSocket 连接 + 状态。UI(ViewModel) 与前台服务共享它。
 */
object BridgeRepo {
    private const val TAG = "BridgeRepo"
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private val http = OkHttpClient.Builder()
        .pingInterval(20, TimeUnit.SECONDS)
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .build()

    val state = MutableStateFlow(ConnState.DISCONNECTED)
    val sessions = MutableStateFlow<List<SessionMeta>>(emptyList())
    val messages = MutableStateFlow<Map<String, List<Message>>>(emptyMap())
    val events = MutableSharedFlow<BridgeEvent>(extraBufferCapacity = 256)

    /** 回控是否可用（电脑上的注入器是否在线） */
    val canControl = MutableStateFlow(false)
    /** 最近一次回控错误（供 UI 提示） */
    val controlError = MutableStateFlow<String?>(null)
    /** 新建会话后拿到真实会话 id 时发出 */
    val newSession = MutableSharedFlow<String>(extraBufferCapacity = 2)
    private var pendingNew = false

    private var ws: WebSocket? = null
    private var wsUrl = ""
    private var token = ""
    private var manualStop = true
    private var attempt = 0

    @Volatile
    var running = false
        private set

    val httpBase: String
        get() {
            var u = wsUrl.removeSuffix("/")
            if (u.endsWith("/ws")) u = u.dropLast(3)
            return u.replaceFirst("ws://", "http://").replaceFirst("wss://", "https://")
        }

    @Synchronized
    fun start(url: String, tk: String) {
        wsUrl = url.trim()
        token = tk.trim()
        manualStop = false
        if (ws != null) return
        if (wsUrl.isBlank() || token.isBlank()) {
            state.value = ConnState.ERROR
            return
        }
        attempt = 0
        open()
    }

    @Synchronized
    fun stop() {
        manualStop = true
        running = false
        ws?.close(1000, "bye")
        ws = null
        state.value = ConnState.DISCONNECTED
    }

    private fun open() {
        state.value = ConnState.CONNECTING
        val url = wsUrl + (if (wsUrl.contains("?")) "&" else "?") + "token=" + token
        Log.i(TAG, "connecting $url")
        ws = http.newWebSocket(Request.Builder().url(url).build(), listener)
    }

    private fun reconnect() {
        if (manualStop) return
        running = false
        state.value = ConnState.ERROR
        attempt++
        val delayMs = minOf(30_000L, 1000L shl minOf(attempt, 5))
        Log.i(TAG, "reconnect in ${delayMs}ms (attempt=$attempt)")
        scope.launch {
            delay(delayMs)
            if (!manualStop && ws == null) open()
        }
    }

    private fun send(obj: JSONObject): Boolean = ws?.send(obj.toString()) ?: false

    /** 打开某会话：按 seq=0 回放历史，之后持续接收。 */
    fun openSession(sid: String) {
        messages.value = messages.value.toMutableMap().apply { this[sid] = emptyList() }
        send(
            JSONObject().put("type", "subscribe")
                .put("data", JSONObject().put("sessionId", sid).put("sinceSeq", 0))
        )
    }

    fun subscribeAll() = send(JSONObject().put("type", "subscribe").put("data", JSONObject()))

    /** 回控预留接口（当前服务端返回 not_implemented）。 */
    fun sendControl(type: String, data: JSONObject = JSONObject()): Boolean =
        send(JSONObject().put("type", type).put("data", data))

    /** 手机发一条消息 → 交给电脑上的注入器打进 Chatbox 对应会话。 */
    fun sendMessage(text: String, sessionId: String? = null): Boolean {
        val t = text.trim()
        if (t.isEmpty()) return false
        val data = JSONObject().put("text", t)
            .put("reqId", java.util.UUID.randomUUID().toString().take(8))
        if (!sessionId.isNullOrBlank()) data.put("sessionId", sessionId)
        return sendControl("control.send", data)
    }

    private val listener = object : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) {
            attempt = 0
            running = true
            state.value = ConnState.CONNECTED
            subscribeAll()
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            val ev = try {
                BridgeEvent(JSONObject(text))
            } catch (e: Exception) {
                return
            }
            handle(ev)
            events.tryEmit(ev)
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            Log.w(TAG, "ws failure: ${t.message}")
            if (ws === webSocket) ws = null
            reconnect()
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
            Log.i(TAG, "ws closed: $code $reason")
            if (ws === webSocket) ws = null
            if (manualStop) state.value = ConnState.DISCONNECTED else reconnect()
        }
    }

    private fun handle(ev: BridgeEvent) {
        when (ev.type) {
            "hello" -> {
                canControl.value = ev.data.optBoolean("canControl", false)
                val arr = ev.data.optJSONArray("sessions") ?: JSONArray()
                val list = ArrayList<SessionMeta>()
                for (i in 0 until arr.length()) {
                    val o = arr.optJSONObject(i) ?: continue
                    list.add(
                        SessionMeta(
                            o.optString("id"), o.optString("title"),
                            o.optLong("updated"), o.optInt("seq"), o.optString("last")
                        )
                    )
                }
                sessions.value = list
            }
            "msg.user", "msg.begin", "msg.delta", "msg.done",
            "msg.reason", "msg.tool", "msg.tool_result", "msg.image" -> applyMessage(ev)
            "session.deleted" -> removeSession(ev.sessionId)
            "bridge.status" -> canControl.value = ev.data.optBoolean("canControl", false)
            "session.upsert" -> {
                val o = ev.data
                val sid = o.optString("id")
                if (sid.isNotBlank()) {
                    val meta = SessionMeta(
                        sid, o.optString("title"), o.optLong("updated"),
                        o.optInt("seq"), o.optString("last")
                    )
                    val list = sessions.value.toMutableList()
                    val i = list.indexOfFirst { it.id == sid }
                    if (i < 0) list.add(0, meta) else list[i] = meta
                    sessions.value = list.sortedByDescending { it.updated }
                }
            }
            "control.result" -> {
                val mode = ev.data.optString("mode")
                if (ev.data.optBoolean("ok", false)) {
                    controlError.value = null
                } else {
                    if (mode == "new") pendingNew = false
                    controlError.value = when (val e = ev.data.optString("error")) {
                        "no_injector" -> "回控不可用：电脑上未运行注入器（用 start_bridge.bat 启动）"
                        "empty", "" -> null
                        else -> "操作失败：$e"
                    }
                }
            }
        }
    }

    @Synchronized
    private fun applyMessage(ev: BridgeEvent) {
        val sid = ev.sessionId ?: return
        val all = messages.value.toMutableMap()
        val cur = (all[sid] ?: emptyList()).toMutableList()
        val mid = ev.messageId
        when (ev.type) {
            "msg.user" -> upsert(cur, ev.messageId ?: "u${ev.seq}", "user", ev.text(), true, ts = ev.ts)
            "msg.begin" -> if (mid != null) upsert(cur, mid, "assistant", "", false, ts = ev.ts, turnId = mid)
            "msg.delta" -> if (mid != null) appendText(cur, mid, "assistant", ev.text(), ev.ts, mid)
            "msg.reason" -> if (mid != null) appendText(cur, "r:$mid", "reason", ev.text(), ev.ts, mid)
            "msg.tool" -> if (mid != null) {
                val idx = ev.data.optInt("index", 0)
                upsertTool(
                    cur, "t:$mid:$idx",
                    optName(ev.data, "name"),
                    ev.data.optString("argsDelta"), ev.ts, mid
                )
            }
            "msg.tool_result" -> {
                val tid = ev.data.optString("toolId").ifBlank { "tr${ev.seq}" }
                upsert(
                    cur, "tr:$tid", "tool_result", ev.data.optString("text"), true,
                    name = optName(ev.data, "name"), ts = ev.ts
                )
            }
            "msg.image" -> {
                val bid = ev.data.optString("blobId")
                if (bid.isNotBlank()) {
                    val id = "img:$bid"
                    if (cur.none { it.id == id }) {
                        cur.add(Message(id, "image", "", true, ts = ev.ts, blob = bid))
                    }
                }
            }
            "msg.done" -> if (mid != null) {
                for (i in cur.indices) {
                    if (cur[i].turnId == mid && !cur[i].done) cur[i] = cur[i].copy(done = true)
                }
                val ft = ev.data.optString("text")
                val i = cur.indexOfFirst { it.id == mid }
                if (ft.isNotBlank() && (i < 0 || cur[i].text != ft)) {
                    if (i < 0) cur.add(Message(mid, "assistant", ft, true, ts = ev.ts, turnId = mid))
                    else cur[i] = cur[i].copy(text = ft, done = true)
                }
                val err = ev.data.optString("error").takeIf { it.isNotBlank() }
                if (err != null) {
                    val j = cur.indexOfFirst { it.id == mid }
                    if (j >= 0) cur[j] = cur[j].copy(error = err, done = true)
                }
            }
        }
        all[sid] = cur
        messages.value = all

        val meta = sessions.value.toMutableList()
        val mi = meta.indexOfFirst { it.id == sid }
        val lastText = (cur.lastOrNull()?.text ?: "").take(120)
        if (mi < 0) {
            meta.add(0, SessionMeta(sid, sessionTitle(cur), ev.ts, ev.seq, lastText))
            sessions.value = meta
            refreshSessions()
            if (pendingNew) {
                pendingNew = false
                newSession.tryEmit(sid)
            }
        } else {
            meta[mi] = meta[mi].copy(updated = ev.ts, seq = maxOf(meta[mi].seq, ev.seq), last = lastText)
            sessions.value = meta.sortedByDescending { it.updated }
        }
    }

    private fun upsert(
        cur: MutableList<Message>, id: String, kind: String, text: String, done: Boolean,
        name: String? = null, ts: Long = 0, turnId: String? = null
    ) {
        val i = cur.indexOfFirst { it.id == id }
        if (i < 0) cur.add(Message(id, kind, text, done, name = name, ts = ts, turnId = turnId))
        else if (!cur[i].done) cur[i] = cur[i].copy(text = text, done = done)
    }

    private fun appendText(
        cur: MutableList<Message>, id: String, kind: String, add: String, ts: Long, turnId: String?
    ) {
        if (add.isEmpty()) return
        val i = cur.indexOfFirst { it.id == id }
        if (i < 0) cur.add(Message(id, kind, add, false, ts = ts, turnId = turnId))
        else cur[i] = cur[i].copy(text = cur[i].text + add)
    }

    /** org.json 的 optString 会把 JSON null 读成字符串 "null"，这里统一纠偏。 */
    /** 删除会话（服务端 + 本地）。 */
    fun deleteSession(sid: String) {
        scope.launch {
            try {
                val req = Request.Builder()
                    .url("$httpBase/sessions/$sid?token=$token").delete().build()
                http.newCall(req).execute().close()
            } catch (_: Exception) {
            }
            removeSession(sid)
        }
    }

    private fun removeSession(sid: String?) {
        if (sid == null) return
        sessions.value = sessions.value.filterNot { it.id == sid }
        messages.value = messages.value.toMutableMap().apply { remove(sid) }
    }

    /** 请电脑端新建一个会话（模型已默认：转发手机 / DeepSeek V4.1 Flash）。 */
    fun createSession(): Boolean {
        val ok = sendControl("control.new", JSONObject().put("reqId", java.util.UUID.randomUUID().toString().take(8)))
        if (ok) pendingNew = true
        return ok
    }

    /** 图片 blob 的完整取用地址（带 token）。 */
    fun blobUrl(name: String): String = "$httpBase/blobs/$name?token=$token"

    private fun optName(o: JSONObject, key: String): String? {
        if (o.isNull(key)) return null
        val v = o.optString(key)
        return v.takeIf { it.isNotBlank() && it != "null" }
    }

    private fun upsertTool(
        cur: MutableList<Message>, id: String, name: String?, argsDelta: String, ts: Long, turnId: String?
    ) {
        val i = cur.indexOfFirst { it.id == id }
        if (i < 0) cur.add(Message(id, "tool", argsDelta, false, name = name, ts = ts, turnId = turnId))
        else cur[i] = cur[i].copy(text = cur[i].text + argsDelta, name = name ?: cur[i].name)
    }

    private fun sessionTitle(cur: List<Message>): String =
        cur.firstOrNull { it.kind == "user" }?.text?.take(60)?.replace("\n", " ") ?: "(新会话)"

    private fun refreshSessions() {
        scope.launch {
            try {
                val req = Request.Builder().url("$httpBase/sessions?token=$token").build()
                http.newCall(req).execute().use { resp ->
                    val body = resp.body?.string() ?: return@use
                    val arr = JSONObject(body).optJSONArray("sessions") ?: return@use
                    val list = ArrayList<SessionMeta>()
                    for (i in 0 until arr.length()) {
                        val o = arr.getJSONObject(i)
                        list.add(
                            SessionMeta(
                                o.optString("id"), o.optString("title"),
                                o.optLong("updated"), o.optInt("seq"), o.optString("last")
                            )
                        )
                    }
                    sessions.value = list
                }
            } catch (_: Exception) {
            }
        }
    }
}
