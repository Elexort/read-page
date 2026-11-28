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
         screenshots?, inline_images?, refresh?, clear_cookies?, file?, from?, chars?, probe?, probe_units?)
read(dir, file?, from=1, chars?)
```

Arguments are the CLI flags without dashes: `--allow-external` -> `allow_external`, `--from` ->
`from`, and so on; `inline_images` is the one argument the CLI does not have. An argument outside
the schema, or a value a tool cannot use (`from: -3`), does not refuse the call: it is left out
and the answer's `ignored:` line names it - an old `offset`, `limit` or `allow_images` among them -
as the CLI does with a flag that is not its own. A misspelled argument (`allow_externl`) is the one
meant. `read_url(..., ocr=N)` answers with the text drawn in picture N, as `--ocr N` does, and
`read(dir, file="img/...", ocr=true)` with a picture's text instead of the picture.

`read_url` answers with the text the CLI prints - a header, then the text whole, or an outline,
the first block and the call that goes on. Only the line under `next:` differs: the read call, not a command:

```
read-page · ok · defuddle · content.md 24.7 KB, 389 lines · 1.9 s
files: C:\Users\me\AppData\Local\Temp\read-page\pages\example.com-9c1f… (content.md, page.md, manifest.json)
outline (line, heading):
      1 ## Installation
      …
── content.md: from line 1 of 389 ──
(the text)
── next: line 127 of 389 ──
read(dir="C:/Users/me/AppData/Local/Temp/read-page/pages/example.com-9c1f…", file="content.md", from=127, chars=7900)
```

The call names its folder, in forward slashes on Windows (a client's JSON takes them unescaped), and the size the
answer was asked with; the last block ends with `── EOF content.md: lines 352-389 of 389 ──`, as on the CLI.
`dir` is the folder on the `files:` line. `read_url(url, from=127)` gives the same block, also from
the saved copy, with no network. A call that names no `file` goes on in the text read last
(a named one becomes the text being read; `read_url` without `from` starts at `content.md`, or
`page.md` for a fragment), so a model that drops `file` still reads the same text under the
same line numbers. A result is its blocks and `isError`, nothing else: no `structuredContent` (the tools declare
no `outputSchema`, so the protocol asks for none). The manifest is the folder's file, `read(dir,
file="manifest.json")`; the header says what a model needs of it - the status, the folder, the advice, the next line
(see How a client counts a result).

`from` takes a piece of text as well as a line number (both tools, as the CLI's `--from "text"`): the
answer starts at the first line that holds it - whitespace folded, then without case; when several do,
the first at or after where the last answer of that file started - and a marker is found by its type
and name, a picture by its number: `from="[tab · Developer Plan Limits]"`, `from="[img #3]"`; the line is
matched as it stands too, so a quote that ends inside a marker (a client cut the result there) is found. No line
holds it: the answer says so and shows the outline, and names no next line.

`chars` (both tools) is the CLI's `--chars`: how much one answer holds, in characters, whole lines - 7 900 by
default, which fits every client; 7 000 to 150 000, a value outside or not a number named on the `ignored:` line with
what was used. The result as Cline counts it, its JSON (see How a client counts a result), stays within it, and the
next line carries it on. `to`, a range in lines until 2026-11-27, is gone: left out and named, `to 120 (gone: chars
sets the size)`, and the call goes on.

`read` behaves by file type:

| File | Result |
|---|---|
| text (`content.md`, `page.md`, `manifest.json`, `raw.html`) | the block that starts at line `from`, inside the same budget, naming the next line; the pictures of a `content.md` or `page.md` block are downloaded first, as a CLI continuation's are (a child `readpage.py` reads on from the folder; none for a page whose pictures were denied, KNOWN-ISSUES 296). A line longer than a whole answer (a minified `raw.html`) shows its head and says so |
| image (`img/03-alt.png`, `raw.jpg`) | a native `image` block and a caption `[WxH size] name` |
| audio / video / other binary | metadata only (name, type, size); audio is attached only with `READ_PAGE_MCP_MEDIA=audio` |

## A probe, for testing a client

`read_url(url="probe", probe=N)` answers with N characters of numbered lines and nothing else, as
`readpage.py --probe N` prints them, with no network - each line its number and how many characters stand
before it, a head and a tail sentinel, ASCII - so what a client shows of a tool's result, and where it cut,
can be read off what reaches the model (Cline's SDK runtime keeps about 3 985 characters at each end of
8 000). `read_url(url="probe:N")` is a page of the same lines answered the normal way, and with `from` and
`chars` it shows what an answer of that size sends. It is for testing the skill, not for reading; SKILL.md does not name it.

`read_url(url="probe", probe_units=N)` is the probe that tells the units apart (`readpage.py --probe-units N`): the
same N characters in lines of 100, but each line's label says its number and how many characters, UTF-16 units and
bytes stand before it (`line 12 | 1100 chars 1190 utf16 1830 bytes before`), and its filler is ASCII, Cyrillic (2
bytes), CJK (3 bytes) or a character past U+FFFF (2 units, 4 bytes) by the line's number (1, 2, 3, 4, then again), so
the three counts drift apart line by line. Take the last line the client shows and where it cut that line: the label
plus what the shown part adds are the three counts at the cut, and the one that comes to the client's limit is the one
it counts: Cline's SDK counts UTF-16 units and keeps about 3 985 of them at each end, so the label of the last line
before its gap says about 3 985 utf16, whatever it says of characters and bytes. The ASCII probe cannot tell them apart.

`READ_PAGE_TEST_CUT` (in the server's environment) cuts a result's text the way a client would - `middle:8000` as Cline,
`head:N`, `tail:N`, `file:N` - its text blocks joined into one: for teaching a model to go on under a cut
([answer.md](answer.md#for-testing-the-skill)). The probes are never cut.

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
| the text | 7 900 characters, 9 980 bytes and 495 lines, as on the CLI - the blocks of one result together, as Cline counts them: their JSON, with the notes after the text and `[image attached]` for each image | Cline (8 000 characters a tool result, MCP too), Codex, Roo Code (`answer.py`) |
| one picture | PNG or JPEG; a long side over 1 568 px is scaled down, proportions kept; at most 3.75 MB, a heavier PNG becomes one JPEG at q95 | xAI takes only PNG and JPEG; Claude on Bedrock 5 MB of base64; 8 000 px, and ~2 000 px when a request has more than 20 pictures |
| the whole answer | 25 000 tokens: the text plus `ceil(w/28)*ceil(h/28)` and ~150 for the path line a picture costs | Claude Code (measured: going over keeps the pictures but tells the model "OUTPUT TRUNCATED") |
| | 256 pictures | Qwen 3.6-plus, for the whole request |
| | 20 MB | Gemini, the whole request with its text |

Only the content pictures go in: not a decoration (the same picture 3+ times in the text, 48 px or
less, 1 KB or less) and not a logo, icon, avatar or badge of 100 px or less, by its name, `alt`
or address. Screenshots asked for go first, then the biggest pictures; each stands right after its
marker. A picture that did not fit keeps its marker, and a note counts it. Converting needs Pillow (GIF, WebP, AVIF,
BMP, scaling) and PyMuPDF (SVG); without them only a PNG or JPEG that already fits goes in, the rest
stays a marker - the setup report names both. The text gives up the room the pictures, the notes and JSON take: the
server counts the blocks of one result together as Cline's SDK counts them - the result's JSON, so the escapes of the
text too (a line's `\n` is two characters, a quote two), and for each image block the `[image attached]` that Cline
puts in its place - and when they would pass the three limits of the text, the text is rendered again inside what
is left (a block ends at a paragraph, so it loses a paragraph at most more than it must); `read`'s blocks the same.
The pointer to the next line names where the shorter block ends. A range (`to`) and a quote that no line holds are
not shortened.

## How a client counts a result

What a client gives the model of a tool's result decides what must fit, so the clients' code was read (2026-11-27):

- **Cline's SDK runtime** - its CLI, and the VS Code windows on that bundle (cline/cline cbc7d14): an MCP tool
  returns the result object as the server sent it (`sdk/packages/core/src/extensions/mcp/tools.ts:29-46`,
  `extensions/mcp/client.ts:929-946`; the VS Code bundle's `apps/vscode/src/services/mcp/McpHub.ts:1721-1741` the
  same), the runtime keeps it as the call's output (`sdk/packages/agents/src/agent-runtime.ts:2601-2621`,
  `2676-2682`), and the message to the model takes `toPersistedToolResultContent(output)`
  (`sdk/packages/core/src/runtime/config/agent-message-codec.ts:296-302`), which makes an object its JSON,
  `JSON.stringify(output)` with no spaces (`sdk/packages/core/src/session/persisted-tool-result-content.ts:9-24`).
  That string is measured in UTF-16 units against 8 000 (`DEFAULT_MAX_TOOL_RESULT_CHARS`,
  `sdk/packages/core/src/session/services/message-builder.ts:29`) and past it cut in the middle, about 3 984 kept
  at each end, `...[truncated N chars]...` between and the cache notice after
  (`message-builder.ts:273-298`, `1619-1641`). So everything in the object counts: the JSON's own characters
  (35 before the first block's text), every escape of the text (`\n`, `\"`, `\\` two characters each; a block of 495
  short lines gains 495), and `structuredContent` - which is why a result carries none. The preview that would put
  `[image attached]` in an image's place (`tool-result-cache.ts:101-148`) is given that string, not the object, so
  an image block reaches the model as its base64 inside the text, cut, and no picture is seen: with Cline leave
  `inline_images` and `screenshots` off, and read a picture's words with `ocr`. The server counts an image as
  `[image attached]` all the same, the most it can do.
- **Cline's legacy VS Code bundle** (the `legacy-extension` branch, 3.89.x,
  `apps/vscode/src/core/task/tools/handlers/UseMcpToolHandler.ts:176-213`): the text blocks joined by a blank
  line, an image passed as an image when the model takes them, `structuredContent` not read; cut at 400 KB.
- **Codex** (openai/codex bee5dc5, `codex-rs/protocol/src/models.rs:2488-2525`): with `structuredContent` the
  model gets that alone, serialised, in place of the text; without it the blocks.

`read_url(url="probe", probe=N)` in Cline's runtime shows that form: of the 3 984 units Cline keeps at the head, the
JSON's start takes 35 and each line's `\n` one more, so the last line seen before the gap says that many characters
fewer than 3 984 stand before it.

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
- Calls at once: every `read_url` runs `readpage.py` in a child process, and so does a `read` of `content.md` or
  `page.md` whose block may have a picture with no file yet, at most four calls at a
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
- An address that starts with `-` is refused ("an address or a path, not a flag"), and the child gets every address
  after `--`: a model's argument is never read as a flag. `url="--setup"` once ran the installer, with no yes of the
  user's (KNOWN-ISSUES 291).
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
example: it makes the children and everything else UTF-8 too. Under a POSIX locale that is not UTF-8 (zh_CN.GBK) a
folder the answer names is found again when a model sends it back, with or without the flag, whether its name's bytes
are the locale's or UTF-8 - the reader's child, always in UTF-8 mode, makes the latter.

## Why not a third tool

`search`, `screenshot`, `click` belong to a browser-automation tool, not to a reader, and the
privacy model here does not cover them. `show`/`explain` are backlog: attach metadata first, then
try a blob; transcription needs `--allow-external` on that very call.
