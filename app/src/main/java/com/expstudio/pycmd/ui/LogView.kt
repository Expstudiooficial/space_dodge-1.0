package com.expstudio.pycmd.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import com.expstudio.pycmd.util.stripAnsiCodes

/** One rendered log line. */
data class LogLine(val text: String, val color: Color)

/**
 * A scrollback view that follows the tail.
 *
 * Auto-scroll stops the moment the user scrolls up to read something, and
 * resumes once they return to the bottom — a log that yanks itself away
 * mid-read is worse than no log.
 */
@Composable
fun LogList(
    lines: List<LogLine>,
    modifier: Modifier = Modifier,
    contentPadding: PaddingValues = PaddingValues(horizontal = 12.dp, vertical = 10.dp),
) {
    val listState = rememberLazyListState()

    // True while the tail is on screen, i.e. the user has not scrolled up to
    // read something further back.
    val atBottom by remember(listState) {
        derivedStateOf {
            val last = listState.layoutInfo.visibleItemsInfo.lastOrNull()
            last == null || last.index >= listState.layoutInfo.totalItemsCount - 2
        }
    }

    LaunchedEffect(lines.size, atBottom) {
        if (atBottom && lines.isNotEmpty()) {
            listState.scrollToItem(lines.lastIndex)
        }
    }

    LazyColumn(
        state = listState,
        modifier = modifier.fillMaxSize(),
        contentPadding = contentPadding,
    ) {
        itemsIndexed(lines) { _, line ->
            Text(
                text = stripAnsiCodes(line.text).trimEnd('\n'),
                color = line.color,
                style = MaterialTheme.typography.bodySmall,
                fontFamily = MonoFamily,
                modifier = Modifier
                    .fillMaxWidth()
                    .horizontalScroll(rememberScrollState()),
                softWrap = false,
            )
        }
    }
}

/** Single-line input used by the server consoles. */
@Composable
fun ConsoleInputBar(
    placeholder: String,
    highlighted: Boolean,
    onSubmit: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    var value by remember { mutableStateOf("") }

    fun send() {
        if (value.isBlank()) return
        onSubmit(value)
        value = ""
    }

    Column(
        modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.surface)
            .padding(horizontal = 10.dp, vertical = 8.dp),
    ) {
        if (highlighted) {
            Text(
                "Waiting for input()",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.tertiary,
                modifier = Modifier.padding(start = 4.dp, bottom = 4.dp),
            )
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = value,
                onValueChange = { value = it },
                modifier = Modifier.weight(1f),
                placeholder = {
                    Text(placeholder, style = MaterialTheme.typography.bodySmall, fontFamily = MonoFamily)
                },
                singleLine = true,
                shape = RoundedCornerShape(12.dp),
                textStyle = MaterialTheme.typography.bodyMedium.copy(fontFamily = MonoFamily),
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = if (highlighted) {
                        MaterialTheme.colorScheme.tertiary
                    } else {
                        MaterialTheme.colorScheme.primary
                    },
                    unfocusedBorderColor = MaterialTheme.colorScheme.outline,
                ),
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
                keyboardActions = KeyboardActions(onSend = { send() }),
            )
            Spacer(Modifier.width(6.dp))
            IconButton(onClick = ::send, enabled = value.isNotBlank()) {
                Icon(
                    PyIcons.ArrowUpward,
                    contentDescription = "Send",
                    tint = if (value.isNotBlank()) {
                        MaterialTheme.colorScheme.primary
                    } else {
                        MaterialTheme.colorScheme.outline
                    },
                )
            }
        }
    }
}
