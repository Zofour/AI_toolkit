package com.chatbox.filehub

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            FileHubTheme {
                Surface(modifier = Modifier.fillMaxSize(), color = Color(0xFF0E1013)) {
                    AppRoot()
                }
            }
        }
    }
}

@Composable
fun FileHubTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = darkColorScheme(
            primary = Color(0xFF7CACF8),
            onPrimary = Color(0xFF07131F),
            secondary = Color(0xFF8FD3C7),
            background = Color(0xFF0E1013),
            surface = Color(0xFF14181E),
            surfaceVariant = Color(0xFF2A3038),
            onSurface = Color(0xFFE7EAF0),
            onSurfaceVariant = Color(0xFFB7C0CC),
        ),
        content = content,
    )
}

/** 页面栈里的两种页面 */
sealed interface Route {
    data class Browse(val path: String) : Route
    data class Viewer(
        val items: List<MediaEntry>,
        val index: Int,
        val folder: String,
    ) : Route
}

@Composable
fun AppRoot() {
    val ctx = LocalContext.current
    val prefs = remember { Prefs(ctx) }
    var configured by remember { mutableStateOf(prefs.configured) }
    var editing by remember { mutableStateOf(false) }

    if (!configured || editing) {
        SetupScreen(
            initialBase = prefs.baseUrl,
            initialToken = prefs.token,
            canCancel = configured,
            onCancel = { editing = false },
            onSaved = { base, token ->
                prefs.baseUrl = base
                prefs.token = token
                prefs.configured = true
                configured = true
                editing = false
            },
        )
        return
    }

    val api = remember(prefs.baseUrl, prefs.token) { Api(prefs.baseUrl, prefs.token) }
    MainNav(api = api, onOpenSettings = { editing = true })
}

@Composable
private fun MainNav(api: Api, onOpenSettings: () -> Unit) {
    val stack = remember { mutableStateListOf<Route>(Route.Browse("")) }
    BackHandler(enabled = stack.size > 1) {
        if (stack.size > 1) stack.removeAt(stack.lastIndex)
    }

    when (val cur = stack.last()) {
        is Route.Browse -> BrowseScreen(
            api = api,
            path = cur.path,
            onOpenDir = { e -> stack.add(Route.Browse(e.path)) },
            onBack = { if (stack.size > 1) stack.removeAt(stack.lastIndex) },
            onOpenViewer = { items, index, folder ->
                stack.add(Route.Viewer(items, index, folder))
            },
            onOpenSettings = onOpenSettings,
        )

        is Route.Viewer -> ViewerScreen(
            api = api,
            items = cur.items,
            startIndex = cur.index,
            folderName = cur.folder,
            onClose = { if (stack.size > 1) stack.removeAt(stack.lastIndex) },
        )
    }
}
