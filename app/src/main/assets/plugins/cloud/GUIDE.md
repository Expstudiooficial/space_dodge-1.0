# Using Cloud

Supabase and Firebase, from a script, a server, the console or the panel. This
is the short version; the whole API is in **Guides → The plugins that ship with
it**.

## 1. Connect a project

**More → Cloud**. Pick Supabase or Firebase at the top, fill in the fields, and
press **Save**, then **Test the connection**.

For **Supabase** you need two things from your project's API settings:

- the **project URL**, like `https://abcdefgh.supabase.co`
- the **anon public key** — the one meant to be shipped in a client

The **service key** is optional and only needed for the admin calls
(`sb.auth.admin_list_users()` and friends). It bypasses row-level security, so
leave it out unless you actually want those.

For **Firebase**:

- the **project id**
- the **web API key** from the project settings
- optionally the **Realtime Database URL** and the **storage bucket**

Keys are saved in the app's own storage, never in the workspace. Exporting or
sharing your files never carries them along.

## 2. Read and write from the console

```
sb select notes 5
sb insert notes {"text": "written from my phone"}
sb delete notes id=3
sb count notes

fb list notes 20
fb get notes/today
fb set notes/today {"text": "hello", "done": false}
fb query notes done == false
```

`cloud` on its own says what is connected.

## 3. The same thing from a script

```python
import pycmd_cloud

sb = pycmd_cloud.supabase()

# Chained filters, exactly like the official client.
rows = (sb.table("notes")
          .select("id,text,done")
          .eq("done", False)
          .order("id", ascending=False)
          .limit(10)
          .run())

for row in rows:
    print(row["text"])

sb.table("notes").insert({"text": "from a script"})
```

```python
fb = pycmd_cloud.firebase()

fb.firestore.set("notes/today", {"text": "hello", "done": False, "n": 7})
print(fb.firestore.get("notes/today"))
print(fb.firestore.query("notes", where=[("done", "==", False)], limit=5))

fb.rtdb.push("rooms/lobby", {"joined": "me"})
```

## 4. Signing a user in

Signing in from the panel, the console or a script all set the *same* session,
so a server you start afterwards is already that user:

```python
pycmd_cloud.supabase().auth.sign_in("someone@example.com", "their password")
```

That is what makes "the server verifies the user" work: sign in, then every
later call carries their token instead of the anon key.

## 5. Files

```
sb up media notes/report.pdf        # workspace file -> bucket
sb down media report.pdf            # bucket -> workspace
fb up photo.png
```

Or from the **Files** tab: any file's ⋮ menu has **Upload to cloud storage**,
and a folder's has **Upload every file in it**. Both use the default bucket
from this plugin's **Settings**, which is in the plugin list.

## What is not here

Realtime subscriptions — Supabase's realtime channels and Firestore listeners.
Both are WebSocket protocols, `urllib` does not speak WebSocket, and a fake
built out of polling would be a worse thing to have than an honest gap. Poll
the read calls yourself if you need to; they are cheap.
