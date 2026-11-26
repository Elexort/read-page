# MCP frontend (`scripts/mcp_server.py`)

Same core, two tools. Reason: an agent without a shell cannot run `readpage.py`, but it can call a
tool. No second implementation of the logic: each `read_url` runs `readpage.py` in a child process
with an argv list (plus `--json`) and reads the manifest it prints - four calls at once, each with
its own stdout. **No second copy of the limits either**: the
answer budget lives in `scripts/answer.py`, the download cap and the timeouts in `readpage.py`, and
both frontends import them, so a CLI run and an MCP call cannot disagree.

Run: `python -X utf8 scripts/mcp_server.py` - stdio JSON-RPC, protocol `2025-06-18`, **stdlib only**
(no MCP SDK needed). After `readpage.py --setup` the server runs under the skill's own environment
by itself, whatever Python the client starts it with, and so does every read it starts. Validated by `tests/mcp_smoke.py` (protocol level), `tests/contract.py` (the
answer) and `tests/mcp_sdk_client.py` (official Python SDK).

## Scope of `read`

`read(dir, ...)` accepts only a folder this skill wrote: an entry under
`<temp>/read-page/pages/`, or a folder produced with `--dir` that contains our `manifest.json`
(`generator: read-page`). Any other path - `C:\Windows`, a home directory - is refused with a clear
error, so a prompt-injected model cannot turn the tool into a general file reader.

## Tools

```
read_url(url, allow_external?, force_external?, alternate?, download?, deny_images?,
         screenshots?, inline_images?, refresh?, clear_cookies?, file?, from?)
read(dir, file?, from=1)
```

Arguments are the CLI flags without dashes: `--allow-external` -> `allow_external`, `--from` ->
`from`, and so on; `inline_images` is the one argument the CLI does not have. An argument outside
the schema, or a value a tool cannot use (`from: "abc"`), does not refuse the call: it is left out
and the answer's `ignored:` line names it - an old `offset`, `limit` or `allow_images` among them -
as the CLI does with a flag that is not its own. A misspelled argument (`allow_externl`) is the one
meant. `read_url(..., ocr=N)` answers with the text drawn in picture N, as `--ocr N` does, and
`read(dir, file="img/...", ocr=true)` with a picture's text instead of the picture.

`read_url` answers with the text the CLI prints - a header, then the text whole, or an outline,
the first block and the next line. Only the pointer differs, since there is no command to repeat:

```
read-page · ok · defuddle · content.md 24.7 KB, 389 lines · 1.9 s
files: C:\Users\me\AppData\Local\Temp\read-page\pages\9c1f… (content.md, page.md, manifest.json)
outline (line, heading):
      1 ## Installation
      …
── content.md: lines 1-126 of 389 ──
(the text)
── next: line 127 of 389 → read(dir, file="content.md", from=127) ──
```

`dir` is the folder on the `files:` line. `read_url(url, from=127)` gives the same block, also from
the saved copy, with no network. A call that names no `file` goes on in the text read last
(a named one becomes the text being read; `read_url` without `from` starts at `content.md`, or
`page.md` for a fragment), so a model that drops `file` still reads the same text under the
same line numbers. The full manifest is in `structuredContent` and in
`dir/manifest.json`; `structuredContent.mcp` adds `file`, `from`, `next_from`, `total_lines` and
the picture counts.

`read` behaves by file type:

| File | Result |
|---|---|
| text (`content.md`, `page.md`, `manifest.json`, `raw.html`) | the block that starts at line `from`, inside the same budget, naming the next line. A line longer than a whole answer (a minified `raw.html`) shows its head and says so |
| image (`img/03-alt.png`, `raw.jpg`) | a native `image` block and a caption `[WxH size] name` |
| audio / video / other binary | metadata only (name, type, size); audio is attached only with `READ_PAGE_MCP_MEDIA=audio` |

## The header

Custom text, not JSON, so it survives any client and costs a few dozen tokens. The first line says
the status, the engine and how much of the visible page its text holds (`cover`), the archive date
for a Wayback copy, which file and how big, `from cache`, `fragment` and the seconds taken. Then,
when there is something to say: `url:` (where a redirect ended), `reason:` (the rule behind any
status but `ok`), `files:`, `advice:`, and at most two `missing:`/`improve:` lines - also on a cache
hit (hiding them there made "why this answer is poor" invisible).

## Images

The text's pictures are downloaded by default and stand in it as numbered markers,
`[img #3 · 100x80 3K · alt] img/03-alt.png` (the number is the file's; SKILL.md, Pictures).
`deny_images=true` keeps the text and downloads nothing - the marker says
`not downloaded` and keeps the address. `inline_images=true` turns every marker that stands on a
line of its own into a real `image` block right after it, in reading order:

```
text block -> [img #3 · 100x80 3K · alt] img/03-alt.png -> image block -> next text block
```

The caption always stays, so a client that renders nothing still gets the paths. Without
`inline_images` only captions are returned. A URL that serves a single image (`status=media_only`)
comes back as that image immediately - one hop, no `read` call. A picture URL that points at a
private host is never fetched; `signals.images_private_skipped` counts them.

## Limits

Only the limits someone enforces, the worst adequate case among clients with a 1M
context; three groups, the first one reached cuts:

| Limit | Value | Who enforces it |
|---|---|---|
| the text | 7 900 characters, 9 980 bytes and 495 lines, as on the CLI | Cline (8 000 characters a tool result, MCP too), Codex, Roo Code (`answer.py`) |
| one picture | PNG or JPEG; a long side over 1 568 px is scaled down, proportions kept; at most 3.75 MB, a heavier PNG becomes one JPEG at q95 | xAI takes only PNG and JPEG; Claude on Bedrock 5 MB of base64; 8 000 px, and ~2 000 px when a request has more than 20 pictures |
| the whole answer | 25 000 tokens: the text plus `ceil(w/28)*ceil(h/28)` and ~150 for the path line a picture costs | Claude Code (measured: going over keeps the pictures but tells the model "OUTPUT TRUNCATED") |
| | 256 pictures | Qwen 3.6-plus, for the whole request |
| | 20 MB | Gemini, the whole request with its text |

Only the content pictures go in: not a decoration (the same picture 3+ times in the text, 48 px or
less, 1 KB or less) and not a logo, icon, avatar or badge of 100 px or less, by its name, `alt`
or address. Screenshots asked for go first, then the biggest pictures; each stands right after its
marker. A picture that did not fit keeps its marker, and a note counts it (`images_skipped`,
`structuredContent.mcp.tokens` is the estimate). Converting needs Pillow (GIF, WebP, AVIF, BMP,
scaling) and PyMuPDF (SVG); without them only a PNG or JPEG that already fits goes in, the rest
stays a marker - the setup report names both. Text is never cut for pictures.

## Degradation

An `image` block is the only media type most hosts render. `audio` is rarely shown, a `resource`
blob is usually undecodable, `resource_link` is not rendered at all and video has no block type -
so images go as blocks, everything else as text with a path.

## Protocol notes

- `initialize` answers with the server's own version (`2025-06-18`). A client that offered an older
  version is not downgraded; the spec allows answering with a supported version, but such a client
  will usually disconnect. One protocol era only.
- A JSON-RPC batch (a top-level array) is not part of 2025-06-18; it is answered with `-32600`
  instead of crashing the loop (0.4.0 fixed a client hang here).
- Calls at once: every `read_url` runs `readpage.py` in a child process, at most four at a
  time, and its answer goes out whole on one line under a lock; two calls for the same page do not
  write one folder at once (the second waits and gets the cached answer). Threads in one process
  were not an option: `redirect_stdout` is global and caught another call's manifest.
- `notifications/cancelled` kills that call's process tree (the browser and curl it started too)
  and the call gets no answer, as the spec asks; a call still waiting for a slot never starts.
  Every read ends by its 55 s deadline anyway (see `references/engines.md`), under the ~60 s at
  which harnesses cancel a call. The server's backstop (`HARD_SECONDS`, 58 s; none with
  `download`) kills a read still running then and says so; if that read had already printed its
  answer and only its exit hung, the answer is what the call gets.
- A file on this machine: `read_url` takes a path or a `file://` URL only inside
  read-page's own folders (a page folder of its cache, or a folder with its manifest), checked after
  links are resolved; anything else is refused with a pointer to the CLI, which reads any path. So a
  prompt-injected model cannot read a home folder through the server.
- A warm process for the next call: the server keeps one `readpage.py --serve-once`
  with Python started and the imports done (about 0.5 s of a call on a fast machine, 2 s on a weak laptop). A
  call takes it and a new one starts; each serves one call and exits, so nothing of one read
  reaches the next. It ends with the server.

## Client config

```json
{"mcpServers": {"read-page": {
  "command": "python",
  "args": ["-X", "utf8", "/home/me/.agents/skills/read-page/scripts/mcp_server.py"]
}}}
```

The server reads and writes UTF-8 whatever the machine's code page is: it reconfigures its own standard
input and output at the start, so a client config without `-X utf8` (a Chinese Windows, code page 936) still
delivers `https://例子.测试/页面` and a folder under `C:\Users\张三` intact, and a UTF-8 BOM before the first line
(a file saved with one, piped in) is dropped: the first message was a parse error. The flag stays in the
example: it makes the children and everything else UTF-8 too.

## Why not a third tool

`search`, `screenshot`, `click` belong to a browser-automation tool, not to a reader, and the
privacy model here does not cover them. `show`/`explain` are backlog: attach metadata first, then
try a blob; transcription needs `--allow-external` on that very call.
