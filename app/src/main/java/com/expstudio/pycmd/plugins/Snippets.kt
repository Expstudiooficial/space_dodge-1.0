package com.expstudio.pycmd.plugins

/**
 * The snippet library behind the Snippets plugin.
 *
 * Typing a for-loop header on a phone keyboard costs about fifteen taps, four
 * of which are on characters hidden behind a modifier key. That is the whole
 * argument for this file: the snippets are the lines nobody should have to
 * type twice, chosen per language so the bar is never showing Python to
 * someone editing CSS.
 *
 * `|` marks where the caret should land after insertion.
 */
data class Snippet(val label: String, val body: String)

object Snippets {

    private val PYTHON = listOf(
        Snippet("main", "def main() -> None:\n    |\n\n\nif __name__ == \"__main__\":\n    main()\n"),
        Snippet("def", "def |():\n    pass\n"),
        Snippet("for", "for item in |:\n    pass\n"),
        Snippet("while", "while |:\n    pass\n"),
        Snippet("if", "if |:\n    pass\n"),
        Snippet("try", "try:\n    |\nexcept Exception as error:\n    print(error)\n"),
        Snippet("class", "class |:\n    def __init__(self):\n        pass\n"),
        Snippet("with", "with open(\"|\") as handle:\n    data = handle.read()\n"),
        Snippet("print", "print(|)"),
        Snippet("input", "value = input(\"| \")"),
    )

    private val PYTHON_MORE = listOf(
        Snippet("http server", "import http.server\nimport socketserver\n\n" +
            "PORT = 8000\nwith socketserver.TCPServer((\"\", PORT), " +
            "http.server.SimpleHTTPRequestHandler) as httpd:\n    print(\"serving on\", PORT)\n" +
            "    httpd.serve_forever()\n"),
        Snippet("read json", "import json\n\nwith open(\"|\") as handle:\n" +
            "    data = json.load(handle)\n"),
        Snippet("argparse", "import argparse\n\nparser = argparse.ArgumentParser()\n" +
            "parser.add_argument(\"|\")\nargs = parser.parse_args()\n"),
        Snippet("dataclass", "from dataclasses import dataclass\n\n\n@dataclass\nclass |:\n" +
            "    name: str\n    value: int = 0\n"),
        Snippet("comprehension", "[| for item in items]"),
        Snippet("f-string", "f\"{|}\""),
        Snippet("enumerate", "for index, item in enumerate(|):\n    pass\n"),
        Snippet("sort by", "items.sort(key=lambda item: |)"),
        Snippet("counter", "from collections import Counter\n\ncounts = Counter(|)\n"),
        Snippet("sleep", "import time\n\ntime.sleep(|)\n"),
    )

    private val JAVASCRIPT = listOf(
        Snippet("log", "console.log(|);"),
        Snippet("function", "function |() {\n  \n}\n"),
        Snippet("arrow", "const | = () => {\n  \n};\n"),
        Snippet("for", "for (let i = 0; i < |; i++) {\n  \n}\n"),
        Snippet("for of", "for (const item of |) {\n  \n}\n"),
        Snippet("if", "if (|) {\n  \n}\n"),
        Snippet("async", "async function |() {\n  \n}\n"),
        Snippet("await input", "const answer = await readLine(\"| \");"),
        Snippet("map", "const result = items.map((item) => |);"),
        Snippet("try", "try {\n  |\n} catch (error) {\n  console.error(error);\n}\n"),
    )

    private val JAVASCRIPT_MORE = listOf(
        Snippet("fetch", "const response = await fetch(\"|\");\nconst data = await response.json();\n"),
        Snippet("class", "class | {\n  constructor() {\n  }\n}\n"),
        Snippet("reduce", "const total = items.reduce((sum, item) => sum + item, 0);"),
        Snippet("filter", "const kept = items.filter((item) => |);"),
        Snippet("timeout", "setTimeout(() => {\n  |\n}, 1000);\n"),
        Snippet("promise", "await new Promise((resolve) => setTimeout(resolve, |));"),
        Snippet("destructure", "const { | } = object;"),
        Snippet("template", "`\${|}`"),
    )

    private val HTML = listOf(
        Snippet("page", "<!doctype html>\n<html>\n<head>\n  <meta charset=\"utf-8\">\n" +
            "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n" +
            "  <title>|</title>\n</head>\n<body>\n  \n</body>\n</html>\n"),
        Snippet("div", "<div class=\"|\"></div>"),
        Snippet("link css", "<link rel=\"stylesheet\" href=\"|\">"),
        Snippet("script", "<script src=\"|\"></script>"),
        Snippet("form", "<form>\n  <input name=\"|\">\n  <button>Send</button>\n</form>\n"),
        Snippet("list", "<ul>\n  <li>|</li>\n</ul>\n"),
        Snippet("img", "<img src=\"|\" alt=\"\">"),
        Snippet("table", "<table>\n  <tr><th>|</th></tr>\n  <tr><td></td></tr>\n</table>\n"),
    )

    private val CSS = listOf(
        Snippet("reset", "* {\n  box-sizing: border-box;\n  margin: 0;\n  padding: 0;\n}\n"),
        Snippet("flex", "display: flex;\nalign-items: center;\njustify-content: |;\n"),
        Snippet("grid", "display: grid;\ngrid-template-columns: repeat(|, 1fr);\ngap: 12px;\n"),
        Snippet("rule", "| {\n  \n}\n"),
        Snippet("media", "@media (max-width: 600px) {\n  |\n}\n"),
        Snippet("variables", ":root {\n  --accent: #|;\n}\n"),
        Snippet("transition", "transition: | 0.2s ease;"),
        Snippet("dark", "@media (prefers-color-scheme: dark) {\n  |\n}\n"),
    )

    private val C = listOf(
        Snippet("main", "#include <stdio.h>\n\nint main(void) {\n    |\n    return 0;\n}\n"),
        Snippet("printf", "printf(\"|\\n\");"),
        Snippet("for", "for (int i = 0; i < |; i++) {\n    \n}\n"),
        Snippet("while", "while (|) {\n    \n}\n"),
        Snippet("if", "if (|) {\n    \n}\n"),
        Snippet("struct", "struct | {\n    int value;\n};\n"),
        Snippet("malloc", "int *values = malloc(| * sizeof(int));"),
        Snippet("scanf", "int value;\nscanf(\"%d\", &value);\n"),
    )

    private val GO = listOf(
        Snippet("main", "package main\n\nimport \"fmt\"\n\nfunc main() {\n\t|\n}\n"),
        Snippet("print", "fmt.Println(|)"),
        Snippet("printf", "fmt.Printf(\"%v\\n\", |)"),
        Snippet("func", "func |() {\n\t\n}\n"),
        Snippet("for", "for i := 0; i < |; i++ {\n\t\n}\n"),
        Snippet("range", "for i, item := range | {\n\t\n}\n"),
        Snippet("if err", "if err != nil {\n\tfmt.Println(err)\n\treturn\n}\n"),
        Snippet("struct", "type | struct {\n\tName string\n}\n"),
        Snippet("goroutine", "go func() {\n\t|\n}()\n"),
        Snippet("channel", "ch := make(chan |, 1)"),
    )

    private val RUST = listOf(
        Snippet("main", "fn main() {\n    |\n}\n"),
        Snippet("print", "println!(\"{}\", |);"),
        Snippet("debug", "println!(\"{:?}\", |);"),
        Snippet("fn", "fn |() {\n    \n}\n"),
        Snippet("for", "for item in | {\n    \n}\n"),
        Snippet("match", "match | {\n    Some(value) => {},\n    None => {},\n}\n"),
        Snippet("struct", "struct | {\n    name: String,\n}\n"),
        Snippet("impl", "impl | {\n    fn new() -> Self {\n        \n    }\n}\n"),
        Snippet("vec", "let mut items: Vec<|> = Vec::new();"),
        Snippet("if let", "if let Some(value) = | {\n    \n}\n"),
    )

    private val MARKDOWN = listOf(
        Snippet("title", "# |\n"),
        Snippet("section", "## |\n"),
        Snippet("list", "- |\n- \n"),
        Snippet("code", "```\n|\n```\n"),
        Snippet("link", "[|](https://)"),
        Snippet("table", "| name | value |\n| --- | --- |\n| | |\n"),
        Snippet("quote", "> |"),
    )

    private val SHELL = listOf(
        Snippet("shebang", "#!/bin/sh\n|"),
        Snippet("for", "for file in *; do\n  |\ndone\n"),
        Snippet("if", "if [ | ]; then\n  \nfi\n"),
        Snippet("echo", "echo \"|\""),
    )

    private val JSON = listOf(
        Snippet("object", "{\n  \"|\": \"\"\n}\n"),
        Snippet("array", "[\n  |\n]\n"),
        Snippet("package", "{\n  \"name\": \"|\",\n  \"version\": \"1.0.0\"\n}\n"),
    )

    private val GENERIC = listOf(
        Snippet("date", "TODO |"),
        Snippet("note", "NOTE: |"),
    )

    private val BASE: Map<String, List<Snippet>> = mapOf(
        "python" to PYTHON,
        "javascript" to JAVASCRIPT,
        "typescript" to JAVASCRIPT,
        "html" to HTML,
        "css" to CSS,
        "c" to C,
        "cpp" to C,
        "go" to GO,
        "rust" to RUST,
        "markdown" to MARKDOWN,
        "shell" to SHELL,
        "json" to JSON,
    )

    private val EXTRA: Map<String, List<Snippet>> = mapOf(
        "python" to PYTHON_MORE,
        "javascript" to JAVASCRIPT_MORE,
        "typescript" to JAVASCRIPT_MORE,
    )

    /**
     * The snippets for one language.
     *
     * [powered] is Power Pack: it adds the longer starters - a whole HTTP
     * server, a fetch call, a dataclass - rather than a different set, so the
     * bar someone already knows does not rearrange itself.
     */
    fun forLanguage(languageId: String, powered: Boolean): List<Snippet> {
        val base = BASE[languageId] ?: GENERIC
        if (!powered) return base
        return base + (EXTRA[languageId] ?: emptyList())
    }

    /** Where the caret marker sits, and the text with the marker removed. */
    fun split(body: String): Pair<String, Int> {
        val caret = body.indexOf('|')
        if (caret < 0) return body to body.length
        return body.removeRange(caret, caret + 1) to caret
    }
}
