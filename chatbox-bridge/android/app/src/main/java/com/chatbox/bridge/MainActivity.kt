package com.chatbox.bridge

import android.Manifest
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Chat
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.Image
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Psychology
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Terminal
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TextField
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import coil.request.ImageRequest
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val s = Settings(this)
        if (s.configured) {
            val i = android.content.Intent(this, BridgeService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) startForegroundService(i) else startService(i)
        }
        setContent { AppRoot() }
    }
}

@Composable
fun ChatboxBridgeTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = lightColorScheme(
            primary = Color(0xFF3B5BFE),
            onPrimary = Color.White,
            primaryContainer = Color(0xFFDDE3FF),
            secondary = Color(0xFF5A5F72),
        ),
        content = content
    )
}

@Composable
fun AppRoot() {
    val vm: BridgeViewModel = androidx.lifecycle.viewmodel.compose.viewModel()
    ChatboxBridgeTheme {
        val configured by vm.configured.collectAsState()
        var settingsOpen by remember { mutableStateOf(false) }
        var openSession by remember { mutableStateOf<String?>(null) }
        var composing by remember { mutableStateOf(false) }

        LaunchedEffect(Unit) {
            vm.newSession.collect { sid ->
                composing = false
                openSession = sid
                vm.openSession(sid)
            }
        }

        val permLauncher = rememberLauncherForActivityResult(
            ActivityResultContracts.RequestPermission()
        ) { }
        LaunchedEffect(Unit) {
            if (Build.VERSION.SDK_INT >= 33) permLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        }

        Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
            when {
                !configured -> SetupScreen(vm)
                settingsOpen -> SettingsScreen(vm) { settingsOpen = false }
                openSession != null -> ChatScreen(vm, openSession!!) { openSession = null }
                composing -> NewChatScreen(vm) { composing = false }
                else -> HomeScreen(vm,
                    onOpen = { sid -> openSession = sid; vm.openSession(sid) },
                    onNew = { vm.createSession(); composing = true },
                    onSettings = { settingsOpen = true })
            }
        }
    }
}

// --------------------------------------------------------------- 设置/首次配置
@Composable
fun SetupScreen(vm: BridgeViewModel) {
    var url by remember { mutableStateOf(vm.wsUrl.value) }
    var tk by remember { mutableStateOf(vm.token.value) }
    Column(
        Modifier.fillMaxSize().padding(20.dp).verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Spacer(Modifier.height(24.dp))
        Text("连接电脑端", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
        Text(
            "在电脑上运行 pc-relay 后，打开 http://127.0.0.1:8787/pair 查看地址与 Token（或扫描二维码）。\n" +
            "出门在外用 Tailscale 的 100.x 地址，在家用局域网地址。",
            style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.secondary
        )
        OutlinedTextField(
            value = url, onValueChange = { url = it },
            label = { Text("WebSocket 地址") },
            placeholder = { Text("ws://100.x.y.z:8787/ws") },
            singleLine = true, modifier = Modifier.fillMaxWidth()
        )
        OutlinedTextField(
            value = tk, onValueChange = { tk = it },
            label = { Text("Token") },
            singleLine = true, modifier = Modifier.fillMaxWidth()
        )
        Button(
            onClick = { vm.saveAndConnect(url, tk, true) },
            enabled = url.isNotBlank() && tk.isNotBlank(),
            modifier = Modifier.fillMaxWidth()
        ) { Text("保存并连接") }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(vm: BridgeViewModel, onBack: () -> Unit) {
    BackHandler { onBack() }
    var url by remember { mutableStateOf(vm.wsUrl.value) }
    var tk by remember { mutableStateOf(vm.token.value) }
    var notify by remember { mutableStateOf(vm.notifyLocal.value) }
    val state by vm.state.collectAsState()

    Scaffold(topBar = {
        TopAppBar(title = { Text("设置") }, navigationIcon = {
            IconButton(onClick = onBack) { Icon(Icons.Filled.ArrowBack, contentDescription = "返回") }
        })
    }) { pad ->
        Column(
            Modifier.padding(pad).padding(20.dp).verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            OutlinedTextField(url, { url = it }, label = { Text("WebSocket 地址") },
                singleLine = true, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(tk, { tk = it }, label = { Text("Token") },
                singleLine = true, modifier = Modifier.fillMaxWidth())
            Row(verticalAlignment = Alignment.CenterVertically) {
                Switch(checked = notify, onCheckedChange = { notify = it })
                Spacer(Modifier.width(10.dp))
                Text("收到回复时本地通知")
            }
            Text("当前状态：${stateLabel(state)}", color = MaterialTheme.colorScheme.secondary)
            Button(onClick = { vm.saveAndConnect(url, tk, notify) }, modifier = Modifier.fillMaxWidth()) {
                Text("保存并重连")
            }
            OutlinedButton(onClick = { vm.disconnect() }, modifier = Modifier.fillMaxWidth()) {
                Text("断开连接")
            }
        }
    }
}

// --------------------------------------------------------------- 新建会话
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun NewChatScreen(vm: BridgeViewModel, onBack: () -> Unit) {
    BackHandler { onBack() }
    val canControl by vm.canControl.collectAsState()
    val controlError by vm.controlError.collectAsState()
    var input by remember { mutableStateOf("") }
    var sent by remember { mutableStateOf(false) }

    LaunchedEffect(controlError) { if (controlError != null) sent = false }

    Scaffold(topBar = {
        TopAppBar(title = { Text("新对话") }, navigationIcon = {
            IconButton(onClick = onBack) { Icon(Icons.Filled.ArrowBack, contentDescription = "返回") }
        })
    }) { pad ->
        Column(
            Modifier.padding(pad).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            Text("在电脑 Chatbox 新建会话", style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold)
            Text("模型：转发手机 · DeepSeek V4.1 Flash（默认）\n发第一条消息后，会话会同时出现在电脑和手机里。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.secondary)
            if (!canControl) {
                Text("回控不可用：电脑上需运行注入器（start_bridge.bat）",
                    style = MaterialTheme.typography.labelSmall, color = Color(0xFFB3261E))
            }
            OutlinedTextField(
                value = input, onValueChange = { input = it },
                placeholder = { Text("说点什么开始新对话…") },
                enabled = canControl && !sent,
                minLines = 3, maxLines = 6,
                modifier = Modifier.fillMaxWidth()
            )
            Button(
                onClick = { vm.sendMessage(input, null); input = ""; sent = true },
                enabled = canControl && input.isNotBlank() && !sent,
                modifier = Modifier.fillMaxWidth()
            ) { Text(if (sent) "已发送" else "发送并开始") }
            if (sent) {
                Text("已发送，正在等待电脑端创建会话…",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.secondary)
            }
            if (controlError != null) {
                Text("⚠ $controlError", style = MaterialTheme.typography.labelSmall,
                    color = Color(0xFFB3261E))
            }
        }
    }
}

// --------------------------------------------------------------- 会话列表（长按清除）
@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun HomeScreen(vm: BridgeViewModel, onOpen: (String) -> Unit, onNew: () -> Unit, onSettings: () -> Unit) {
    val sessions by vm.sessions.collectAsState()
    val state by vm.state.collectAsState()
    var pending by remember { mutableStateOf<SessionMeta?>(null) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        StatusDot(state)
                        Spacer(Modifier.width(8.dp))
                        Text("Chatbox 会话")
                    }
                },
                actions = {
                    IconButton(onClick = onNew) { Icon(Icons.Filled.Add, contentDescription = "新建会话") }
                    IconButton(onClick = onSettings) { Icon(Icons.Filled.Settings, contentDescription = "设置") }
                }
            )
        }
    ) { pad ->
        if (sessions.isEmpty()) {
            Box(Modifier.padding(pad).fillMaxSize(), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    if (state == ConnState.CONNECTING) CircularProgressIndicator()
                    Spacer(Modifier.height(12.dp))
                    Text("暂无会话", color = MaterialTheme.colorScheme.secondary)
                    Text("在电脑上开始一段对话即可出现", style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.secondary)
                }
            }
        } else {
            LazyColumn(Modifier.padding(pad).fillMaxSize()) {
                item {
                    Text("长按会话可清除", style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.secondary,
                        modifier = Modifier.padding(start = 16.dp, top = 6.dp, bottom = 2.dp))
                }
                items(sessions, key = { it.id }) { s ->
                    Card(
                        modifier = Modifier.fillMaxWidth()
                            .padding(horizontal = 12.dp, vertical = 6.dp)
                            .combinedClickable(
                                onClick = { onOpen(s.id) },
                                onLongClick = { pending = s }
                            ),
                        colors = CardDefaults.cardColors(containerColor = Color.White)
                    ) {
                        Column(Modifier.padding(14.dp)) {
                            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                                Text(s.title.ifBlank { "(无标题)" }, fontWeight = FontWeight.SemiBold,
                                    maxLines = 1, overflow = TextOverflow.Ellipsis,
                                    modifier = Modifier.weight(1f))
                                Text(fmtTime(s.updated), style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.secondary)
                            }
                            if (s.last.isNotBlank()) {
                                Spacer(Modifier.height(4.dp))
                                Text(s.last, maxLines = 2, overflow = TextOverflow.Ellipsis,
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = MaterialTheme.colorScheme.secondary)
                            }
                        }
                    }
                }
            }
        }
    }

    pending?.let { s ->
        AlertDialog(
            onDismissRequest = { pending = null },
            title = { Text("清除会话") },
            text = { Text("确定删除「${s.title.ifBlank { "(无标题)" }}」及其全部消息？此操作不可恢复。") },
            confirmButton = {
                TextButton(onClick = { vm.deleteSession(s.id); pending = null }) { Text("删除") }
            },
            dismissButton = { TextButton(onClick = { pending = null }) { Text("取消") } }
        )
    }
}

// --------------------------------------------------------------- 对话（工作流时间线 + 收缩/展开）
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(vm: BridgeViewModel, sid: String, onBack: () -> Unit) {
    BackHandler { onBack() }
    val all by vm.messages.collectAsState()
    val sessions by vm.sessions.collectAsState()
    val state by vm.state.collectAsState()
    val canControl by vm.canControl.collectAsState()
    val controlError by vm.controlError.collectAsState()
    var input by remember { mutableStateOf("") }
    val list = all[sid] ?: emptyList()
    val title = sessions.firstOrNull { it.id == sid }?.title ?: "会话"
    val listState = rememberLazyListState()
    val expandedIds = remember { mutableStateMapOf<String, Boolean>() }

    LaunchedEffect(list.size, list.lastOrNull()?.text?.length) {
        if (list.isNotEmpty()) listState.scrollToItem(list.size - 1)
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text(title, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text(stateLabel(state), style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.secondary)
                    }
                },
                navigationIcon = {
                    IconButton(onClick = onBack) { Icon(Icons.Filled.ArrowBack, contentDescription = "返回") }
                }
            )
        },
        bottomBar = {
            Surface(shadowElevation = 8.dp) {
                Column {
                    if (!canControl) {
                        Text("回控不可用：电脑上需运行注入器（start_bridge.bat）",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.secondary,
                            modifier = Modifier.padding(start = 14.dp, top = 6.dp))
                    }
                    if (controlError != null) {
                        Text("⚠ $controlError", style = MaterialTheme.typography.labelSmall,
                            color = Color(0xFFB3261E),
                            modifier = Modifier.padding(start = 14.dp, top = 6.dp))
                    }
                    Row(Modifier.fillMaxWidth().padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                        OutlinedTextField(
                            value = input, onValueChange = { input = it },
                            placeholder = { Text("发消息（会显示在电脑 Chatbox 里）") },
                            enabled = canControl, maxLines = 4,
                            modifier = Modifier.weight(1f)
                        )
                        Spacer(Modifier.width(8.dp))
                        Button(
                            onClick = { vm.sendMessage(input, sid); input = "" },
                            enabled = canControl && input.isNotBlank()
                        ) { Text("发送") }
                    }
                }
            }
        }
    ) { pad ->
        if (list.isEmpty()) {
            Box(Modifier.padding(pad).fillMaxSize(), contentAlignment = Alignment.Center) {
                Text("该会话暂无消息", color = MaterialTheme.colorScheme.secondary)
            }
        } else {
            LazyColumn(
                state = listState,
                modifier = Modifier.padding(pad).fillMaxSize(),
                contentPadding = PaddingValues(12.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                items(list, key = { it.id }) { m ->
                    TimelineItem(m, expandedIds[m.id] == true, { vm.blobUrl(it) }) {
                        expandedIds[m.id] = !(expandedIds[m.id] ?: false)
                    }
                }
            }
        }
    }
}

/** 一条时间线事件：默认收缩，点击卡片展开/收起。 */
@Composable
fun TimelineItem(m: Message, expanded: Boolean, blobUrl: (String) -> String, onToggle: () -> Unit) {
    val expandable = m.text.length > 80
    val collapsed = expandable && !expanded

    if (m.kind == "image" && m.blob != null) {
        var big by remember { mutableStateOf(false) }
        val url = blobUrl(m.blob)
        Card(
            Modifier.fillMaxWidth(), shape = RoundedCornerShape(12.dp),
            colors = CardDefaults.cardColors(containerColor = Color.White)
        ) {
            Column(Modifier.padding(12.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Filled.Image, contentDescription = null,
                        tint = Color(0xFF0E7A8A), modifier = Modifier.size(16.dp))
                    Spacer(Modifier.width(6.dp))
                    Text("图片", style = MaterialTheme.typography.labelLarge,
                        fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.secondary)
                }
                Spacer(Modifier.height(6.dp))
                AsyncImage(
                    model = ImageRequest.Builder(LocalContext.current).data(url).crossfade(true).build(),
                    contentDescription = "图片",
                    contentScale = ContentScale.Fit,
                    modifier = Modifier.fillMaxWidth().heightIn(max = 320.dp)
                        .clip(RoundedCornerShape(8.dp)).clickable { big = true }
                )
                Text("点击可放大", style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.secondary,
                    modifier = Modifier.padding(top = 4.dp))
            }
        }
        if (big) {
            Dialog(onDismissRequest = { big = false }) {
                Surface(color = Color(0xE6000000), shape = RoundedCornerShape(8.dp)) {
                    AsyncImage(
                        model = ImageRequest.Builder(LocalContext.current).data(url).build(),
                        contentDescription = "图片",
                        contentScale = ContentScale.Fit,
                        modifier = Modifier.fillMaxWidth().padding(8.dp).clickable { big = false }
                    )
                }
            }
        }
        return
    }

    if (m.kind == "user") {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
            Card(
                modifier = Modifier
                    .fillMaxWidth(0.86f)
                    .then(if (expandable) Modifier.clickable { onToggle() } else Modifier),
                shape = RoundedCornerShape(14.dp),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer)
            ) {
                Column(Modifier.padding(12.dp)) {
                    MdText(m.text, MaterialTheme.colorScheme.onSurface, collapsed)
                    if (expandable) ExpandHint(expanded, alignEnd = true)
                }
            }
        }
        return
    }

    val icon: ImageVector
    val tint: Color
    when (m.kind) {
        "reason" -> { icon = Icons.Filled.Psychology; tint = Color(0xFF7C5CFF) }
        "tool" -> { icon = Icons.Filled.Terminal; tint = Color(0xFF0E8A6B) }
        "tool_result" -> { icon = Icons.Filled.Description; tint = Color(0xFF0E7A8A) }
        else -> { icon = Icons.Filled.Chat; tint = MaterialTheme.colorScheme.primary }
    }
    val title = when (m.kind) {
        "reason" -> "已深度思考"
        "tool" -> if (!m.name.isNullOrBlank()) "运行命令 · ${m.name}" else "运行命令"
        "tool_result" -> "工具返回"
        else -> null
    }

    Card(
        modifier = Modifier.fillMaxWidth()
            .then(if (expandable) Modifier.clickable { onToggle() } else Modifier),
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(containerColor = Color.White)
    ) {
        Row(Modifier.padding(12.dp)) {
            Box(
                Modifier.size(28.dp).clip(CircleShape).background(tint.copy(alpha = 0.14f)),
                contentAlignment = Alignment.Center
            ) { Icon(icon, contentDescription = null, tint = tint, modifier = Modifier.size(17.dp)) }
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                if (title != null) {
                    Text(title, style = MaterialTheme.typography.labelLarge,
                        fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.secondary)
                    Spacer(Modifier.height(3.dp))
                }
                when (m.kind) {
                    "reason" -> Text(
                        m.text.ifBlank { "…" },
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.secondary,
                        maxLines = if (collapsed) 2 else Int.MAX_VALUE,
                        overflow = TextOverflow.Ellipsis
                    )
                    "tool", "tool_result" -> MonoBlock(m.text, collapsed)
                    else -> MdText(m.text.ifBlank { if (!m.done) "…" else "" },
                        MaterialTheme.colorScheme.onSurface, collapsed)
                }
                if (expandable) ExpandHint(expanded)
                if (!m.done) {
                    Spacer(Modifier.height(4.dp))
                    Text("进行中…", style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.secondary)
                }
                if (m.error != null) {
                    Spacer(Modifier.height(4.dp))
                    Text("⚠ ${m.error}", style = MaterialTheme.typography.labelSmall, color = Color(0xFFB3261E))
                }
            }
        }
    }
}

@Composable
fun ExpandHint(expanded: Boolean, alignEnd: Boolean = false) {
    Row(
        Modifier.fillMaxWidth().padding(top = 6.dp),
        horizontalArrangement = if (alignEnd) Arrangement.End else Arrangement.Start,
        verticalAlignment = Alignment.CenterVertically
    ) {
        Icon(
            if (expanded) Icons.Filled.ExpandLess else Icons.Filled.ExpandMore,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.primary,
            modifier = Modifier.size(16.dp)
        )
        Spacer(Modifier.width(2.dp))
        Text(
            if (expanded) "收起" else "展开",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.primary
        )
    }
}

/** 深色等宽代码块。 */
@Composable
fun MonoBlock(body: String, collapsed: Boolean = false) {
    if (body.isBlank()) return
    Surface(
        color = Color(0xFF101828),
        shape = RoundedCornerShape(8.dp),
        modifier = Modifier.fillMaxWidth()
    ) {
        Text(
            body.trimEnd('\n'),
            color = Color(0xFFE7EAF3),
            fontFamily = FontFamily.Monospace,
            style = MaterialTheme.typography.bodySmall,
            maxLines = if (collapsed) 3 else Int.MAX_VALUE,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.padding(10.dp)
        )
    }
}

/** 极简 Markdown：``` 代码块→等宽底色块；行内 **粗体** 与 `代码`。 */
@Composable
fun MdText(text: String, color: Color, collapsed: Boolean = false) {
    if (text.isEmpty()) return
    val maxL = if (collapsed) 2 else Int.MAX_VALUE
    if (!text.contains("```")) {
        Text(inlineMarkdown(text), color = color, maxLines = maxL, overflow = TextOverflow.Ellipsis)
        return
    }
    val parts = text.split("```")
    Column {
        parts.forEachIndexed { i, seg ->
            if (i % 2 == 1) {
                val body = seg.substringAfter('\n', seg)
                Surface(
                    color = Color(0xFF101828),
                    shape = RoundedCornerShape(8.dp),
                    modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp)
                ) {
                    Text(
                        body.trimEnd('\n'),
                        color = Color(0xFFE7EAF3),
                        fontFamily = FontFamily.Monospace,
                        style = MaterialTheme.typography.bodySmall,
                        maxLines = if (collapsed) 3 else Int.MAX_VALUE,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.padding(10.dp)
                    )
                }
            } else {
                val t = seg.trim('\n')
                if (t.isNotEmpty()) Text(inlineMarkdown(t), color = color, maxLines = maxL, overflow = TextOverflow.Ellipsis)
            }
        }
    }
}

private val mdRe = Regex("(\\*\\*[^*\\n]+\\*\\*|`[^`\\n]+`)")

fun inlineMarkdown(s: String): AnnotatedString = buildAnnotatedString {
    val bold = SpanStyle(fontWeight = FontWeight.Bold)
    val code = SpanStyle(fontFamily = FontFamily.Monospace, background = Color(0x1A000000))
    var last = 0
    for (m in mdRe.findAll(s)) {
        if (m.range.first > last) append(s.substring(last, m.range.first))
        val tok = m.value
        if (tok.startsWith("**")) withStyle(bold) { append(tok.substring(2, tok.length - 2)) }
        else withStyle(code) { append(tok.substring(1, tok.length - 1)) }
        last = m.range.last + 1
    }
    if (last < s.length) append(s.substring(last))
}

// --------------------------------------------------------------- 小组件
@Composable
fun StatusDot(state: ConnState) {
    val color = when (state) {
        ConnState.CONNECTED -> Color(0xFF2E7D32)
        ConnState.CONNECTING -> Color(0xFFF9A825)
        ConnState.ERROR -> Color(0xFFC62828)
        ConnState.DISCONNECTED -> Color(0xFF9E9E9E)
    }
    Box(Modifier.size(10.dp).background(color, CircleShape))
}

fun stateLabel(state: ConnState): String = when (state) {
    ConnState.CONNECTED -> "已连接"
    ConnState.CONNECTING -> "连接中…"
    ConnState.ERROR -> "连接失败，重试中"
    ConnState.DISCONNECTED -> "已断开"
}

fun fmtTime(ms: Long): String {
    if (ms <= 0) return ""
    return SimpleDateFormat("MM-dd HH:mm", Locale.getDefault()).format(Date(ms))
}
