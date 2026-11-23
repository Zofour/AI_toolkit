package com.chatbox.filehub

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Computer
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch

@Composable
fun SetupScreen(
    initialBase: String,
    initialToken: String,
    canCancel: Boolean,
    onCancel: () -> Unit,
    onSaved: (String, String) -> Unit,
) {
    var base by remember { mutableStateOf(initialBase) }
    var token by remember { mutableStateOf(initialToken) }
    var testing by remember { mutableStateOf(false) }
    var result by remember { mutableStateOf<String?>(null) }
    var resultOk by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    fun doTest(onOk: (() -> Unit)? = null) {
        val b = Api.normalizeBase(base)
        if (b.isEmpty()) {
            result = "请填写电脑地址"; resultOk = false; return
        }
        testing = true; result = null
        scope.launch {
            try {
                val name = Api(b, token.trim()).ping()
                resultOk = true
                result = "已连接：$name"
                onOk?.invoke()
            } catch (e: Exception) {
                resultOk = false
                result = "连接失败：${e.message ?: "未知错误"}"
            } finally {
                testing = false
            }
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background)
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 22.dp),
    ) {
        Spacer(Modifier.height(56.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            if (canCancel) {
                IconButton(onClick = onCancel) {
                    Icon(Icons.Filled.ArrowBack, contentDescription = "返回")
                }
            }
            Icon(
                Icons.Filled.Computer,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(30.dp),
            )
            Spacer(Modifier.size(10.dp))
            Text("连接电脑", style = MaterialTheme.typography.headlineSmall)
        }

        Spacer(Modifier.height(6.dp))
        Text(
            "手机通过 Tailscale 直连电脑上运行的 FileHub 服务，只能看，不能改。",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        Spacer(Modifier.height(26.dp))
        OutlinedTextField(
            value = base,
            onValueChange = { base = it },
            label = { Text("电脑地址") },
            placeholder = { Text("http://100.64.0.1:8730") },
            singleLine = true,
            keyboardOptions = KeyboardOptions(
                keyboardType = KeyboardType.Uri,
                imeAction = ImeAction.Next,
            ),
            textStyle = MaterialTheme.typography.bodyMedium.copy(fontFamily = FontFamily.Monospace),
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(12.dp))
        OutlinedTextField(
            value = token,
            onValueChange = { token = it },
            label = { Text("访问令牌") },
            singleLine = true,
            keyboardOptions = KeyboardOptions(
                keyboardType = KeyboardType.Ascii,
                imeAction = ImeAction.Done,
            ),
            textStyle = MaterialTheme.typography.bodyMedium.copy(fontFamily = FontFamily.Monospace),
            modifier = Modifier.fillMaxWidth(),
        )

        Spacer(Modifier.height(22.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Button(
                onClick = { doTest() },
                enabled = !testing,
                modifier = Modifier.weight(1f),
            ) {
                if (testing) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(18.dp),
                        strokeWidth = 2.dp,
                        color = MaterialTheme.colorScheme.onPrimary,
                    )
                    Spacer(Modifier.size(8.dp))
                }
                Text(if (testing) "连接中…" else "测试连接")
            }
            OutlinedButton(
                onClick = {
                    val b = Api.normalizeBase(base)
                    onSaved(b, token.trim())
                },
                enabled = !testing && base.isNotBlank(),
                modifier = Modifier.weight(1f),
            ) { Text("保存并进入") }
        }

        result?.let { msg ->
            Spacer(Modifier.height(18.dp))
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier
                    .fillMaxWidth()
                    .background(
                        (if (resultOk) MaterialTheme.colorScheme.secondary
                        else MaterialTheme.colorScheme.error).copy(alpha = 0.12f),
                        RoundedCornerShape(10.dp),
                    )
                    .padding(12.dp),
            ) {
                if (resultOk) {
                    Icon(
                        Icons.Filled.CheckCircle,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.secondary,
                        modifier = Modifier.size(18.dp),
                    )
                    Spacer(Modifier.size(8.dp))
                }
                Text(
                    msg,
                    fontSize = 13.sp,
                    color = if (resultOk) MaterialTheme.colorScheme.secondary
                    else MaterialTheme.colorScheme.error,
                )
            }
        }

        Spacer(Modifier.height(28.dp))
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .background(MaterialTheme.colorScheme.surface, RoundedCornerShape(12.dp))
                .padding(14.dp),
        ) {
            Column {
                Text("电脑端怎么启动？", style = MaterialTheme.typography.titleSmall)
                Spacer(Modifier.height(8.dp))
                Text(
                    "双击 C:\\chatbox_temp\\filehub\\server\\run.bat\n" +
                        "窗口里会打印 Tailscale 地址与令牌，端口 8730。",
                    fontSize = 12.sp,
                    fontFamily = FontFamily.Monospace,
                    lineHeight = 18.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        Spacer(Modifier.height(40.dp))
    }
}
