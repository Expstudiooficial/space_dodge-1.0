"""A one-file PyCmd plugin: adds a `greet` command to the console.

Install it from Plugins -> Install a plugin -> From the workspace.
See PLUGINS.md (Plugins -> How do I write one?) for the full guide.
"""

PLUGIN = {
    "id": "demo.greet",
    "name": "Greet",
    "version": "1.0.0",
    "author": "PyCmd",
    "description": "A console command that says hello, and a count of how many "
                   "times you have run it.",
    "commands": [{"name": "greet", "help": "greet <name> - say hello"}],
}


def setup(api):
    @api.command("greet", help="greet <name>")
    def greet(argument):
        who = argument.strip() or "world"
        state = api.store()
        state["count"] = state.get("count", 0) + 1
        api.store(state)
        api.print(f"hello, {who}  (greeting number {state['count']})")

    @api.on("file_saved")
    def saved(event):
        api.log("you saved", event.get("name", ""))
