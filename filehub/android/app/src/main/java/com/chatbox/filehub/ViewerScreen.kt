package com.chatbox.filehub

import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.content.pm.ActivityInfo
import android.net.Uri
import android.util.Log
import android.view.LayoutInflater
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.calculatePan
import androidx.compose.foundation.gestures.calculateZoom
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.ScreenRotation
import androidx.compose.material.icons.filled.StayCurrentPortrait
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.ui.PlayerView
import coil.compose.AsyncImage
import coil.compose.AsyncImagePainter
import coil.request.ImageRequest
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/** 全屏查看：图片左右滑动 + 双指缩放，视频点击播放。全部只读。 */
@Composable
fun ViewerScreen(
    api: Api,
    items: List<MediaEntry>,
    startIndex: Int,
    folderName: String,
    onClose: () -> Unit,
) {
    if (items.isEmpty()) {
        onClose()
        return
    }
    val pager = rememberPagerState(
        initialPage = startIndex.coerceIn(0, items.lastIndex),
        pageCount = { items.size },
    )
    var chrome by remember { mutableStateOf(true) }
    var pagerEnabled by remember { mutableStateOf(true) }

    // 横屏切换：按钮只在查看页生效，退出查看页自动恢复“跟随系统”
    val activity = LocalContext.current.findActivity()
    var landscape by remember { mutableStateOf(false) }
    DisposableEffect(Unit) {
        onDispose { activity?.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED }
    }

    LaunchedEffect(pager.currentPage) { pagerEnabled = true }
    ImmersiveMode()

    Box(
        Modifier
            .fillMaxSize()
            .background(Color.Black),
    ) {
        HorizontalPager(
            state = pager,
            userScrollEnabled = pagerEnabled,
            beyondViewportPageCount = 0,
            modifier = Modifier.fillMaxSize(),
        ) { page ->
            val e = items[page]
            when {
                e.isVideo -> VideoStage(api, e, active = page == pager.currentPage)
                else -> PhotoPage(
                    api = api,
                    entry = e,
                    onTap = { chrome = !chrome },
                    onZoomChange = { zoomed ->
                        if (page == pager.currentPage) pagerEnabled = !zoomed
                    },
                )
            }
        }

        val cur = items[pager.currentPage.coerceIn(0, items.lastIndex)]

        // 顶部信息条
        AnimatedVisibility(
            visible = chrome,
            enter = fadeIn(),
            exit = fadeOut(),
            modifier = Modifier.align(Alignment.TopCenter),
        ) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .background(
                        Brush.verticalGradient(
                            listOf(Color(0xCC000000), Color(0x00000000)),
                        )
                    )
                    .statusBarsPadding()
                    .padding(horizontal = 4.dp, vertical = 2.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                IconButton(onClick = onClose) {
                    Icon(Icons.Filled.Close, contentDescription = "关闭", tint = Color.White)
                }
                Column(Modifier.weight(1f)) {
                    Text(
                        cur.name,
                        color = Color.White,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        fontSize = 13.sp,
                    )
                    Text(
                        listOf(folderName, humanSize(cur.size), humanDate(cur.mtime))
                            .filter { it.isNotBlank() }
                            .joinToString("  ·  "),
                        color = Color.White.copy(alpha = 0.62f),
                        maxLines = 1,
                        fontSize = 10.sp,
                    )
                }
                IconButton(onClick = {
                    val on = !landscape
                    landscape = on
                    activity?.requestedOrientation = if (on)
                        ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE   // 左右两个横屏方向都允许
                    else
                        ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED
                }) {
                    Icon(
                        if (landscape) Icons.Filled.StayCurrentPortrait
                        else Icons.Filled.ScreenRotation,
                        contentDescription = if (landscape) "切回竖屏" else "横屏查看",
                        tint = Color.White.copy(alpha = 0.9f),
                    )
                }
                Text(
                    "${pager.currentPage + 1} / ${items.size}",
                    color = Color.White.copy(alpha = 0.85f),
                    fontSize = 12.sp,
                    modifier = Modifier.padding(end = 12.dp),
                )
            }
        }

        // 底部页码
        AnimatedVisibility(
            visible = chrome && items.size > 1,
            enter = fadeIn(),
            exit = fadeOut(),
            modifier = Modifier.align(Alignment.BottomCenter),
        ) {
            Text(
                if (cur.isVideo) "视频 · 左右滑动切换" else "双指缩放 · 双击放大",
                color = Color.White.copy(alpha = 0.55f),
                fontSize = 11.sp,
                modifier = Modifier
                    .padding(bottom = 18.dp)
                    .background(Color(0x66000000), RoundedCornerShape(20.dp))
                    .padding(horizontal = 12.dp, vertical = 5.dp),
            )
        }
    }
}

// ------------------------------------------------------------------ 图片

/**
 * 一张照片：大于 6 MB 的原图先用电脑端生成的 2200px 预览秒开，
 * 需要细节时再点“原图”拉全尺寸。这样 50 MB 的 PNG 也不用干等。
 */
@Composable
private fun PhotoPage(
    api: Api,
    entry: MediaEntry,
    onTap: () -> Unit,
    onZoomChange: (Boolean) -> Unit,
) {
    var wantOriginal by remember(entry.path) { mutableStateOf(false) }
    val isBig = entry.size > 6L * 1024 * 1024
    val usePreview = isBig && !wantOriginal
    val url = if (usePreview) api.thumbUrl(entry.path, 2200) else api.fileUrl(entry.path)

    Box(Modifier.fillMaxSize()) {
        ZoomableImage(
            url = url,
            onTap = onTap,
            onZoomChange = onZoomChange,
            modifier = Modifier.fillMaxSize(),
        )
        if (usePreview) {
            TextButton(
                onClick = { wantOriginal = true },
                modifier = Modifier
                    .align(Alignment.BottomEnd)
                    .padding(end = 14.dp, bottom = 46.dp)
                    .background(Color(0x66000000), RoundedCornerShape(20.dp)),
            ) {
                Text("原图", color = Color.White.copy(alpha = 0.9f), fontSize = 12.sp)
            }
        }
    }
}

private fun clampOffset(o: Offset, scale: Float, size: IntSize): Offset {
    if (size.width == 0 || size.height == 0) return o
    val maxX = ((scale - 1f) * size.width) / 2f
    val maxY = ((scale - 1f) * size.height) / 2f
    return Offset(o.x.coerceIn(-maxX, maxX), o.y.coerceIn(-maxY, maxY))
}

@Composable
private fun ZoomableImage(
    url: String,
    onTap: () -> Unit,
    onZoomChange: (Boolean) -> Unit,
    modifier: Modifier = Modifier,
) {
    var scale by remember(url) { mutableFloatStateOf(1f) }
    var offset by remember(url) { mutableStateOf(Offset.Zero) }
    var boxSize by remember { mutableStateOf(IntSize.Zero) }
    var tapJob by remember { mutableStateOf<Job?>(null) }
    var state by remember(url) { mutableStateOf<AsyncImagePainter.State>(AsyncImagePainter.State.Empty) }
    val scope = rememberCoroutineScope()
    val ctx = LocalContext.current

    LaunchedEffect(scale) { onZoomChange(scale > 1.01f) }

    Box(modifier = modifier.clipToBounds()) {
        AsyncImage(
            model = ImageRequest.Builder(ctx)
                .data(url)
                .crossfade(180)
                .build(),
            onState = { state = it },
            contentDescription = null,
            contentScale = ContentScale.Fit,
            modifier = Modifier
                .fillMaxSize()
                .onSizeChanged { boxSize = it }
                .graphicsLayer {
                    scaleX = scale
                    scaleY = scale
                    translationX = offset.x
                    translationY = offset.y
                }
                .pointerInput(url) {
                    var lastTap = 0L
                    awaitEachGesture {
                        val down = awaitFirstDown(requireUnconsumed = false)
                        val downPos = down.position
                        var maxDist = 0f
                        var consumed = false
                        while (true) {
                            val ev = awaitPointerEvent()
                            val pressed = ev.changes.filter { it.pressed }
                            if (pressed.isEmpty()) break
                            val zoom = ev.calculateZoom()
                            val pan = ev.calculatePan()
                            for (c in pressed) {
                                val d = (c.position - downPos).getDistance()
                                if (d > maxDist) maxDist = d
                            }
                            if (pressed.size >= 2 && (zoom != 1f || pan != Offset.Zero)) {
                                // 双指缩放
                                val ns = (scale * zoom).coerceIn(1f, 6f)
                                scale = ns
                                offset = if (ns <= 1.01f) Offset.Zero
                                else clampOffset(offset + pan, ns, boxSize)
                                ev.changes.forEach { it.consume() }
                                consumed = true
                            } else if (scale > 1.01f && pan != Offset.Zero) {
                                // 放大后单指拖动
                                offset = clampOffset(offset + pan, scale, boxSize)
                                ev.changes.forEach { it.consume() }
                                consumed = true
                            }
                        }
                        if (!consumed && maxDist < 26f) {
                            val now = System.currentTimeMillis()
                            if (now - lastTap < 320L) {
                                tapJob?.cancel()
                                lastTap = 0L
                                if (scale > 1.01f) {
                                    scale = 1f
                                    offset = Offset.Zero
                                } else {
                                    scale = 2.5f
                                    offset = Offset.Zero
                                }
                            } else {
                                lastTap = now
                                tapJob?.cancel()
                                tapJob = scope.launch {
                                    delay(300)
                                    onTap()
                                }
                            }
                        }
                    }
                },
        )

        when (state) {
            is AsyncImagePainter.State.Loading, AsyncImagePainter.State.Empty -> {
                Column(
                    modifier = Modifier.align(Alignment.Center),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(28.dp),
                        strokeWidth = 2.dp,
                        color = Color.White.copy(alpha = 0.8f),
                    )
                }
            }

            is AsyncImagePainter.State.Error -> {
                Text(
                    "加载失败",
                    color = Color.White.copy(alpha = 0.7f),
                    fontSize = 12.sp,
                    modifier = Modifier.align(Alignment.Center),
                )
            }

            else -> Unit
        }
    }
}

// ------------------------------------------------------------------ 视频

@Composable
private fun VideoStage(api: Api, entry: MediaEntry, active: Boolean) {
    var started by remember(entry.path) { mutableStateOf(false) }
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        if (started && active) {
            ExoVideo(url = api.fileUrl(entry.path), modifier = Modifier.fillMaxSize())
        } else {
            AsyncImage(
                model = ImageRequest.Builder(LocalContext.current)
                    .data(api.thumbUrl(entry.path, 720))
                    .crossfade(true)
                    .build(),
                contentDescription = entry.name,
                contentScale = ContentScale.Fit,
                modifier = Modifier.fillMaxSize(),
            )
            Box(
                modifier = Modifier
                    .size(68.dp)
                    .clip(RoundedCornerShape(50))
                    .background(Color(0xAA000000))
                    .clickable { started = true },
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    Icons.Filled.PlayArrow,
                    contentDescription = "播放",
                    tint = Color.White,
                    modifier = Modifier.size(42.dp),
                )
            }
        }
    }
}

@Composable
private fun ExoVideo(url: String, modifier: Modifier = Modifier) {
    val ctx = LocalContext.current
    val lifecycle = LocalLifecycleOwner.current.lifecycle

    val player = remember(url) {
        ExoPlayer.Builder(ctx).build().apply {
            addListener(object : Player.Listener {
                override fun onPlaybackStateChanged(playbackState: Int) {
                    Log.d("FileHub", "state=$playbackState")
                }

                override fun onRenderedFirstFrame() {
                    Log.d("FileHub", "first frame rendered")
                }

                override fun onPlayerError(error: PlaybackException) {
                    Log.e("FileHub", "player error: ${error.errorCodeName} / ${error.message}")
                }
            })
            setMediaItem(MediaItem.fromUri(Uri.parse(url)))
            prepare()
            playWhenReady = true
        }
    }

    DisposableEffect(player) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_STOP) player.pause()
        }
        lifecycle.addObserver(observer)
        onDispose {
            lifecycle.removeObserver(observer)
            player.release()
        }
    }

    AndroidView(
        factory = { c ->
            (LayoutInflater.from(c).inflate(R.layout.view_player, null) as PlayerView).apply {
                this.player = player
                setShowNextButton(false)
                setShowPreviousButton(false)
            }
        },
        modifier = modifier,
    )
}

// ------------------------------------------------------------------ 沉浸式

@Composable
private fun ImmersiveMode() {
    val view = LocalView.current
    val orientation = LocalConfiguration.current.orientation   // 旋转后重新进入沉浸
    DisposableEffect(orientation) {
        val window = view.context.findActivity()?.window
        if (window == null) {
            onDispose { }
        } else {
            val controller = WindowCompat.getInsetsController(window, view)
            controller.systemBarsBehavior =
                WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            controller.hide(WindowInsetsCompat.Type.systemBars())
            onDispose { controller.show(WindowInsetsCompat.Type.systemBars()) }
        }
    }
}

private fun Context.findActivity(): Activity? {
    var c: Context = this
    while (c is ContextWrapper) {
        if (c is Activity) return c
        c = c.baseContext
    }
    return null
}
