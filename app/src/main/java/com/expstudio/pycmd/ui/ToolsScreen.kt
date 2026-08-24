package com.expstudio.pycmd.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Switch
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.expstudio.pycmd.plugins.PluginIds
import com.expstudio.pycmd.plugins.PluginScreen
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONObject

/**
 * The screens the Tools plugins open.
 *
 * All five share one shape - inputs at the top, a result below, a copy button
 * - and all five do their actual work in Python, so what Regex Lab reports is
 * exactly what `re` will do in the script being written next to it.
 */
@Composable
fun ToolScreen(
    screen: PluginScreen,
    viewModel: MainViewModel,
    modifier: Modifier = Modifier,
) {
    when (screen) {
        PluginScreen.JSON_TOOLS -> JsonToolsScreen(viewModel, modifier)
        PluginScreen.TEXT_TOOLS -> TextToolsScreen(viewModel, modifier)
        PluginScreen.REGEX_LAB -> RegexLabScreen(viewModel, modifier)
        PluginScreen.HTTP_CLIENT -> ApiTesterScreen(viewModel, modifier)
        PluginScreen.SEARCH -> WorkspaceSearchScreen(viewModel, modifier)
    }
}

// ---------------------------------------------------------------- JSON tools

@Composable
private fun JsonToolsScreen(viewModel: MainViewModel, modifier: Modifier) {
    val scope = rememberCoroutineScope()
    var input by remember { mutableStateOf("") }
    var output by remember { mutableStateOf("") }
    var problem by remember { mutableStateOf<String?>(null) }
    var summary by remember { mutableStateOf("") }
    val powered = viewModel.isPluginPoweredUp(PluginIds.JSON_TOOLS)

    fun run(action: String, sort: Boolean = false) {
        scope.launch {
            val reply = viewModel.runTool(
                "json",
                JSONObject().put("text", input).put("action", action).put("sort", sort),
            )
            if (reply.optBoolean("ok")) {
                output = reply.optString("text")
                summary = reply.optString("summary")
                problem = null
            } else {
                problem = reply.optString("error", "that is not JSON")
                summary = ""
            }
        }
    }

    ToolLayout(
        title = "JSON Tools",
        subtitle = "Format, check and convert JSON. Nothing leaves the device.",
        modifier = modifier,
    ) {
        item {
            ToolInput(
                label = "JSON",
                value = input,
                onValueChange = { input = it },
                minLines = 5,
            )
        }
        item {
            ButtonWrap {
                ActionButton("Format", PyIcons.FormatIndentIncrease, { run("format") })
                GhostButton("Minify", PyIcons.WrapText, { run("minify") })
                GhostButton("Use editor file", PyIcons.Edit, {
                    input = viewModel.editorContent()
                })
            }
        }
        if (powered) {
            item {
                ButtonWrap {
                    GhostButton("Sort keys", PyIcons.Tune, { run("format", sort = true) })
                    GhostButton("As Python", PyIcons.Terminal, { run("python") })
                    GhostButton("List keys", PyIcons.Description, { run("keys") })
                }
            }
        }
        problem?.let { message ->
            item { ProblemCard(message) }
        }
        if (output.isNotEmpty()) {
            item {
                ResultCard(
                    title = if (summary.isNotEmpty()) "Valid JSON - $summary" else "Result",
                    body = output,
                    onUseInEditor = { viewModel.replaceEditorContent(output) },
                )
            }
        }
    }
}

// ---------------------------------------------------------------- text tools

private data class Conversion(val label: String, val action: String)

private val BASE_CONVERSIONS = listOf(
    Conversion("Base64 encode", "base64_encode"),
    Conversion("Base64 decode", "base64_decode"),
    Conversion("URL encode", "url_encode"),
    Conversion("URL decode", "url_decode"),
    Conversion("MD5", "md5"),
    Conversion("SHA-256", "sha256"),
    Conversion("UPPER", "upper"),
    Conversion("lower", "lower"),
    Conversion("snake_case", "snake"),
    Conversion("camelCase", "camel"),
    Conversion("Count", "count"),
)

private val POWERED_CONVERSIONS = listOf(
    Conversion("SHA-1", "sha1"),
    Conversion("SHA-512", "sha512"),
    Conversion("Hex encode", "hex_encode"),
    Conversion("Hex decode", "hex_decode"),
    Conversion("kebab-case", "kebab"),
    Conversion("Title Case", "title"),
    Conversion("ROT13", "rot13"),
    Conversion("Reverse", "reverse"),
    Conversion("Sort lines", "sort_lines"),
    Conversion("Unique lines", "unique_lines"),
    Conversion("Drop blank lines", "strip_blank"),
    Conversion("Escape", "escape"),
)

@Composable
private fun TextToolsScreen(viewModel: MainViewModel, modifier: Modifier) {
    val scope = rememberCoroutineScope()
    var input by remember { mutableStateOf("") }
    var output by remember { mutableStateOf("") }
    var problem by remember { mutableStateOf<String?>(null) }
    var chosen by remember { mutableStateOf("") }
    val powered = viewModel.isPluginPoweredUp(PluginIds.TEXT_TOOLS)
    val conversions = if (powered) BASE_CONVERSIONS + POWERED_CONVERSIONS else BASE_CONVERSIONS

    fun run(conversion: Conversion) {
        chosen = conversion.label
        scope.launch {
            val reply = viewModel.runTool(
                "text",
                JSONObject().put("text", input).put("action", conversion.action),
            )
            if (reply.optBoolean("ok")) {
                output = reply.optString("text")
                problem = null
            } else {
                problem = reply.optString("error")
            }
        }
    }

    ToolLayout(
        title = "Text Tools",
        subtitle = "The conversions you would otherwise open a website for.",
        modifier = modifier,
    ) {
        item {
            ToolInput(label = "Text", value = input, onValueChange = { input = it }, minLines = 4)
        }
        item {
            Column {
                SectionTitle("Convert")
                Chips(conversions.map { it.label }) { label ->
                    conversions.firstOrNull { it.label == label }?.let { run(it) }
                }
            }
        }
        problem?.let { item { ProblemCard(it) } }
        if (output.isNotEmpty()) {
            item {
                ResultCard(
                    title = chosen.ifEmpty { "Result" },
                    body = output,
                    onUseAsInput = { input = output },
                )
            }
        }
    }
}

// ------------------------------------------------------------------ regex lab

@Composable
private fun RegexLabScreen(viewModel: MainViewModel, modifier: Modifier) {
    val scope = rememberCoroutineScope()
    var pattern by remember { mutableStateOf("") }
    var subject by remember { mutableStateOf("") }
    var replacement by remember { mutableStateOf("") }
    var ignoreCase by remember { mutableStateOf(false) }
    var multiline by remember { mutableStateOf(false) }
    var result by remember { mutableStateOf<JSONObject?>(null) }
    val powered = viewModel.isPluginPoweredUp(PluginIds.REGEX_LAB)

    // Re-testing on every keystroke would run a regex per character; a short
    // pause after typing stops means the result still feels immediate.
    LaunchedEffect(pattern, subject, replacement, ignoreCase, multiline) {
        delay(200)
        result = viewModel.runTool(
            "regex",
            JSONObject()
                .put("pattern", pattern)
                .put("text", subject)
                .put("ignore_case", ignoreCase)
                .put("multiline", multiline)
                .apply { if (powered && replacement.isNotEmpty()) put("replacement", replacement) },
        )
    }

    ToolLayout(
        title = "Regex Lab",
        subtitle = "Tested with Python's own re module, so your script will agree with it.",
        modifier = modifier,
    ) {
        item {
            ToolInput(label = "Pattern", value = pattern, onValueChange = { pattern = it },
                      minLines = 1)
        }
        item {
            ToolInput(label = "Test against", value = subject, onValueChange = { subject = it },
                      minLines = 4)
        }
        if (powered) {
            item {
                ToolInput(
                    label = "Replacement (use \\1 for a group)",
                    value = replacement,
                    onValueChange = { replacement = it },
                    minLines = 1,
                )
            }
            item {
                PyCard {
                    ToggleRow("Ignore case", ignoreCase) { ignoreCase = it }
                    ToggleRow("^ and \$ match every line", multiline) { multiline = it }
                }
            }
        }

        val reply = result
        if (reply != null && !reply.optBoolean("ok", true)) {
            item { ProblemCard(reply.optString("error")) }
        } else if (reply != null && pattern.isNotEmpty()) {
            val count = reply.optInt("count")
            item {
                PyCard {
                    Text(
                        if (count == 0) "No matches" else
                            "$count match${if (count == 1) "" else "es"}" +
                                reply.optInt("groups").let {
                                    if (it > 0) ", $it capture group${if (it == 1) "" else "s"}"
                                    else ""
                                },
                        style = MaterialTheme.typography.titleMedium,
                        color = if (count == 0) MaterialTheme.colorScheme.onSurfaceVariant
                        else MaterialTheme.colorScheme.primary,
                    )
                }
            }
            val matches = reply.optJSONArray("matches")
            if (matches != null) {
                items((0 until minOf(matches.length(), 40)).toList()) { index ->
                    val match = matches.getJSONObject(index)
                    val groups = match.optJSONArray("groups")
                    PyCard {
                        Text(
                            match.optString("text"),
                            style = MaterialTheme.typography.bodyMedium,
                            fontFamily = MonoFamily,
                        )
                        Text(
                            "at ${match.optInt("start")}..${match.optInt("end")}" +
                                if (groups != null && groups.length() > 0) {
                                    "  groups: " + (0 until groups.length())
                                        .joinToString(", ") { groups.optString(it) }
                                } else "",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
            val substituted = reply.optString("substituted")
            if (substituted.isNotEmpty()) {
                item { ResultCard(title = "After substitution", body = substituted) }
            }
        }
    }
}

// ----------------------------------------------------------------- API tester

@Composable
private fun ApiTesterScreen(viewModel: MainViewModel, modifier: Modifier) {
    val scope = rememberCoroutineScope()
    var method by remember { mutableStateOf("GET") }
    var url by remember { mutableStateOf("http://127.0.0.1:8000/") }
    var headers by remember { mutableStateOf("") }
    var body by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var reply by remember { mutableStateOf<JSONObject?>(null) }
    val powered = viewModel.isPluginPoweredUp(PluginIds.HTTP_CLIENT)

    ToolLayout(
        title = "API Tester",
        subtitle = "Point it at the server you just started on this phone.",
        modifier = modifier,
    ) {
        item {
            Column {
                SectionTitle("Method")
                Chips(listOf("GET", "POST", "PUT", "PATCH", "DELETE"), selected = method) {
                    method = it
                }
            }
        }
        item { ToolInput("URL", url, { url = it }, minLines = 1) }
        if (powered) {
            item {
                ToolInput("Headers, one per line", headers, { headers = it }, minLines = 2)
            }
        }
        if (method != "GET") {
            item { ToolInput("Body", body, { body = it }, minLines = 3) }
        }
        item {
            ActionButton(
                text = if (busy) "Sending..." else "Send",
                icon = PyIcons.Send,
                enabled = !busy && url.isNotBlank(),
                onClick = {
                    busy = true
                    scope.launch {
                        reply = viewModel.runTool(
                            "http",
                            JSONObject()
                                .put("method", method)
                                .put("url", url)
                                .put("headers", headers)
                                .put("body", body),
                        )
                        busy = false
                    }
                },
                modifier = Modifier.fillMaxWidth(),
            )
        }

        val response = reply
        if (response != null) {
            if (!response.optBoolean("ok")) {
                item { ProblemCard(response.optString("error")) }
            } else {
                item {
                    val status = response.optInt("status")
                    PyCard {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            StatusChip(
                                "$status ${response.optString("reason")}".trim(),
                                if (status in 200..299) MaterialTheme.colorScheme.primary
                                else MaterialTheme.colorScheme.error,
                            )
                            Spacer(Modifier.width(10.dp))
                            Text(
                                "${response.optInt("millis")} ms, " +
                                    "${response.optInt("bytes")} bytes",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                }
                if (powered && response.optString("headers").isNotEmpty()) {
                    item { ResultCard("Response headers", response.optString("headers")) }
                }
                item {
                    ResultCard(
                        title = "Response",
                        body = response.optString("body").ifEmpty { "(empty)" },
                        onUseInEditor = { viewModel.replaceEditorContent(response.optString("body")) },
                    )
                }
            }
        }
    }
}

// ----------------------------------------------------------- workspace search

@Composable
private fun WorkspaceSearchScreen(viewModel: MainViewModel, modifier: Modifier) {
    val scope = rememberCoroutineScope()
    var query by remember { mutableStateOf("") }
    var caseSensitive by remember { mutableStateOf(false) }
    var wholeWord by remember { mutableStateOf(false) }
    var useRegex by remember { mutableStateOf(false) }
    var reply by remember { mutableStateOf<JSONObject?>(null) }
    var busy by remember { mutableStateOf(false) }
    val powered = viewModel.isPluginPoweredUp(PluginIds.SEARCH)

    fun search() {
        if (query.isBlank()) return
        busy = true
        scope.launch {
            reply = viewModel.runTool(
                "search",
                JSONObject()
                    .put("root", viewModel.workspaceRoot.absolutePath)
                    .put("query", query)
                    .put("case_sensitive", caseSensitive)
                    .put("whole_word", wholeWord)
                    .put("regex", useRegex),
            )
            busy = false
        }
    }

    ToolLayout(
        title = "Workspace Search",
        subtitle = "Looks through every text file you have written.",
        modifier = modifier,
    ) {
        item { ToolInput("Find", query, { query = it }, minLines = 1) }
        if (powered) {
            item {
                PyCard {
                    ToggleRow("Match case", caseSensitive) { caseSensitive = it }
                    ToggleRow("Whole words only", wholeWord) { wholeWord = it }
                    ToggleRow("Regular expression", useRegex) { useRegex = it }
                }
            }
        }
        item {
            ActionButton(
                text = if (busy) "Searching..." else "Search",
                icon = PyIcons.Search,
                onClick = { search() },
                enabled = !busy && query.isNotBlank(),
                modifier = Modifier.fillMaxWidth(),
            )
        }

        val response = reply
        if (response != null) {
            if (!response.optBoolean("ok")) {
                item { ProblemCard(response.optString("error")) }
            } else {
                val hits = response.optJSONArray("hits")
                val count = hits?.length() ?: 0
                item {
                    SectionTitle(
                        "$count result${if (count == 1) "" else "s"} " +
                            "in ${response.optInt("files")} files" +
                            if (response.optBoolean("truncated")) " (showing the first $count)" else ""
                    )
                }
                if (count == 0) {
                    item {
                        EmptyState(
                            icon = PyIcons.Search,
                            title = "Nothing found",
                            hint = "No file in the workspace contains that.",
                        )
                    }
                }
                items((0 until count).toList()) { index ->
                    // `count` is zero when hits is null, so this list is empty
                    // in that case - but reading it defensively costs nothing
                    // and cannot be broken by a later edit to the count.
                    val hit = hits?.optJSONObject(index) ?: return@items
                    PyCard(contentPadding = PaddingValues(0.dp)) {
                        Column(
                            Modifier
                                .fillMaxWidth()
                                .clickable { viewModel.openSearchHit(hit.optString("path")) }
                                .padding(14.dp),
                        ) {
                            Text(
                                "${hit.optString("name")}:${hit.optInt("line")}",
                                style = MaterialTheme.typography.labelMedium,
                                color = MaterialTheme.colorScheme.primary,
                            )
                            Spacer(Modifier.height(4.dp))
                            Text(
                                hit.optString("text"),
                                style = MaterialTheme.typography.bodySmall,
                                fontFamily = MonoFamily,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                }
            }
        }
    }
}

// -------------------------------------------------------------- shared parts

@Composable
private fun ToolLayout(
    title: String,
    subtitle: String,
    modifier: Modifier = Modifier,
    content: androidx.compose.foundation.lazy.LazyListScope.() -> Unit,
) {
    LazyColumn(
        modifier.fillMaxSize(),
        contentPadding = PaddingValues(14.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item {
            Column {
                Text(title, style = MaterialTheme.typography.titleLarge,
                     fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.height(4.dp))
                Text(
                    subtitle,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        content()
        item { Spacer(Modifier.height(20.dp)) }
    }
}

@Composable
private fun ToolInput(
    label: String,
    value: String,
    onValueChange: (String) -> Unit,
    minLines: Int,
) {
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        modifier = Modifier.fillMaxWidth(),
        label = { Text(label, style = MaterialTheme.typography.labelMedium) },
        minLines = minLines,
        maxLines = if (minLines > 1) 10 else 2,
        shape = RoundedCornerShape(12.dp),
        textStyle = MaterialTheme.typography.bodyMedium.copy(fontFamily = MonoFamily),
        colors = OutlinedTextFieldDefaults.colors(
            focusedBorderColor = MaterialTheme.colorScheme.primary,
            unfocusedBorderColor = MaterialTheme.colorScheme.outline,
        ),
    )
}

@Composable
private fun ButtonWrap(content: @Composable () -> Unit) {
    Row(
        Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        content()
    }
}

@Composable
private fun Chips(labels: List<String>, selected: String? = null, onPick: (String) -> Unit) {
    Row(
        Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        labels.forEach { label ->
            val active = label == selected
            Surface(
                color = if (active) MaterialTheme.colorScheme.primary.copy(alpha = 0.16f)
                else MaterialTheme.colorScheme.surface,
                contentColor = if (active) MaterialTheme.colorScheme.primary
                else MaterialTheme.colorScheme.onSurface,
                shape = RoundedCornerShape(10.dp),
                border = androidx.compose.foundation.BorderStroke(
                    1.dp,
                    if (active) MaterialTheme.colorScheme.primary
                    else MaterialTheme.colorScheme.outline,
                ),
                onClick = { onPick(label) },
            ) {
                Text(
                    label,
                    style = MaterialTheme.typography.labelLarge,
                    modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp),
                )
            }
        }
    }
}

@Composable
private fun ToggleRow(label: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(
        Modifier.fillMaxWidth().padding(vertical = 2.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(label, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
        Switch(checked = checked, onCheckedChange = onChange)
    }
}

@Composable
private fun ProblemCard(message: String) {
    Box(
        Modifier
            .fillMaxWidth()
            .background(
                MaterialTheme.colorScheme.error.copy(alpha = 0.12f),
                RoundedCornerShape(12.dp),
            )
            .padding(14.dp),
    ) {
        Row(verticalAlignment = Alignment.Top) {
            Icon(
                PyIcons.BugReport,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.error,
                modifier = Modifier.size(18.dp),
            )
            Spacer(Modifier.width(10.dp))
            Text(
                message,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
            )
        }
    }
}

@Composable
private fun ResultCard(
    title: String,
    body: String,
    onUseInEditor: (() -> Unit)? = null,
    onUseAsInput: (() -> Unit)? = null,
) {
    val clipboard = LocalClipboardManager.current
    PyCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(title, style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
            GhostButton("Copy", PyIcons.ContentCopy, {
                clipboard.setText(AnnotatedString(body))
            })
        }
        Spacer(Modifier.height(10.dp))
        Box(
            Modifier
                .fillMaxWidth()
                .heightIn(max = 320.dp)
                .background(MaterialTheme.colorScheme.surfaceVariant, RoundedCornerShape(10.dp))
                .padding(12.dp),
        ) {
            Text(
                body,
                style = MaterialTheme.typography.bodySmall,
                fontFamily = MonoFamily,
            )
        }
        if (onUseInEditor != null || onUseAsInput != null) {
            Spacer(Modifier.height(10.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (onUseAsInput != null) {
                    GhostButton("Use as input", PyIcons.ArrowUpward, onUseAsInput)
                }
                if (onUseInEditor != null) {
                    GhostButton("Into the editor", PyIcons.Edit, onUseInEditor)
                }
            }
        }
    }
}
