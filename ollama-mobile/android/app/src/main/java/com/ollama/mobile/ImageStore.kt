package com.ollama.mobile

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.media.ExifInterface
import android.net.Uri
import android.util.Base64
import java.io.File
import java.io.FileOutputStream
import java.util.UUID

/**
 * 图片处理：相册 Uri → 纠正 EXIF 方向 → 缩到最长边 1280 → JPEG 存本地。
 * 发送时再读成 base64（Ollama 的 images 字段要求裸 base64，不带 data: 前缀）。
 */
object ImageStore {

    private const val MAX_EDGE = 1280
    private const val QUALITY = 85
    const val MAX_COUNT = 4

    private fun dir(ctx: Context): File =
        File(ctx.filesDir, "images").apply { if (!exists()) mkdirs() }

    fun file(ctx: Context, name: String): File = File(dir(ctx), name)

    /** 导入一张图，返回生成的文件名；失败返回 null */
    fun import(ctx: Context, uri: Uri): String? {
        var tmp: File? = null
        var bmp: Bitmap? = null
        return try {
            tmp = File.createTempFile("pick", ".img", ctx.cacheDir)
            ctx.contentResolver.openInputStream(uri)?.use { input ->
                FileOutputStream(tmp).use { out -> input.copyTo(out) }
            } ?: return null

            val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
            BitmapFactory.decodeFile(tmp.absolutePath, bounds)
            if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null

            var sample = 1
            while (bounds.outWidth / (sample * 2) >= MAX_EDGE && bounds.outHeight / (sample * 2) >= MAX_EDGE) {
                sample *= 2
            }

            val opts = BitmapFactory.Options().apply { inSampleSize = sample }
            bmp = BitmapFactory.decodeFile(tmp.absolutePath, opts) ?: return null
            bmp = rotateByExif(tmp.absolutePath, bmp)
            bmp = scaleDown(bmp)

            val name = UUID.randomUUID().toString() + ".jpg"
            FileOutputStream(file(ctx, name)).use { out ->
                bmp.compress(Bitmap.CompressFormat.JPEG, QUALITY, out)
            }
            name
        } catch (e: Exception) {
            null
        } finally {
            bmp?.recycle()
            tmp?.delete()
        }
    }

    private fun rotateByExif(path: String, src: Bitmap): Bitmap {
        val deg = try {
            when (ExifInterface(path).getAttributeInt(
                ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL
            )) {
                ExifInterface.ORIENTATION_ROTATE_90 -> 90f
                ExifInterface.ORIENTATION_ROTATE_180 -> 180f
                ExifInterface.ORIENTATION_ROTATE_270 -> 270f
                else -> 0f
            }
        } catch (e: Exception) {
            0f
        }
        if (deg == 0f) return src
        val m = Matrix().apply { postRotate(deg) }
        val out = Bitmap.createBitmap(src, 0, 0, src.width, src.height, m, true)
        if (out != src) src.recycle()
        return out
    }

    private fun scaleDown(src: Bitmap): Bitmap {
        val maxEdge = maxOf(src.width, src.height)
        if (maxEdge <= MAX_EDGE) return src
        val ratio = MAX_EDGE.toFloat() / maxEdge
        val out = Bitmap.createScaledBitmap(
            src,
            (src.width * ratio).toInt().coerceAtLeast(1),
            (src.height * ratio).toInt().coerceAtLeast(1),
            true,
        )
        if (out != src) src.recycle()
        return out
    }

    /** 发送给 Ollama 的裸 base64 */
    fun base64(ctx: Context, name: String): String? = try {
        val f = file(ctx, name)
        if (!f.exists()) null
        else Base64.encodeToString(f.readBytes(), Base64.NO_WRAP)
    } catch (e: Exception) {
        null
    }

    fun bitmap(ctx: Context, name: String): Bitmap? = try {
        val f = file(ctx, name)
        if (!f.exists()) null else BitmapFactory.decodeFile(f.absolutePath)
    } catch (e: Exception) {
        null
    }

    /** 删除已入库但没发出去的图，避免垃圾堆积 */
    fun delete(ctx: Context, name: String) {
        runCatching { file(ctx, name).delete() }
    }
}
