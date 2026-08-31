# Building with blocks

Creator is a tab where you build code by stacking blocks instead of typing it,
and then save what you built as a real file. Not a toy file: a `.py` the
Servers tab runs, an `.html` the Pages tab serves, a `.css` the editor opens.
Once it is saved there is nothing in it to say it came from blocks.

Turn it on in **More → Plugins → Creator**, and **Creator** appears in More.

---

## The two screens

**The bar** at the top holds the project's name and a language chooser. Five
to pick from, and the language decides which blocks exist:

| Language | Blocks | What it is for |
|---|---|---|
| Python | 154 | Runs in the app - everything the console can do |
| JavaScript | 98 | A page's behaviour, or a script on its own |
| HTML | 49 | The page itself |
| CSS | 42 | How the page looks |
| Markdown | 20 | Notes and documents |

Three hundred and sixty-three in all. **Switching language does not throw
anything away**: Creator keeps one script per language, so the chooser moves
between five drafts and your Python is still there when you come back.

**Your script** is the middle, and every row is **the line that block writes** -
real code, from the same compiler that writes the file - with the block's
plain-English name underneath it. A block that holds other blocks says so, its
contents sit inside a rail, and its closing line is greyed out below.

Tap a block to select it. A selected block grows a row of buttons:

| Button | What it does |
|---|---|
| Fill in | Its holes, one field each |
| Up / Down | Move it among its neighbours |
| Move inside | Put it inside the block above, if that block can hold things |
| Move out | Take it back out, to just after the block it was in |
| Duplicate | Another one just like it, underneath |
| Delete | Remove it |

**+ Add a block** at the bottom opens the second screen: everything you can
add, each row showing the line it would write. Filter by category, or search -
"print", "loop", "colour". It stays open while you tap, saying what went in and
how many blocks you have now, so several can go on in a row; **Done** takes you
back to the script, at the block you just added.

The line at the top of that screen always says where the next one will land,
and so does the line beside **Your script**:

- with nothing selected, **at the end** of the script;
- with a block selected, **after** it;
- with a **container** selected - a loop, an `if`, a `<div>`, a CSS rule - it
  goes **inside** it. That is the whole trick to building a loop: tap the loop
  in your script, then **+ Add a block** and pick what goes in it.

The first time you open Creator there is already an example script on screen,
labelled as one. Change it, or press **New** for an empty one.

---

## Filling in the holes

Most blocks have holes. `print text` has one; `repeat this many times` has two.
**Edit** opens them, one field each, with a sensible value already in it so a
block always writes something valid even if you never open it.

The kinds of hole, and what they do differently:

- **text** - written exactly as you type it. This is the escape hatch, and
  where an expression goes: `score + 1`, `items[0]`, `len(name)`.
- **a piece of text** - made safe for wherever it lands. Python and JavaScript
  get the quotes put round it and their escapes, so `he said "no"` cannot end
  the string early; HTML gets its entities, so a quote cannot end an attribute
  and `<b>` in a paragraph stays visible text; CSS loses braces, which cannot
  appear in a declaration and could only close the rule early.
- **text inside something quoted** - an f-string, a template literal. Escaped
  the same way, but not quoted again, and `{name}` and `${name}` are left alone
  because that is what those blocks are for.
- **number** - a number field. Left blank it is `0`.
- **name** - a variable, function or property name. Used as typed, so
  `data["k"]` works where a name is asked for.
- **choice** - a fixed list; you cannot type something that is not on it.

---

## Build, then save

**See the code** shows the whole file, before anything is saved. If a block is
in a language the project is not, it says so under the code rather than writing
something broken.

**Save as a file** asks for a file name and a folder inside your workspace, then
writes it. The Files tab refreshes, and the editor opens it unless you turn
that off in the plugin's settings. From there it is an ordinary file:

- a `.py` runs from the editor's Run button or `run thing.py` in the console;
- an `.html` and its `.css` are a page - put them in a folder and point the
  Pages tab at it;
- everything is editable by hand afterwards, and Creator does not mind.

Your projects are kept separately from the files they produce - **Saved** in
the bar is the drawer, up to sixty of them, and **Keep this one** puts the
script you are on into it. Saving a file does not delete the
blocks, and editing the file afterwards does not change them: they are two
things, and the file is the one that runs.

---

## From the console

```
blocks              # the projects in the drawer
blocks langs        # the languages, and how many blocks each has
blocks build hello  # print what a project writes
blocks save hello   # write it into the workspace
```

---

## What it will not do

**It cannot read a file back into blocks.** Blocks go one way. Reading source
back would mean a parser for each of the five languages, kept correct forever,
and the direction people actually want is this one - where the syntax errors
are.

**It does not check your expressions.** A `text` hole takes what you type and
puts it in the file. `score +` will be written out exactly like that and
Python will complain when you run it. The blocks get the *shape* right - the
colons, the braces, the indentation, the closing tags - which is the part that
is fiddly on a phone keyboard.

**It is not where the file lives.** The workspace is. Creator writes a file and
lets go of it.
