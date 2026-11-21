// defuddle for one read, without the CLI's start-up on every call (ddworker.py starts it).
// It loads defuddle's modules and warms the JIT on a built-in page while the HTTP request is in
// flight, says {"ready": true}, then answers each page sent on stdin as "<id> <byte length>\n<html>"
// with one JSON line, {"id": id, "content": markdown}, in the order the pages came. The call is the CLI's own `defuddle parse FILE
// --markdown`: parseLinkedomHTML, Defuddle with markdown and separateMarkdown, no URL (the page
// carries a <base href>), and the CLI's empty-content check, so the text is the CLI's text.
// Usage: node ddworker.js DEFUDDLE_DIST
"use strict";
const path = require("path");
let parseLinkedomHTML, Defuddle;
try {
  ({ parseLinkedomHTML } = require(path.join(process.argv[2], "utils", "linkedom-compat")));
  ({ Defuddle } = require(path.join(process.argv[2], "node")));
} catch (e) {
  process.stdout.write(JSON.stringify({ ready: false, error: String(e).slice(0, 200) }) + "\n");
  process.exit(1);
}

async function parse(html) {
  const doc = parseLinkedomHTML(html);
  const res = await Defuddle(doc, undefined, { markdown: true, separateMarkdown: true });
  const text = parseLinkedomHTML(`<!DOCTYPE html><html><body>${res.content}</body></html>`)
    .body.textContent?.trim() || "";
  return text ? res.content + "\n" : "";      // the CLI prints it with console.log: one newline
}

function sample() {
  // an ordinary article: chrome around a body with the elements turndown has rules for
  const p = (i) => `<p>Paragraph ${i} with <a href="/link/${i}">a link</a>, <em>emphasis</em>, ` +
    `<strong>strong text</strong> and <code>inline code</code>. Lorem ipsum dolor sit amet, ` +
    `consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore.</p>`;
  let body = "";
  for (let s = 1; s <= 6; s++) {
    body += `<h2 id="s${s}">Section ${s}</h2>`;
    for (let i = 0; i < 5; i++) body += p(s * 10 + i);
    body += `<ul><li>One <a href="#a">item</a></li><li>Two</li></ul><ol><li>First</li><li>Second</li></ol>`;
    body += `<pre><code class="language-js">const x = ${s};\nconsole.log(x);</code></pre>`;
    body += `<blockquote><p>A quote ${s}.</p></blockquote>`;
    body += `<figure><img src="/img/${s}.png" alt="Figure ${s}"><figcaption>Caption ${s}</figcaption></figure>`;
    body += `<table><thead><tr><th>A</th><th>B</th></tr></thead><tbody><tr><td>1</td><td>2</td></tr></tbody></table>`;
  }
  let nav = "";
  for (let i = 0; i < 40; i++) nav += `<li><a href="/nav/${i}">Menu ${i}</a></li>`;
  return `<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>Sample</title>` +
    `<base href="https://example.com/a/"><meta name="description" content="A sample">` +
    `<script type="application/ld+json">{"@type":"Article","headline":"Sample"}</script>` +
    `</head><body><header><nav><ul>${nav}</ul></nav></header><aside><ul>${nav}</ul></aside>` +
    `<main><article><h1>Sample</h1><p class="byline">By A, 2026-01-01</p>${body}</article></main>` +
    `<footer><ul>${nav}</ul></footer></body></html>`;
}

let chunks = [], have = 0, need = -1, id = "", busy = false;

function take() {
  if (need < 0) {
    if (!have) return null;
    const b = Buffer.concat(chunks);
    const nl = b.indexOf(10);
    if (nl < 0) { chunks = [b]; return null; }
    const head = b.subarray(0, nl).toString().split(" ");      // "<id> <byte length>"
    id = head.length > 1 ? head[0] : "";
    need = parseInt(head[head.length - 1], 10);
    const rest = b.subarray(nl + 1);
    chunks = rest.length ? [rest] : [];
    have = rest.length;
  }
  if (have < need) return null;
  const b = Buffer.concat(chunks);
  const html = b.subarray(0, need).toString("utf8");
  const rest = b.subarray(need);
  chunks = rest.length ? [rest] : [];
  have = rest.length;
  need = -1;
  return [id, html];
}

async function pump() {
  if (busy) return;
  busy = true;
  for (let job = take(); job !== null; job = take()) {
    let out;
    try { out = { id: job[0], content: await parse(job[1]) }; }
    catch (e) { out = { id: job[0], content: "", error: String(e).slice(0, 200) }; }
    process.stdout.write(JSON.stringify(out) + "\n");
  }
  busy = false;
}

(async () => {
  try { await parse(sample()); } catch (e) { /* a cold JIT is still a working parser */ }
  process.stdin.on("data", (c) => { chunks.push(c); have += c.length; pump(); });
  process.stdin.on("end", () => process.exit(0));
  process.stdout.write(JSON.stringify({ ready: true }) + "\n");
})();
