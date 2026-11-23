package com.ollama.mobile

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.AddPhotoAlternate
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.List
import androidx.compose.material.icons.filled.Memory
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Send
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.rememberDrawerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch
import java.util.Locale

// ---------------- 配色 ----------------
private val Bg = Color(0xFF0B1020)
private val Panel = Color(0xFF121A28)
private val PanelHi = Color(0xFF1C2740)
private val BubbleAI = Color(0xFF151D2C)
private val BubbleUser = Color(0xFF1D3F8F)
private val Accent = Color(0xFF6EE7FF)
private val Dim = Color(0xFF8A98AD)
private val Danger = Color(0xFFFF8A8A)
private val Ok = Color(0xFF7EE787)

fun appColorScheme() = darkColorScheme(
    primary = Accent,
    onPrimary = Color(0xFF04121A),
    secondary = Color(0xFF9DB2FF),
    background = Bg,
    onBackground = Color(0xFFE8EEF7),
    surface = Bg,
    onSurface = Color(0xFFE8EEF7),
    surfaceVariant = Panel,
    onSurfaceVariant = Dim,
    error = Danger,
)

private fun fmtSize(bytes: Long): String = when {
    bytes <= 0L -> ""
    bytes >= 1024L * 1024 * 1024 -> String.format(Locale.US, "%.1f GB", bytes / 1024.0 / 1024 / 1024)
    else -> String.format(Locale.US, "%.0f MB", bytes / 1024.0 / 1024)
}

// ---------------- 根 ----------------
@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun App(vm: AppViewModel) {
    val st by vm.state.collectAsState()
    val snackbar = remember { SnackbarHostState() }
    val drawer = rememberDrawerState(DrawerValue.Closed)
    val scope = rememberCoroutineScope()
    val clipboard = LocalClipboardManager.current

    var showModels by remember { mutableStateOf(false) }
    var showSettings by remember { mutableStateOf(false) }
    var input by remember { mutableStateOf("") }

    val picker = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri ->
        if (uri != null) vm.addPendingImage(uri)
    }

    val conv = st.conversations.firstOrNull { it.id == st.currentId }

    LaunchedEffect(st.toast) {
        st.toast?.let {
            snackbar.showSnackbar(it)
            vm.consumeToast()
        }
    }

    MaterialTheme(colorScheme = appColorScheme()) {
        ModalNavigationDrawer(
            drawerState = drawer,
            drawerContent = {
                DrawerBody(
                    st = st,
                    onNew = {
                        vm.newChat()
                        scope.launch { drawer.close() }
                    },
                    onPick = {
                        vm.selectConversation(it)
                        scope.launch { drawer.close() }
                    },
                    onDelete = { vm.deleteConversation(it) },
                    onSettings = {
                        showSettings = true
                        scope.launch { drawer.close() }
                    },
                    onUnload = { vm.unloadAll() },
                    onRefresh = { vm.refresh() },
                )
            },
        ) {
            Scaffold(
                containerColor = Bg,
                snackbarHost = { SnackbarHost(snackbar) },
                topBar = {
                    TopAppBar(
                        colors = TopAppBarDefaults.topAppBarColors(
                            containerColor = Panel,
                            titleContentColor = Color(0xFFE8EEF7),
                        ),
                        navigationIcon = {
                            IconButton(onClick = { scope.launch { drawer.open() } }) {
                                Icon(Icons.Filled.Menu, contentDescription = "对话列表", tint = Accent)
                            }
                        },
                        title = {
                            Column(Modifier.clickable { showModels = true }) {
                                Text(
                                    conv?.title ?: "Ollama 口袋",
                                    fontSize = 15.sp,
                                    fontWeight = FontWeight.SemiBold,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis,
                                )
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Text(
                                        conv?.model?.ifBlank { "未选择模型" } ?: "未连接",
                                        fontSize = 11.sp,
                                        color = Accent,
                                        maxLines = 1,
                                        overflow = TextOverflow.Ellipsis,
                                    )
                                    Icon(
                                        Icons.Filled.ArrowDropDown,
                                        contentDescription = null,
                                        tint = Accent,
                                        modifier = Modifier.size(16.dp),
                                    )
                                }
                            }
                        },
                        actions = {
                            IconButton(onClick = { vm.newChat() }) {
                                Icon(Icons.Filled.Add, contentDescription = "新建对话", tint = Color(0xFFE8EEF7))
                            }
                            Box {
                                IconButton(onClick = { showModels = true }) {
                                    Icon(Icons.Filled.Memory, contentDescription = "选择模型", tint = Accent)
                                }
                                DropdownMenu(
                                    expanded = showModels,
                                    onDismissRequest = { showModels = false },
                                    modifier = Modifier.heightIn(max = 460.dp),
                                ) {
                                    if (st.models.isEmpty()) {
                                        DropdownMenuItem(
                                            text = { Text("没有取到模型，点下面刷新", fontSize = 13.sp) },
                                            onClick = { showModels = false },
                                        )
                                    }
                                    st.models.forEach { m ->
                                        val selected = m.name == conv?.model
                                        val running = st.loaded.contains(m.name)
                                        DropdownMenuItem(
                                            text = {
                                                Column {
                                                    Text(
                                                        m.name,
                                                        fontSize = 14.sp,
                                                        fontWeight = if (selected) FontWeight.Bold else FontWeight.Normal,
                                                        color = if (selected) Accent else Color(0xFFE8EEF7),
                                                    )
                                                    Text(
                                                        listOfNotNull(
                                                            m.paramSize.ifBlank { null },
                                                            fmtSize(m.sizeBytes).ifBlank { null },
                                                            if (st.visionModels.contains(m.name)) "视觉" else null,
                                                            if (running) "已驻留显存" else null,
                                                        ).joinToString(" · "),
                                                        fontSize = 11.sp,
                                                        color = if (running) Ok else Dim,
                                                    )
                                                }
                                            },
                                            leadingIcon = {
                                                if (selected) {
                                                    Icon(Icons.Filled.Check, null, tint = Accent, modifier = Modifier.size(18.dp))
                                                } else {
                                                    Spacer(Modifier.width(18.dp))
                                                }
                                            },
                                            onClick = {
                                                showModels = false
                                                vm.selectModel(m.name)
                                            },
                                        )
                                    }
                                    HorizontalDivider()
                                    DropdownMenuItem(
                                        text = { Text("刷新模型列表", fontSize = 13.sp) },
                                        leadingIcon = { Icon(Icons.Filled.Refresh, null, modifier = Modifier.size(18.dp)) },
                                        onClick = {
                                            showModels = false
                                            vm.refresh()
                                        },
                                    )
                                }
                            }
                        },
                    )
                },
                bottomBar = {
                    InputBar(
                        value = input,
                        onValueChange = { input = it },
                        streaming = st.streaming,
                        busy = st.busy,
                        status = st.status,
                        online = st.online,
                        server = st.activeUrl.ifBlank { st.serverUrl },
                        pendingImages = st.pendingImages,
                        onAttach = {
                            picker.launch(
                                PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)
                            )
                        },
                        onRemoveImage = { vm.removePendingImage(it) },
                        onSend = {
                            val t = input
                            input = ""
                            vm.send(t)
                        },
                        onStop = { vm.stop() },
                    )
                },
            ) { padding ->
                Box(Modifier.fillMaxSize().padding(padding)) {
                    if (conv == null || conv.messages.isEmpty()) {
                        EmptyHint(conv?.model.orEmpty(), st.online, st.status)
                    } else {
                        MessageList(conv, st.streaming, onCopy = { s ->
                            clipboard.setText(AnnotatedString(s))
                            scope.launch { snackbar.showSnackbar("已复制") }
                        })
                    }
                }
            }
        }

        if (showSettings) {
            SettingsDialog(
                st = st,
                onDismiss = { showSettings = false },
                onSave = { u, b, k, p ->
                    vm.saveSettings(u, b, k, p)
                    showSettings = false
                },
                onTest = { u, b, k, p -> vm.saveSettings(u, b, k, p) },
                onUnload = { vm.unloadAll() },
            )
        }
    }
}

// ---------------- 消息列表 ----------------
@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun MessageList(conv: Conversation, streaming: Boolean, onCopy: (String) -> Unit) {
    val listState = rememberLazyListState()
    val lastLen = conv.messages.lastOrNull()?.content?.length ?: 0
    LaunchedEffect(conv.messages.size, lastLen / 300) {
        if (conv.messages.isNotEmpty()) {
            listState.scrollToItem(conv.messages.lastIndex)
        }
    }
    SelectionContainer {
        LazyColumn(
            state = listState,
            modifier = Modifier.fillMaxSize(),
            contentPadding = androidx.compose.foundation.layout.PaddingValues(vertical = 10.dp),
        ) {
            itemsIndexed(conv.messages) { i, m ->
                val isLast = i == conv.messages.lastIndex
                ChatBubble(
                    m = m,
                    streaming = streaming && isLast && m.role == "assistant",
                    onCopy = onCopy,
                )
            }
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun ChatBubble(m: ChatMessage, streaming: Boolean, onCopy: (String) -> Unit) {
    val isUser = m.role == "user"
    var showThinking by remember(m.ts) { mutableStateOf(false) }

    Row(
        Modifier.fillMaxWidth().padding(horizontal = 10.dp, vertical = 4.dp),
        horizontalArrangement = if (isUser) Arrangement.End else Arrangement.Start,
    ) {
        Surface(
            color = if (isUser) BubbleUser else BubbleAI,
            shape = RoundedCornerShape(
                topStart = 16.dp,
                topEnd = 16.dp,
                bottomStart = if (isUser) 16.dp else 4.dp,
                bottomEnd = if (isUser) 4.dp else 16.dp,
            ),
            modifier = Modifier
                .widthIn(max = 330.dp)
                .combinedClickable(
                    onClick = {},
                    onLongClick = { if (m.content.isNotBlank()) onCopy(m.content) },
                ),
        ) {
            Column(Modifier.padding(horizontal = 12.dp, vertical = 9.dp)) {
                if (m.imageNames.isNotEmpty()) {
                    val ctx = LocalContext.current
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        m.imageNames.forEach { name ->
                            val bmp = remember(name) { ImageStore.bitmap(ctx, name) }
                            if (bmp != null) {
                                val ratio = bmp.width.toFloat() / bmp.height.coerceAtLeast(1)
                                val sizeMod = if (ratio >= 1f) {
                                    Modifier.width(210.dp)
                                } else {
                                    Modifier.height(210.dp)
                                }
                                Image(
                                    bitmap = bmp.asImageBitmap(),
                                    contentDescription = null,
                                    contentScale = ContentScale.Fit,
                                    modifier = sizeMod.clip(RoundedCornerShape(10.dp)),
                                )
                            }
                        }
                    }
                    Spacer(Modifier.height(6.dp))
                }
                if (m.thinking.isNotBlank()) {
                    Text(
                        if (showThinking) "思考过程 ▾" else "思考过程 ▸（${m.thinking.length} 字）",
                        fontSize = 11.sp,
                        color = Dim,
                        modifier = Modifier.clickable { showThinking = !showThinking },
                    )
                    if (showThinking) {
                        Text(
                            m.thinking,
                            fontSize = 12.sp,
                            color = Dim,
                            modifier = Modifier.padding(top = 4.dp, bottom = 6.dp),
                        )
                        HorizontalDivider(color = Color(0xFF243149))
                        Spacer(Modifier.height(6.dp))
                    } else {
                        Spacer(Modifier.height(2.dp))
                    }
                }

                if (m.content.isBlank() && streaming) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(13.dp),
                            strokeWidth = 2.dp,
                            color = Accent,
                        )
                        Spacer(Modifier.width(8.dp))
                        Text("正在生成…", fontSize = 13.sp, color = Dim)
                    }
                } else {
                    MarkdownText(if (streaming) m.content + " ▌" else m.content, isUser, m.error)
                }
            }
        }
    }
}

/** 极简渲染：正文 + ``` 代码块 */
@Composable
private fun MarkdownText(text: String, isUser: Boolean, isError: Boolean) {
    val parts = remember(text) { text.split("```") }
    Column {
        parts.forEachIndexed { i, seg ->
            if (i % 2 == 1) {
                val body = seg.substringAfter('\n', "").ifBlank { seg }
                Surface(
                    color = Color(0xFF070C16),
                    shape = RoundedCornerShape(8.dp),
                    modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
                ) {
                    Text(
                        body.trimEnd(),
                        fontFamily = FontFamily.Monospace,
                        fontSize = 12.5.sp,
                        color = Color(0xFF9FE8FF),
                        modifier = Modifier.padding(9.dp),
                    )
                }
            } else if (seg.isNotBlank()) {
                Text(
                    seg.trim(),
                    fontSize = 14.5.sp,
                    lineHeight = 21.sp,
                    color = if (isError) Danger else if (isUser) Color(0xFFF2F6FF) else Color(0xFFE8EEF7),
                )
            }
        }
    }
}

// ---------------- 输入栏 ----------------
@Composable
private fun InputBar(
    value: String,
    onValueChange: (String) -> Unit,
    streaming: Boolean,
    busy: Boolean,
    status: String,
    online: Boolean?,
    server: String,
    pendingImages: List<String>,
    onAttach: () -> Unit,
    onRemoveImage: (String) -> Unit,
    onSend: () -> Unit,
    onStop: () -> Unit,
) {
    val ctx = LocalContext.current
    val canSend = streaming || ((value.isNotBlank() || pendingImages.isNotEmpty()) && !busy)
    Surface(color = Panel) {
        Column(Modifier.fillMaxWidth().navigationBarsPadding().imePadding()) {
            if (status.isNotBlank()) {
                Row(Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                    CircularProgressIndicator(Modifier.size(11.dp), strokeWidth = 2.dp, color = Accent)
                    Spacer(Modifier.width(8.dp))
                    Text(status, fontSize = 11.sp, color = Accent, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            } else if (online == false) {
                Text(
                    "⚠ 连不上 $server —— 确认电脑端 Ollama 在运行、Tailscale 已连通",
                    fontSize = 11.sp,
                    color = Danger,
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 4.dp),
                )
            }
            if (pendingImages.isNotEmpty()) {
                Row(
                    Modifier.fillMaxWidth().padding(start = 12.dp, top = 8.dp, end = 12.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    pendingImages.forEach { name ->
                        Box {
                            val bmp = remember(name) { ImageStore.bitmap(ctx, name) }
                            if (bmp != null) {
                                Image(
                                    bitmap = bmp.asImageBitmap(),
                                    contentDescription = null,
                                    contentScale = ContentScale.Crop,
                                    modifier = Modifier.size(58.dp).clip(RoundedCornerShape(10.dp)),
                                )
                            } else {
                                Box(
                                    Modifier.size(58.dp)
                                        .clip(RoundedCornerShape(10.dp))
                                        .background(PanelHi)
                                )
                            }
                            Box(
                                Modifier
                                    .align(Alignment.TopEnd)
                                    .size(18.dp)
                                    .background(Color(0xFF0B1020), CircleShape)
                                    .clickable { onRemoveImage(name) },
                                contentAlignment = Alignment.Center,
                            ) {
                                Icon(
                                    Icons.Filled.Close,
                                    contentDescription = "移除",
                                    tint = Color.White,
                                    modifier = Modifier.size(12.dp),
                                )
                            }
                        }
                    }
                }
            }
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 8.dp),
                verticalAlignment = Alignment.Bottom,
            ) {
                IconButton(
                    onClick = onAttach,
                    enabled = !streaming,
                    modifier = Modifier.size(44.dp),
                ) {
                    Icon(
                        Icons.Filled.AddPhotoAlternate,
                        contentDescription = "添加图片",
                        tint = if (streaming) Dim else Accent,
                        modifier = Modifier.size(23.dp),
                    )
                }
                OutlinedTextField(
                    value = value,
                    onValueChange = onValueChange,
                    modifier = Modifier.weight(1f),
                    placeholder = { Text("说点什么…", fontSize = 14.sp, color = Dim) },
                    maxLines = 5,
                    shape = RoundedCornerShape(22.dp),
                )
                Spacer(Modifier.width(6.dp))
                IconButton(
                    onClick = { if (streaming) onStop() else if (canSend) onSend() },
                    modifier = Modifier
                        .size(46.dp)
                        .background(if (streaming) Danger else Accent, CircleShape),
                    enabled = canSend,
                ) {
                    Icon(
                        if (streaming) Icons.Filled.Close else Icons.Filled.Send,
                        contentDescription = if (streaming) "停止" else "发送",
                        tint = Color(0xFF04121A),
                        modifier = Modifier.size(20.dp),
                    )
                }
            }
        }
    }
}

@Composable
private fun EmptyHint(model: String, online: Boolean?, status: String) {
    Column(
        Modifier.fillMaxSize().padding(32.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text("Ollama 口袋", fontSize = 22.sp, fontWeight = FontWeight.Bold, color = Accent)
        Spacer(Modifier.height(10.dp))
        Text(
            if (model.isBlank()) "先在右上角选择模型" else "当前模型：$model",
            fontSize = 13.sp,
            color = Dim,
        )
        Spacer(Modifier.height(20.dp))
        Text(
            "· 顶栏点名称可切换模型，切换时上一个模型会被自动卸载\n" +
                "· 左上角抽屉里管理多个对话\n" +
                "· 长按消息可复制内容",
            fontSize = 12.sp,
            color = Dim,
            lineHeight = 20.sp,
        )
        if (status.isNotBlank()) {
            Spacer(Modifier.height(18.dp))
            Text(status, fontSize = 12.sp, color = Accent)
        }
    }
}

// ---------------- 抽屉 ----------------
@Composable
private fun DrawerBody(
    st: UiState,
    onNew: () -> Unit,
    onPick: (String) -> Unit,
    onDelete: (String) -> Unit,
    onSettings: () -> Unit,
    onUnload: () -> Unit,
    onRefresh: () -> Unit,
) {
    ModalDrawerSheet(
        modifier = Modifier.width(300.dp),
        drawerContainerColor = Panel,
    ) {
        Column(Modifier.fillMaxSize().padding(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Filled.List, null, tint = Accent, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(8.dp))
                Text("对话", fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.weight(1f))
                Box(
                    Modifier.size(8.dp).background(
                        when (st.online) {
                            true -> Ok
                            false -> Danger
                            else -> Dim
                        }, CircleShape
                    )
                )
                Spacer(Modifier.width(6.dp))
                Text(
                    when (st.online) {
                        true -> "在线"
                        false -> "离线"
                        else -> "…"
                    },
                    fontSize = 11.sp,
                    color = Dim,
                )
            }
            Spacer(Modifier.height(4.dp))
            Text(
                st.activeUrl.ifBlank { st.serverUrl },
                fontSize = 10.sp,
                color = Dim,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Spacer(Modifier.height(10.dp))

            Button(onClick = onNew, modifier = Modifier.fillMaxWidth()) {
                Icon(Icons.Filled.Add, null, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(6.dp))
                Text("新建对话")
            }
            Spacer(Modifier.height(10.dp))

            LazyColumn(Modifier.weight(1f)) {
                items(st.conversations, key = { it.id }) { c ->
                    ConvRow(c, c.id == st.currentId, onClick = { onPick(c.id) }, onDelete = { onDelete(c.id) })
                }
            }

            HorizontalDivider(color = Color(0xFF243149))
            Text(
                if (st.loaded.isEmpty()) "显存占用：无模型驻留" else "显存占用：${st.loaded.joinToString()}",
                fontSize = 11.sp,
                color = if (st.loaded.isEmpty()) Dim else Ok,
                modifier = Modifier.padding(vertical = 6.dp, horizontal = 2.dp),
            )
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
                TextButton(onClick = onUnload) {
                    Icon(Icons.Filled.Memory, null, modifier = Modifier.size(16.dp))
                    Spacer(Modifier.width(4.dp))
                    Text("卸载模型", fontSize = 12.sp)
                }
                TextButton(onClick = onRefresh) {
                    Icon(Icons.Filled.Refresh, null, modifier = Modifier.size(16.dp))
                    Spacer(Modifier.width(4.dp))
                    Text("刷新", fontSize = 12.sp)
                }
                TextButton(onClick = onSettings) {
                    Icon(Icons.Filled.Settings, null, modifier = Modifier.size(16.dp))
                    Spacer(Modifier.width(4.dp))
                    Text("设置", fontSize = 12.sp)
                }
            }
        }
    }
}

@Composable
private fun ConvRow(c: Conversation, selected: Boolean, onClick: () -> Unit, onDelete: () -> Unit) {
    Surface(
        color = if (selected) PanelHi else Color.Transparent,
        shape = RoundedCornerShape(10.dp),
        modifier = Modifier.fillMaxWidth().padding(vertical = 2.dp).clickable { onClick() },
    ) {
        Row(Modifier.padding(start = 10.dp, end = 4.dp, top = 8.dp, bottom = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(
                    c.title.ifBlank { "新对话" },
                    fontSize = 13.5.sp,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    color = if (selected) Accent else Color(0xFFE8EEF7),
                )
                Text(
                    "${c.model.ifBlank { "未选模型" }} · ${c.messages.size} 条",
                    fontSize = 10.5.sp,
                    color = Dim,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            IconButton(onClick = onDelete, modifier = Modifier.size(32.dp)) {
                Icon(Icons.Filled.Delete, contentDescription = "删除", tint = Dim, modifier = Modifier.size(16.dp))
            }
        }
    }
}

// ---------------- 设置 ----------------
@Composable
private fun SettingsDialog(
    st: UiState,
    onDismiss: () -> Unit,
    onSave: (String, String, String, String) -> Unit,
    onTest: (String, String, String, String) -> Unit,
    onUnload: () -> Unit,
) {
    var url by remember { mutableStateOf(st.serverUrl) }
    var backup by remember { mutableStateOf(st.backupUrl) }
    var keepAlive by remember { mutableStateOf(st.keepAlive) }
    var prompt by remember { mutableStateOf(st.systemPrompt) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("连接设置", fontSize = 17.sp) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                OutlinedTextField(
                    value = url,
                    onValueChange = { url = it },
                    label = { Text("主地址（Tailscale IP）", fontSize = 12.sp) },
                    placeholder = { Text("http://100.64.0.1:11434", fontSize = 12.sp) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(10.dp))
                OutlinedTextField(
                    value = backup,
                    onValueChange = { backup = it },
                    label = { Text("备用地址（可选，主地址失败时自动尝试）", fontSize = 12.sp) },
                    placeholder = { Text("http://192.168.1.100:11434", fontSize = 12.sp) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(10.dp))
                OutlinedTextField(
                    value = keepAlive,
                    onValueChange = { keepAlive = it },
                    label = { Text("对话后保持加载 (keep_alive)", fontSize = 12.sp) },
                    placeholder = { Text("5m", fontSize = 12.sp) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(10.dp))
                OutlinedTextField(
                    value = prompt,
                    onValueChange = { prompt = it },
                    label = { Text("系统提示词（可留空）", fontSize = 12.sp) },
                    minLines = 2,
                    maxLines = 5,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(12.dp))
                Text(
                    "当前驻留显存：" + if (st.loaded.isEmpty()) "无" else st.loaded.joinToString(),
                    fontSize = 11.sp,
                    color = Dim,
                )
                Spacer(Modifier.height(6.dp))
                Row {
                    OutlinedButton(onClick = { onTest(url, backup, keepAlive, prompt) }) {
                        Icon(Icons.Filled.Refresh, null, modifier = Modifier.size(15.dp))
                        Spacer(Modifier.width(4.dp))
                        Text("测试连接", fontSize = 12.sp)
                    }
                    Spacer(Modifier.width(8.dp))
                    OutlinedButton(onClick = onUnload) {
                        Icon(Icons.Filled.Memory, null, modifier = Modifier.size(15.dp))
                        Spacer(Modifier.width(4.dp))
                        Text("卸载模型", fontSize = 12.sp)
                    }
                }
                Spacer(Modifier.height(8.dp))
                Text(
                    "提示：主地址填电脑的 Tailscale IP（100.x.x.x）。手机与电脑登录同一 Tailscale 账号后，任何网络下都能连；没开 Tailscale 时会自动退回备用地址（家里 Wi-Fi）。",
                    fontSize = 11.sp,
                    color = Dim,
                    lineHeight = 16.sp,
                )
            }
        },
        confirmButton = {
            TextButton(onClick = { onSave(url, backup, keepAlive, prompt) }) { Text("保存") }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("取消") }
        },
    )
}
