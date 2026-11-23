package com.ollama.mobile

/** /api/tags 返回的一个模型 */
data class OllamaModel(
    val name: String,
    val sizeBytes: Long = 0L,
    val paramSize: String = "",
    val family: String = "",
)

/** 一条消息。thinking 用于 deepseek-r1 / qwen3 这类思考模型；imageNames 是本地图片文件名 */
data class ChatMessage(
    val role: String,
    val content: String,
    val thinking: String = "",
    val ts: Long = System.currentTimeMillis(),
    val error: Boolean = false,
    val imageNames: List<String> = emptyList(),
)

/** 一个会话上下文 */
data class Conversation(
    val id: String,
    val title: String,
    val model: String,
    val messages: List<ChatMessage> = emptyList(),
    val createdAt: Long = System.currentTimeMillis(),
)

/** 界面状态 */
data class UiState(
    val conversations: List<Conversation> = emptyList(),
    val currentId: String = "",
    val models: List<OllamaModel> = emptyList(),
    /** 支持图片输入的模型（/api/show capabilities 含 vision） */
    val visionModels: Set<String> = emptySet(),
    /** /api/ps 里当前驻留显存的模型 */
    val loaded: List<String> = emptyList(),
    val streaming: Boolean = false,
    val busy: Boolean = false,
    val online: Boolean? = null,
    val status: String = "",
    val toast: String? = null,
    val serverUrl: String = "",
    val backupUrl: String = "",
    /** 实际连上的地址（可能是备用地址回退成功） */
    val activeUrl: String = "",
    val keepAlive: String = "5m",
    val systemPrompt: String = "",
    /** 待发送的图片（本地文件名） */
    val pendingImages: List<String> = emptyList(),
)
