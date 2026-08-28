package com.expstudio.pycmd.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.unit.dp

/** Single-field prompt used for names, ports and package versions. */
@Composable
fun TextPromptDialog(
    title: String,
    label: String,
    initial: String,
    confirmLabel: String,
    onDismiss: () -> Unit,
    onConfirm: (String) -> Unit,
    supportingText: String? = null,
    keyboardOptions: KeyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
) {
    // Selecting the stem (not the extension) is what a rename dialog should do.
    var value by remember {
        val selectionEnd = initial.substringBeforeLast('.', initial).length
        mutableStateOf(TextFieldValue(initial, TextRange(0, selectionEnd)))
    }
    val focusRequester = remember { FocusRequester() }

    LaunchedEffect(Unit) { focusRequester.requestFocus() }

    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = MaterialTheme.colorScheme.surface,
        shape = RoundedCornerShape(18.dp),
        title = { Text(title, style = MaterialTheme.typography.titleMedium) },
        text = {
            Column {
                OutlinedTextField(
                    value = value,
                    onValueChange = { value = it },
                    label = { Text(label) },
                    singleLine = true,
                    shape = RoundedCornerShape(12.dp),
                    textStyle = MaterialTheme.typography.bodyMedium.copy(fontFamily = MonoFamily),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = MaterialTheme.colorScheme.primary,
                        unfocusedBorderColor = MaterialTheme.colorScheme.outline,
                    ),
                    keyboardOptions = keyboardOptions,
                    keyboardActions = KeyboardActions(
                        onDone = { onConfirm(value.text) },
                        onGo = { onConfirm(value.text) },
                    ),
                    modifier = Modifier.fillMaxWidth().focusRequester(focusRequester),
                )
                if (supportingText != null) {
                    Spacer(Modifier.height(8.dp))
                    Text(
                        supportingText,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        },
        confirmButton = {
            TextButton(
                onClick = { onConfirm(value.text) },
                enabled = value.text.isNotBlank(),
            ) {
                Text(confirmLabel)
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Cancel") }
        },
    )
}

/** Yes/no dialog; [destructive] paints the confirm action red. */
@Composable
fun ConfirmDialog(
    title: String,
    message: String,
    confirmLabel: String,
    onDismiss: () -> Unit,
    onConfirm: () -> Unit,
    destructive: Boolean = false,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = MaterialTheme.colorScheme.surface,
        shape = RoundedCornerShape(18.dp),
        title = { Text(title, style = MaterialTheme.typography.titleMedium) },
        text = {
            Text(
                message,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        },
        confirmButton = {
            TextButton(onClick = onConfirm) {
                Text(
                    confirmLabel,
                    color = if (destructive) {
                        MaterialTheme.colorScheme.error
                    } else {
                        MaterialTheme.colorScheme.primary
                    },
                )
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Cancel") }
        },
    )
}

/**
 * A dialog whose body is a scrolling list of things to pick.
 *
 * The message dialogs above cover yes/no and one text field; a picker needs
 * arbitrary rows, and a long list has to scroll rather than push its buttons
 * off the screen.
 */
@Composable
fun ListDialog(
    title: String,
    onDismiss: () -> Unit,
    content: @Composable ColumnScope.() -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = MaterialTheme.colorScheme.surface,
        shape = RoundedCornerShape(18.dp),
        title = { Text(title, style = MaterialTheme.typography.titleMedium) },
        text = {
            Column(
                Modifier
                    .fillMaxWidth()
                    .heightIn(max = 380.dp)
                    .verticalScroll(rememberScrollState()),
                content = content,
            )
        },
        confirmButton = {
            TextButton(onClick = onDismiss) { Text("Close") }
        },
    )
}

/**
 * The name is already taken: replace it, keep both, or stop.
 *
 * A dialog rather than a rule, because neither answer is right in general.
 * Silently keeping both is what the app used to do, and it meant an updated
 * file arrived as a second copy while every script went on reading the old
 * one - a bug you only notice much later, by which time you are debugging the
 * wrong file.
 */
@Composable
fun ImportCollisionDialog(
    name: String,
    isFolder: Boolean,
    existingSummary: String,
    onReplace: () -> Unit,
    onKeepBoth: () -> Unit,
    onCancel: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onCancel,
        containerColor = MaterialTheme.colorScheme.surface,
        shape = RoundedCornerShape(18.dp),
        title = {
            Text(
                if (isFolder) "That folder is already here" else "That file is already here",
                style = MaterialTheme.typography.titleMedium,
            )
        },
        text = {
            Column {
                Text(
                    name,
                    style = MaterialTheme.typography.bodyMedium,
                    fontFamily = MonoFamily,
                )
                Spacer(Modifier.height(4.dp))
                Text(
                    existingSummary,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(12.dp))
                Text(
                    if (isFolder) {
                        "Replacing removes what is there first, so nothing of the old " +
                            "copy is left mixed in with the new one."
                    } else {
                        "Keeping both leaves the old file exactly where it is, under " +
                            "its own name."
                    },
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        },
        confirmButton = {
            TextButton(onClick = onReplace) {
                Text("Replace", color = MaterialTheme.colorScheme.error)
            }
        },
        dismissButton = {
            Row {
                TextButton(onClick = onCancel) {
                    Text("Cancel", color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                TextButton(onClick = onKeepBoth) {
                    Text("Keep both", color = MaterialTheme.colorScheme.primary)
                }
            }
        },
    )
}
