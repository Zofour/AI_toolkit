package com.ollama.mobile

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/** 会话本地持久化（app 私有目录，卸载前一直保留） */
class Store(ctx: Context) {

    private val file = File(ctx.filesDir, "conversations.json")

    fun load(): List<Conversation> = try {
        if (!file.exists()) {
            emptyList()
        } else {
            val text = file.readText()
            if (text.isBlank()) emptyList() else {
                val arr = JSONArray(text)
                (0 until arr.length()).mapNotNull { i ->
                    val o = arr.optJSONObject(i) ?: return@mapNotNull null
                    val msgs = ArrayList<ChatMessage>()
                    val ma = o.optJSONArray("messages") ?: JSONArray()
                    for (j in 0 until ma.length()) {
                        val m = ma.optJSONObject(j) ?: continue
                        val imgs = ArrayList<String>()
                        val ia = m.optJSONArray("images")
                        if (ia != null) {
                            for (k in 0 until ia.length()) {
                                val n = ia.optString(k, "")
                                if (n.isNotBlank()) imgs.add(n)
                            }
                        }
                        msgs.add(
                            ChatMessage(
                                role = m.optString("role", "user"),
                                content = m.optString("content", ""),
                                thinking = m.optString("thinking", ""),
                                ts = m.optLong("ts", System.currentTimeMillis()),
                                error = m.optBoolean("error", false),
                                imageNames = imgs,
                            )
                        )
                    }
                    val id = o.optString("id", "")
                    if (id.isBlank()) null else Conversation(
                        id = id,
                        title = o.optString("title", "新对话"),
                        model = o.optString("model", ""),
                        messages = msgs,
                        createdAt = o.optLong("createdAt", System.currentTimeMillis()),
                    )
                }
            }
        }
    } catch (e: Exception) {
        emptyList()
    }

    fun save(list: List<Conversation>) {
        try {
            val arr = JSONArray()
            list.forEach { c ->
                val ma = JSONArray()
                c.messages.forEach { m ->
                    val ia = JSONArray()
                    m.imageNames.forEach { ia.put(it) }
                    ma.put(
                        JSONObject()
                            .put("role", m.role)
                            .put("content", m.content)
                            .put("thinking", m.thinking)
                            .put("ts", m.ts)
                            .put("error", m.error)
                            .put("images", ia)
                    )
                }
                arr.put(
                    JSONObject()
                        .put("id", c.id)
                        .put("title", c.title)
                        .put("model", c.model)
                        .put("createdAt", c.createdAt)
                        .put("messages", ma)
                )
            }
            file.writeText(arr.toString())
        } catch (_: Exception) {
        }
    }
}
