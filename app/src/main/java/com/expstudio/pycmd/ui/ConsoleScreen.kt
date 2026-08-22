package com.expstudio.pycmd.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.Clear
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.unit.dp
import com.expstudio.pycmd.python.EngineStatus

/** Characters the on-screen keyboard buries but Python needs constantly. */
private val CONSOLE_KEYS = listOf(
    ":", "(", ")", "[", "]", "{", "}", "=", "\"", "'", ".", ",", "_", "+", "-",
    "*", "/", "%", "<", ">", "|", "#",
)

@Composable
fun ConsoleScreen(
    host: WebHost,
    status: EngineStatus,
    history: List<String>,
    onRun: (String) -> Unit,
    onStdin: (String) -> Unit,
    onStop: () -> Unit,
    onClear: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var field by remember { mutableStateOf(TextFieldValue("")) }
    var historyOpen by remember { mutableStateOf(false) }

    val awaitingInput = status.awaitingInput
    val canSubmit = field.text.isNotBlank()

    fun submit() {
        val text = field.text
        if (text.isBlank()) return
        if (awaitingInput) {
            onStdin(text)
        } else {
            onRun(text)
        }
        field = TextFieldValue("")
    }

    fun insertKey(key: String) {
        val start = field.selection.start.coerceIn(0, field.text.length)
        val end = field.selection.end.coerceIn(start, field.text.length)
        val updated = field.text.substring(0, start) + key + field.text.substring(end)
        field = TextFieldValue(updated, TextRange(start + key.length))
    }

    Column(modifier.fillMaxSize()) {
        Box(Modifier.weight(1f).fillMaxWidth()) {
            PersistentWebView(host, Modifier.fillMaxSize())
        }

        KeyStrip(keys = CONSOLE_KEYS, onKey = ::insertKey)

        Column(
            Modifier
                .fillMaxWidth()
                .background(MaterialTheme.colorScheme.surface)
                .padding(horizontal = 10.dp, vertical = 8.dp),
        ) {
            if (awaitingInput) {
                Text(
                    text = "Waiting for input()  -  type a line and send it",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.tertiary,
                    modifier = Modifier.padding(start = 4.dp, bottom = 4.dp),
                )
            }

            Row(verticalAlignment = Alignment.Bottom) {
                Box {
                    IconButton(
                        onClick = { historyOpen = true },
                        enabled = history.isNotEmpty(),
                    ) {
                        Icon(
                            Icons.Filled.History,
                            contentDescription = "Command history",
                            tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    DropdownMenu(
                        expanded = historyOpen,
                        onDismissRequest = { historyOpen = false },
                    ) {
                        history.take(20).forEach { entry ->
                            DropdownMenuItem(
                                text = {
                                    Text(
                                        entry.lineSequence().first().take(60),
                                        fontFamily = MonoFamily,
                                        style = MaterialTheme.typography.bodySmall,
                                        maxLines = 1,
                                    )
                                },
                                onClick = {
                                    field = TextFieldValue(entry, TextRange(entry.length))
                                    historyOpen = false
                                },
                            )
                        }
                    }
                }

                OutlinedTextField(
                    value = field,
                    onValueChange = { field = it },
                    modifier = Modifier
                        .weight(1f)
                        .heightIn(min = 52.dp, max = 160.dp),
                    placeholder = {
                        Text(
                            if (awaitingInput) "Your answer..." else "print('hello')",
                            fontFamily = MonoFamily,
                            style = MaterialTheme.typography.bodyMedium,
                        )
                    },
                    textStyle = MaterialTheme.typography.bodyMedium.copy(fontFamily = MonoFamily),
                    shape = RoundedCornerShape(12.dp),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = MaterialTheme.colorScheme.primary,
                        unfocusedBorderColor = MaterialTheme.colorScheme.outline,
                    ),
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
                    keyboardActions = KeyboardActions(onSend = { submit() }),
                    maxLines = 6,
                )

                Spacer(Modifier.width(6.dp))

                if (status.running && !awaitingInput) {
                    IconButton(onClick = onStop) {
                        Icon(
                            Icons.Filled.Stop,
                            contentDescription = "Stop",
                            tint = MaterialTheme.colorScheme.error,
                        )
                    }
                } else {
                    IconButton(onClick = ::submit, enabled = canSubmit && status.ready) {
                        Icon(
                            if (awaitingInput) Icons.Filled.ArrowUpward else Icons.Filled.PlayArrow,
                            contentDescription = if (awaitingInput) "Send input" else "Run",
                            tint = if (canSubmit && status.ready) {
                                MaterialTheme.colorScheme.primary
                            } else {
                                MaterialTheme.colorScheme.outline
                            },
                        )
                    }
                }
            }

            Row(
                Modifier.fillMaxWidth().padding(top = 4.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = when {
                        !status.ready -> "Starting interpreter..."
                        awaitingInput -> "stdin"
                        status.running -> "running"
                        else -> "ready"
                    },
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(start = 6.dp),
                )
                IconButton(onClick = onClear, modifier = Modifier.size(34.dp)) {
                    Icon(
                        Icons.Filled.Clear,
                        contentDescription = "Clear output",
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.size(17.dp),
                    )
                }
            }
        }
    }
}
