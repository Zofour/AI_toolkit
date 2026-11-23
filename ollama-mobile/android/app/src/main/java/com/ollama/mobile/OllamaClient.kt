package com.ollama.mobile

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

class OllamaException(message: String) : Exception(message)

/**
 * Ollama HTTP 客户端。
 *  - GET  /api/tags     模型列表
 *  - GET  /api/ps       当前驻留显存的模型
 *  - POST /api/generate {model, keep_alive:0}  → 立即把该模型从内存卸载
 *  - POST /api/chat     {stream:true} 流式对话
 */
class OllamaClient(base: String) {

    @Volatile
    var baseUrl: String = base.trim()

    private val jsonType = "application/json".toMediaType()

    private val client: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(8, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.SECONDS)     // 流式：不设读超时
        .writeTimeout(30, TimeUnit.SECONDS)
        .callTimeout(0, TimeUnit.SECONDS)
        .retryOnConnectionFailure(false)
        .build()

    private fun url(path: String) = baseUrl.trimEnd('/') + path

    /** 轻量探活，用于判断当前地址是否可用 */
    suspend fun probe(): String = withContext(Dispatchers.IO) {
        val req = Request.Builder().url(url("/api/version")).get().build()
        client.newCall(req).execute().use { r ->
            if (!r.isSuccessful) throw OllamaException("HTTP ${r.code}")
            JSONObject(r.body?.string().orEmpty()).optString("version")
        }
    }

    /** /api/show 的 capabilities，例如 completion / vision / thinking / tools */
    suspend fun capabilities(model: String): Set<String> = withContext(Dispatchers.IO) {
        val payload = JSONObject().put("model", model).toString()
        val req = Request.Builder()
            .url(url("/api/show"))
            .post(payload.toRequestBody(jsonType))
            .build()
        client.newCall(req).execute().use { r ->
            if (!r.isSuccessful) return@withContext emptySet()
            val arr = JSONObject(r.body?.string().orEmpty()).optJSONArray("capabilities") ?: JSONArray()
            (0 until arr.length()).map { arr.optString(it) }.toSet()
        }
    }

    suspend fun listModels(): List<OllamaModel> = withContext(Dispatchers.IO) {
        val req = Request.Builder().url(url("/api/tags")).get().build()
        client.newCall(req).execute().use { r ->
            val body = r.body?.string().orEmpty()
            if (!r.isSuccessful) throw OllamaException("HTTP ${r.code}: ${body.take(200)}")
            val arr = JSONObject(body).optJSONArray("models") ?: JSONArray()
            (0 until arr.length()).map { i ->
                val o = arr.getJSONObject(i)
                val d = o.optJSONObject("details")
                OllamaModel(
                    name = o.optString("name").ifBlank { o.optString("model") },
                    sizeBytes = o.optLong("size"),
                    paramSize = d?.optString("parameter_size").orEmpty(),
                    family = d?.optString("family").orEmpty(),
                )
            }.sortedBy { it.name.lowercase() }
        }
    }

    /** 当前在显存里的模型名 */
    suspend fun running(): List<String> = withContext(Dispatchers.IO) {
        val req = Request.Builder().url(url("/api/ps")).get().build()
        client.newCall(req).execute().use { r ->
            val body = r.body?.string().orEmpty()
            if (!r.isSuccessful) throw OllamaException("HTTP ${r.code}: ${body.take(200)}")
            val arr = JSONObject(body).optJSONArray("models") ?: JSONArray()
            (0 until arr.length()).mapNotNull { i ->
                val o = arr.optJSONObject(i) ?: return@mapNotNull null
                o.optString("name").ifBlank { o.optString("model") }
            }
        }
    }

    /** keep_alive = 0 → Ollama 立即卸载该模型，释放显存 */
    suspend fun unload(model: String) = withContext(Dispatchers.IO) {
        if (model.isBlank()) return@withContext
        val payload = JSONObject()
            .put("model", model)
            .put("keep_alive", 0)
            .toString()
        val req = Request.Builder()
            .url(url("/api/generate"))
            .post(payload.toRequestBody(jsonType))
            .build()
        client.newCall(req).execute().use { r ->
            r.body?.string()   // 结果无需解析
        }
        Unit
    }

    data class Delta(val content: String, val thinking: String)

    /** 流式对话，取消 collect 即中断 HTTP 请求。lastImages 只随最后一条 user 消息上传 */
    fun chatFlow(
        model: String,
        history: List<ChatMessage>,
        keepAlive: String,
        lastImages: List<String> = emptyList(),
    ): Flow<Delta> = flow {
        val arr = JSONArray()
        val lastIndex = history.lastIndex
        history.forEachIndexed { i, m ->
            val isLastUser = i == lastIndex && m.role == "user" && lastImages.isNotEmpty()
            if (m.role == "system" || m.content.isNotBlank() || isLastUser) {
                val o = JSONObject().put("role", m.role).put("content", m.content)
                if (isLastUser) {
                    val ia = JSONArray()
                    lastImages.forEach { ia.put(it) }
                    o.put("images", ia)
                }
                arr.put(o)
            }
        }
        val payload = JSONObject()
            .put("model", model)
            .put("messages", arr)
            .put("stream", true)
            .put("keep_alive", keepAlive)

        val req = Request.Builder()
            .url(url("/api/chat"))
            .post(payload.toString().toRequestBody(jsonType))
            .build()

        val call = client.newCall(req)
        try {
            call.execute().use { r ->
                if (!r.isSuccessful) {
                    throw OllamaException("HTTP ${r.code}: " + (r.body?.string()?.take(300) ?: ""))
                }
                val src = r.body!!.source()
                while (true) {
                    val line = src.readUtf8Line() ?: break
                    if (line.isBlank()) continue
                    val o = try {
                        JSONObject(line)
                    } catch (e: Exception) {
                        continue
                    }
                    if (o.has("error")) throw OllamaException(o.optString("error"))
                    val msg = o.optJSONObject("message")
                    val c = msg?.optString("content").orEmpty()
                    val th = msg?.optString("thinking").orEmpty()
                    if (c.isNotEmpty() || th.isNotEmpty()) emit(Delta(c, th))
                    if (o.optBoolean("done", false)) break
                }
            }
        } finally {
            call.cancel()
        }
    }.flowOn(Dispatchers.IO)
}
