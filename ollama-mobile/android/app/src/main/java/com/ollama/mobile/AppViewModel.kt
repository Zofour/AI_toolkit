package com.ollama.mobile

import android.app.Application
import android.net.Uri
import android.os.SystemClock
import androidx.lifecycle.AndroidViewModel
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.UUID

class AppViewModel(app: Application) : AndroidViewModel(app) {

    private val settings = Settings(app)
    private val store = Store(app)
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var client = OllamaClient(settings.serverUrl)

    private val _state = MutableStateFlow(
        UiState(
            serverUrl = settings.serverUrl,
            backupUrl = settings.backupUrl,
            keepAlive = settings.keepAlive,
            systemPrompt = settings.systemPrompt,
        )
    )
    val state: StateFlow<UiState> = _state.asStateFlow()

    private var chatJob: Job? = null
    private var saveJob: Job? = null

    init {
        val saved = store.load()
        val convs = if (saved.isEmpty()) {
            listOf(newConv(settings.lastModel))
        } else {
            saved
        }
        _state.update { it.copy(conversations = convs, currentId = convs.first().id) }
        refresh()
    }

    override fun onCleared() {
        super.onCleared()
        chatJob?.cancel()
        scope.cancel()
    }

    // ---------------- 基础工具 ----------------

    private fun newConv(model: String) = Conversation(
        id = UUID.randomUUID().toString(),
        title = "新对话",
        model = model,
        messages = emptyList(),
    )

    private fun current(): Conversation? {
        val s = _state.value
        return s.conversations.firstOrNull { it.id == s.currentId }
    }

    private fun updateConv(c: Conversation) {
        _state.update { s ->
            s.copy(conversations = s.conversations.map { if (it.id == c.id) c else it })
        }
    }

    private fun scheduleSave() {
        saveJob?.cancel()
        saveJob = scope.launch {
            delay(800)
            val snapshot = _state.value.conversations
            withContext(Dispatchers.IO) { store.save(snapshot) }
        }
    }

    private fun toast(msg: String) {
        _state.update { it.copy(toast = msg) }
    }

    fun consumeToast() {
        _state.update { it.copy(toast = null) }
    }

    // ---------------- 服务器 / 模型 ----------------

    fun refresh() {
        scope.launch {
            _state.update { it.copy(busy = true, status = "正在连接服务器…") }

            // 主地址（Tailscale）→ 备用地址（例如家里 Wi-Fi 的局域网 IP）依次尝试
            val candidates = listOf(settings.serverUrl, settings.backupUrl)
                .map { it.trim().trimEnd('/') }
                .filter { it.isNotBlank() }
                .distinct()

            var ok: OllamaClient? = null
            var models: List<OllamaModel> = emptyList()
            val failed = mutableListOf<String>()

            for (c in candidates) {
                val cl = OllamaClient(c)
                try {
                    _state.update { it.copy(status = "连接 $c …") }
                    cl.probe()
                    models = cl.listModels()
                    ok = cl
                    break
                } catch (e: Exception) {
                    failed += c.removePrefix("http://").removePrefix("https://")
                }
            }

            val working = ok
            if (working == null) {
                _state.update { it.copy(online = false, busy = false, status = "") }
                toast("连不上：${failed.joinToString("、")}")
                return@launch
            }
            client = working
            val loaded = runCatching { working.running() }.getOrDefault(emptyList())

            // 当前会话没有可用模型时，自动挑一个
            val cur = current()
            val pick = when {
                cur == null -> null
                models.isEmpty() -> null
                cur.model.isBlank() || models.none { it.name == cur.model } -> models.first().name
                else -> cur.model
            }
            if (cur != null && pick != null && pick != cur.model) {
                updateConv(cur.copy(model = pick))
                settings.lastModel = pick
                scheduleSave()
            }
            _state.update {
                it.copy(
                    models = models,
                    loaded = loaded,
                    online = true,
                    busy = false,
                    status = "",
                    activeUrl = working.baseUrl,
                )
            }

            // 后台探测哪些模型能看图（capabilities 含 vision）
            scope.launch {
                val vs = mutableSetOf<String>()
                models.forEach { m ->
                    val caps = runCatching { working.capabilities(m.name) }.getOrDefault(emptySet())
                    if (caps.contains("vision")) vs += m.name
                }
                _state.update { it.copy(visionModels = vs) }
            }
        }
    }

    /** 切换模型：先卸载上一个（以及其它仍驻留的模型），保证显存只留一个新模型 */
    fun selectModel(name: String) {
        val conv = current() ?: return
        if (conv.model == name) return
        val old = conv.model
        updateConv(conv.copy(model = name))
        settings.lastModel = name
        scheduleSave()

        scope.launch {
            _state.update { it.copy(busy = true, status = if (old.isBlank()) "切换模型…" else "卸载 $old …") }
            try {
                if (old.isNotBlank() && old != name) {
                    runCatching { client.unload(old) }
                }
                val running = runCatching { client.running() }.getOrDefault(emptyList())
                running.filter { it != name }.forEach { m ->
                    _state.update { it.copy(status = "卸载 $m …") }
                    runCatching { client.unload(m) }
                }
                val left = runCatching { client.running() }.getOrDefault(emptyList())
                _state.update { it.copy(loaded = left, busy = false, status = "") }
                toast("已切换到 $name")
            } catch (e: Exception) {
                _state.update { it.copy(busy = false, status = "") }
                toast("切换失败：${e.message}")
            }
        }
    }

    /** 手动释放显存：把当前所有驻留模型都卸掉 */
    fun unloadAll() {
        scope.launch {
            _state.update { it.copy(busy = true, status = "正在卸载模型…") }
            try {
                val running = client.running()
                if (running.isEmpty()) {
                    _state.update { it.copy(busy = false, status = "") }
                    toast("当前没有模型驻留显存")
                    return@launch
                }
                running.forEach { m ->
                    _state.update { it.copy(status = "卸载 $m …") }
                    runCatching { client.unload(m) }
                }
                val left = runCatching { client.running() }.getOrDefault(emptyList())
                _state.update { it.copy(loaded = left, busy = false, status = "") }
                toast(if (left.isEmpty()) "已全部卸载，显存已释放" else "仍有驻留：${left.joinToString()}")
            } catch (e: Exception) {
                _state.update { it.copy(busy = false, status = "") }
                toast("卸载失败：${e.message}")
            }
        }
    }

    /** 发消息前确认：除目标模型外，把别的模型都踢出显存 */
    private suspend fun ensureOnly(model: String) {
        val running = runCatching { client.running() }.getOrDefault(emptyList())
        if (running.isEmpty() || running.all { it == model }) return
        running.filter { it != model }.forEach { m ->
            runCatching { client.unload(m) }
        }
        val left = runCatching { client.running() }.getOrDefault(emptyList())
        _state.update { it.copy(loaded = left) }
    }

    // ---------------- 会话管理 ----------------

    fun newChat() {
        chatJob?.cancel()
        val model = current()?.model?.ifBlank { null }
            ?: _state.value.models.firstOrNull()?.name
            ?: settings.lastModel
        val c = newConv(model)
        _state.update {
            it.copy(conversations = listOf(c) + it.conversations, currentId = c.id, streaming = false)
        }
        scheduleSave()
    }

    fun selectConversation(id: String) {
        chatJob?.cancel()
        _state.update { it.copy(currentId = id, streaming = false) }
    }

    fun deleteConversation(id: String) {
        val s = _state.value
        val rest = s.conversations.filterNot { it.id == id }
        val list = if (rest.isEmpty()) {
            listOf(newConv(s.models.firstOrNull()?.name ?: settings.lastModel))
        } else {
            rest
        }
        _state.update {
            it.copy(
                conversations = list,
                currentId = if (it.currentId == id) list.first().id else it.currentId,
            )
        }
        scheduleSave()
    }

    fun clearMessages() {
        val c = current() ?: return
        updateConv(c.copy(messages = emptyList(), title = "新对话"))
        scheduleSave()
    }

    // ---------------- 图片 ----------------

    fun addPendingImage(uri: Uri) {
        val ctx = getApplication<Application>()
        scope.launch {
            if (_state.value.pendingImages.size >= ImageStore.MAX_COUNT) {
                toast("一次最多 ${ImageStore.MAX_COUNT} 张图")
                return@launch
            }
            _state.update { it.copy(status = "读取图片…") }
            val name = withContext(Dispatchers.IO) { ImageStore.import(ctx, uri) }
            _state.update { it.copy(status = "") }
            if (name == null) toast("读取图片失败") else {
                _state.update { it.copy(pendingImages = it.pendingImages + name) }
            }
        }
    }

    fun removePendingImage(name: String) {
        val ctx = getApplication<Application>()
        _state.update { it.copy(pendingImages = it.pendingImages - name) }
        scope.launch { withContext(Dispatchers.IO) { ImageStore.delete(ctx, name) } }
    }

    // ---------------- 对话 ----------------

    fun send(text: String) {
        val raw = text.trim()
        val s = _state.value
        if (s.streaming) return
        val conv = current() ?: return
        if (conv.model.isBlank()) {
            toast("还没选模型：点顶部模型名选择")
            return
        }
        val images = s.pendingImages.toList()
        if (raw.isEmpty() && images.isEmpty()) return
        if (images.isNotEmpty() && s.visionModels.isNotEmpty() && !s.visionModels.contains(conv.model)) {
            toast("${conv.model} 看不了图，请换成带「视觉」标记的模型")
            return
        }

        val userMsg = ChatMessage(role = "user", content = raw, imageNames = images)
        val placeholder = ChatMessage(role = "assistant", content = "")
        val base = conv.copy(
            title = if (conv.title == "新对话" || conv.title.isBlank()) {
                (raw.ifBlank { "图片" }).take(20)
            } else {
                conv.title
            },
            messages = conv.messages + userMsg + placeholder,
        )
        updateConv(base)
        _state.update { it.copy(pendingImages = emptyList()) }
        scheduleSave()

        val convId = base.id
        val idx = base.messages.size - 1
        val history = buildList {
            if (s.systemPrompt.isNotBlank()) add(ChatMessage(role = "system", content = s.systemPrompt))
            addAll(conv.messages)
            add(userMsg)
        }

        chatJob = scope.launch {
            _state.update {
                it.copy(streaming = true, status = if (images.isEmpty()) "生成中…" else "上传图片…")
            }
            val ctx = getApplication<Application>()
            val b64 = if (images.isEmpty()) {
                emptyList()
            } else {
                withContext(Dispatchers.IO) { images.mapNotNull { ImageStore.base64(ctx, it) } }
            }
            _state.update { it.copy(status = "生成中…") }

            val content = StringBuilder()
            val thinking = StringBuilder()
            var lastPush = 0L
            try {
                ensureOnly(base.model)
                client.chatFlow(base.model, history, s.keepAlive, b64).collect { d ->
                    content.append(d.content)
                    thinking.append(d.thinking)
                    val now = SystemClock.elapsedRealtime()
                    if (now - lastPush >= 80) {
                        lastPush = now
                        patch(convId, idx, content.toString(), thinking.toString(), false)
                    }
                }
                patch(convId, idx, content.toString(), thinking.toString(), false)
                _state.update { it.copy(streaming = false, status = "") }
                scheduleSave()
            } catch (e: CancellationException) {
                val c = content.toString()
                patch(
                    convId, idx,
                    if (c.isBlank()) "（已停止）" else c,
                    thinking.toString(), false
                )
                _state.update { it.copy(streaming = false, status = "") }
                scheduleSave()
                throw e
            } catch (e: Exception) {
                val msg = e.message ?: e.toString()
                val c = content.toString()
                patch(
                    convId, idx,
                    if (c.isBlank()) "⚠️ $msg" else "$c\n\n⚠️ $msg",
                    thinking.toString(), true
                )
                _state.update { it.copy(streaming = false, status = "") }
                scheduleSave()
            } finally {
                runCatching {
                    val left = client.running()
                    _state.update { it.copy(loaded = left) }
                }
            }
        }
    }

    fun stop() {
        chatJob?.cancel()
        chatJob = null
        _state.update { it.copy(streaming = false, status = "") }
    }

    private fun patch(convId: String, idx: Int, content: String, thinking: String, error: Boolean) {
        _state.update { s ->
            s.copy(
                conversations = s.conversations.map { c ->
                    if (c.id != convId || idx !in c.messages.indices) c
                    else {
                        val list = c.messages.toMutableList()
                        list[idx] = list[idx].copy(content = content, thinking = thinking, error = error)
                        c.copy(messages = list)
                    }
                }
            )
        }
    }

    // ---------------- 设置 ----------------

    fun saveSettings(url: String, backup: String, keepAlive: String, systemPrompt: String) {
        val clean = url.trim().trimEnd('/')
        val cleanBackup = backup.trim().trimEnd('/')
        settings.serverUrl = clean
        settings.backupUrl = cleanBackup
        settings.keepAlive = keepAlive.trim().ifBlank { "5m" }
        settings.systemPrompt = systemPrompt
        client = OllamaClient(clean)
        _state.update {
            it.copy(
                serverUrl = clean,
                backupUrl = cleanBackup,
                keepAlive = settings.keepAlive,
                systemPrompt = systemPrompt,
                online = null,
            )
        }
        refresh()
    }
}
