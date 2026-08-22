"""Terminal colour and formatting, straight from Python.

rich is built into PyCmd. The console renders its ANSI colour codes
properly - tables, progress bars, styled text all show up the way they
would in a real terminal.
"""

import time

from rich.console import Console
from rich.table import Table
from rich.progress import track

console = Console()

console.print("\n[bold cyan]PyCmd[/bold cyan] running on your phone\n")

table = Table(title="Device Python")
table.add_column("Property", style="cyan")
table.add_column("Value", style="green")
table.add_row("Interpreter", "CPython 3.13")
table.add_row("Runs on", "arm64-v8a / x86_64")
table.add_row("Style", "[italic]this table[/italic]")
console.print(table)

console.print()
for _ in track(range(20), description="Working..."):
    time.sleep(0.05)

console.print("\n[bold green]Done.[/bold green] All of that ran on the device.")
