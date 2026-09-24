# xthread-agent 🧵

**An agentic X/Twitter thread content & media harvester for cloud-based AI agents.**

[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/Bilal140202/xthread-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/Bilal140202/xthread-agent/actions/workflows/ci.yml)
[![GitHub](https://img.shields.io/badge/GitHub-Bilal140202%2Fxthread--agent-black.svg)](https://github.com/Bilal140202/xthread-agent)
[![stdlib only](https://img.shields.io/badge/dependencies-stdlib%20only-success.svg)](#requirements)

`xthread-agent` is a deterministic, single-file CLI agent built specifically for
cloud-based AI agents and headless environments. Give it any public X status URL
and it returns the reconstructed thread (posts, authors, timestamps, quoted
posts), every video and photo in the thread as files on disk, plus an enveloped
machine-readable manifest. No login. No API keys. No browser. No cookies.

**One goal:** the calling agent gives us an X status URL; we return the thread's
content and media, on disk, with a machine-readable manifest. Everything else is
implementation.

```bash
python3 xthread-agent.py "https://x.com/<user>/status/<status_id>" --out media/
```

---

## Why this exists

X locked down its public GraphQL endpoints. As of 2026, the standard toolbox is
broken in specific, well-defined ways — this tool routes around all of them
(see the [endpoint matrix](docs/endpoint-matrix.md) for the full autopsy):

| Approach | Status in 2026 |
|---|---|
| `gallery-dl` guest-token + `TweetResultByRestId` | ❌ Dead — guest token activates, GraphQL returns empty payload |
| `yt-dlp` on status URLs | ❌ Dead — same GraphQL wall |
| **Nitter** (all public instances) | ❌ Dead — timeouts / HTTP 451 |
| Direct `x.com` scrape (headless or curl) | ❌ Blocked — empty shell for datacenter IPs |
| `api.vxtwitter.com` | ✅ **Alive again** (re-verified 2026-09-24) — used as the **fallback decoder slot** |
| sotwe.com / twstalker.com mirrors | ❌ Blocked — Cloudflare 403 |
| `syndication.twitter.com` timeline endpoint | ⚠️ Rate-limited (429) — unusable for thread walking |
| `cdn.syndication.twimg.com/tweet-result` | ✅ Works — single tweets only, no traversal |
| `api.fxtwitter.com/status/<id>` | ✅ **Works** — full tweet JSON incl. multi-video "amplify" media |
| **unrollnow.com/status/<id>** | ✅ **Works** — public thread walk; ⚠️ its pages also embed *recommendations*, which this tool filters out |

**xthread-agent = Thread Walker (UnrollNow) + Metadata Decoder (FixTweet, with
vxtwitter fallback) + Thread Reconstructor (`replying_to_status` chain) +
Media Fetcher (twimg CDN).**

---

## Architecture

```
status URL
   │
   ▼
┌───────────────────────────────┐
│ 0. NORMALIZE + VALIDATE       │  proper URL parsing (x.com / twitter.com,
│    → bare status id           │  mobile/www hosts, /photo /video suffixes)
└───────────────┬───────────────┘
                ▼
┌───────────────────────────────┐
│ 1. THREAD WALK                │  GET unrollnow.com/status/<root_id>
│    regex-extract every        │  → ordered, deduped candidate IDs
│    candidate ID               │    (root ALWAYS kept; capped at 50)
└───────────────┬───────────────┘
                ▼
┌───────────────────────────────┐
│ 2. METADATA DECODE            │  GET api.fxtwitter.com/status/<id>
│    (3 retries, backoff)       │  → text, author, stats, media[]
│    404s = media IDs, skipped  │    fallback slot: api.vxtwitter.com
└───────────────┬───────────────┘
                ▼
┌───────────────────────────────┐
│ 3. CHAIN RECONSTRUCTION       │  true self-reply chain from
│    walk UP to thread start,   │  replying_to_status — unrelated
│    walk DOWN through replies  │    same-author recommendations are
└───────────────┬───────────────┘    excluded, not harvested
                ▼
┌───────────────────────────────┐
│ 4. CDN DOWNLOAD               │  video.twimg.com/…mp4  (best variant;
│    atomic (.part + rename)    │  m3u8-only videos fall back to the
│    resumable, size-verified   │  highest-bitrate mp4 in formats[])
└───────────────┬───────────────┘
                ▼
┌───────────────────────────────┐
│ 5. thread_manifest.json       │  enveloped result: source, request,
│    (schema_version 3.0)       │  thread stats, posts[], errors[],
│                               │  metadata — UTF-8, atomic write
└───────────────────────────────┘
```

### Key research findings baked into the code

- **UnrollNow pages embed recommendations, not just the conversation.**
  Same-author tweets that do not reply to the root appear alongside thread
  members; the walker's output is treated strictly as *candidates*. Chain
  membership is decided by `replying_to_status` from the decoder — never by
  page order. (v2.0.0 harvested recommendations as thread members; v3 does not.)
- **The root is always harvested**, even for short legacy IDs the walker's
  regex cannot see (v2.0.0 silently dropped the root in that case).
- **A 404/451 from the decoder is a filter signal, not an error.** It arrives
  both as a 200 body with `code: 404` and as a real HTTP status — both are
  handled as instant, retry-free filters.
- **FixTweet decodes multi-video "amplify" tweets**, and its `formats[]`
  array carries mp4 variants with bitrates — so even videos whose primary URL
  is HLS-only can usually be downloaded as mp4 by variant selection.
- **`video.twimg.com` and `pbs.twimg.com` need no auth** once you have the
  URL. All authentication burden sits in front of *discovery*, not *delivery*.
- Media downloads are restricted to `*.twimg.com` over https, verified against
  `Content-Length`, streamed, and atomically renamed — a truncated transfer or
  a compromised decoder payload cannot corrupt local files.

---

## Quickstart

```bash
# stdlib only — Python 3.9+, nothing to install
python3 xthread-agent.py "https://x.com/<user>/status/<id>"
```

Output layout:

```
media/
├── <tweetid>_v1.mp4           # videos (best-quality mp4)
├── <tweetid>_v1_poster.jpg    # poster frames
├── <tweetid>_p1.jpg           # photos
└── thread_manifest.json       # everything, mapped (envelope, schema 3.0)
```

### CLI reference

```bash
python3 xthread-agent.py <status_url_or_id> [--out DIR] [--no-download]
                                               [--json] [--quiet] [--version]
```

| Flag | Purpose |
|---|---|
| `--out DIR` | Output directory (default `x_thread_media`) |
| `--no-download` | Manifest only — resolve, decode, reconstruct; skip media |
| `--json` | Machine-readable summary on **stdout** (all logs stay on stderr) |
| `--quiet` | Suppress log lines |
| `--version` | Print version |

Exit codes: `0` = at least one post harvested, `1` = nothing harvested / error,
`2` = usage error.

### JSON output (for AI agents)

```bash
python3 xthread-agent.py "https://x.com/<user>/status/<id>" --json --quiet
```

```json
{
  "ok": true,
  "status": "ok",
  "root_id": "…",
  "canonical_url": "https://x.com/i/web/status/…",
  "tweets": 4,
  "videos": 11,
  "photos": 2,
  "downloaded": 13,
  "failed_downloads": 0,
  "out_dir": "media",
  "manifest_path": "media/thread_manifest.json",
  "errors": 0,
  "duration_sec": 86.3
}
```

`status` is `ok` (posts, no errors), `partial` (posts but something degraded —
see `errors`), or `empty` (nothing harvested). The full detail — posts in
thread order, authors, timestamps, quoted posts, media URLs, local file paths,
per-stage errors — lives in `thread_manifest.json`
([JSON Schema](schema/thread-result.schema.json)).

---

## For AI agents

### The 3-command contract

```bash
python3 xthread-agent.py "<status_url>" --json --quiet   # run
cat <out>/thread_manifest.json                           # inspect
```

Exit code `0` = at least one post harvested. `1` = nothing. `2` = usage error.
Logs are always on **stderr**; `--json` results are always on **stdout**, so
the two can be piped safely.

`agent.md` is the complete operating manual — an AI agent reading only that
file can run this tool end-to-end without asking a human a single question.
`agents.md` defines the role prompts each internal stage must conform to.
`demo.py` is a minimal runnable example of programmatic consumption.

### MCP server (Model Context Protocol)

For MCP-compatible agent hosts (Claude Desktop, Zed, custom hosts),
`mcp_server.py` exposes the harvester as tools over the standard stdio
transport — still stdlib-only, still no login:

```bash
python3 mcp_server.py   # speaks MCP on stdin/stdout; logs on stderr
```

| Tool | What it does |
|---|---|
| `extract_thread` | Full harvest: thread reconstruction + media downloads; returns the envelope |
| `lookup_status` | Metadata-only (`--no-download` equivalent): text, authors, timestamps, media URLs |
| `read_manifest` | Returns an existing `thread_manifest.json` verbatim (refuses any other filename) |
| `get_schema` | Returns the JSON Schema for the envelope contract |

The server never reimplements the pipeline — each tool call shells out to
`xthread-agent.py` as a subprocess with a hard timeout, so the CLI contract,
schema, and politeness rules stay the single source of truth. Register it in
your MCP client config as a stdio command, e.g.
`{"command": "python3", "args": ["/path/to/mcp_server.py"]}`.

---

## Documentation

| File | Purpose |
|---|---|
| [`agent.md`](agent.md) | Agent entry point — how to run, the JSON contract, decision tree |
| [`agents.md`](agents.md) | Role prompts for the internal agent roster (the spec) |
| [`mcp_server.py`](mcp_server.py) | MCP wrapper — exposes the harvester as MCP tools over stdio (stdlib-only) |
| [`demo.py`](demo.py) | Minimal end-to-end consumption example |
| [`schema/thread-result.schema.json`](schema/thread-result.schema.json) | JSON Schema (draft-07) for the manifest envelope |
| [`docs/research-blog.md`](docs/research-blog.md) | Research chronicle: the X lockdown and the bypass architecture |
| [`docs/endpoint-matrix.md`](docs/endpoint-matrix.md) | Living reference: every endpoint, its status, its failure signature |
| [`PROJECT_CONTEXT.md`](PROJECT_CONTEXT.md) | Why this exists, design decisions, fragile parts — for future maintainers |
| [`RELEASE_NOTES.md`](RELEASE_NOTES.md) | Version history |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | How to contribute |

---

## Constraints (non-negotiable)

1. **No login. No cookies. No OAuth. No browser.** Public content only.
2. **No GUI. No interactive prompts.** 100% non-interactive CLI.
3. **No LLM at runtime.** Deterministic state machine.
4. **stdlib only.** Single file, no pip installs, Python 3.9+.
5. **Logs on stderr, data on stdout.** Always pipe-safe.
6. **Files stay under the output directory.** Media URLs are restricted to
   X's CDN hosts; remote IDs are validated before use in filenames.

## Requirements

- Python **3.9+** (the tool itself). Tests also run on stdlib `unittest`.
- Outbound HTTPS to `unrollnow.com`, `api.fxtwitter.com`, `api.vxtwitter.com`
  (fallback only), `video.twimg.com`, `pbs.twimg.com`.

---

## Testing

```bash
python3 -m unittest discover -s tests -p "test_*.py" -v   # 110 offline tests, ~1s
```

The suite covers URL normalization, the walker, both decoders (including the
vxtwitter fallback and HTTP 404/451/429 paths), chain reconstruction, payload
mapping, atomic downloads, the envelope contract, CLI behavior, and the MCP
wrapper (protocol framing, tools, error paths) — all against synthetic
fixtures (no network). CI (`.github/workflows/ci.yml`) runs the same suite on
Python 3.9–3.13 on every push and PR; live endpoints are deliberately never
probed from CI. For a real end-to-end run, use `demo.py` against any public
status URL of your choice; keep the request rate polite and test against
content you control where possible.

---

## Media

- **Videos**: downloaded as mp4 at the best available quality (the decoder's
  primary URL, or the highest-bitrate mp4 variant when the primary is HLS).
  Video metadata includes duration, dimensions, format, and the full variant
  list. Videos that genuinely have no mp4 variant are reported with
  `downloadable: false` and a `reason` (`hls_only`) — never silently dropped.
- **Photos**: downloaded at source resolution with alt text and dimensions.
- **Posters**: every downloaded video gets its poster frame.
- **Quoted posts**: recorded with author, text, timestamp, and media *URLs*
  (quoted media is not downloaded — it belongs to the quoted post, and this
  keeps runs polite and output directories honest).

## No-login architecture

"No login" here means: the tool never presents credentials, cookies, session
tokens, or a browser fingerprint, and it never touches `x.com` itself. It
reads three *public* surfaces that any visitor can reach without
authentication: an unrolling service (thread candidates), two open
link-decoder workers (per-tweet JSON), and X's own media CDN (bytes). This
works because X's authentication wall guards *discovery* APIs, while the CDN
serves whatever URL a decoder already resolved. It does **not** mean the
access is officially supported by X or guaranteed to last — see
[Limitations](#limitations) and the [endpoint matrix](docs/endpoint-matrix.md).

## Limitations (be honest, we are)

- **Dependency on free third-party services.** If UnrollNow or FixTweet change
  or gate datacenter IPs, functionality degrades (root-only harvest, or
  `empty`). The fallback decoder slot mitigates but does not eliminate this.
- **Retweet URLs resolve to the original post.** For a retweet URL the
  decoder returns the original tweet's payload, so `posts[0].id` is the
  *original* post ID while `request.status_id` / `thread.root_status_id`
  stay the requested ID. The harvested content is exactly what that URL
  publicly shows (the retweeted post).
- **Linear self-reply chains only.** Threads where the author branches into
  multiple replies get the first-seen branch; cross-author reply trees are out
  of scope by design.
- **Deleted/protected/age-restricted content** fails closed (`status: empty`)
  — nothing here bypasses access controls.
- **HLS-only videos** (rare) are reported but not downloaded.
- **A slow-drip CDN transfer** is cut off at the transfer deadline; the retry
  restarts the file rather than resuming by byte range.
- **UnrollNow outages** degrade the walk to root-only; the manifest records
  this (`degraded_to_root_only: true`) so callers can tell.
- **One run at a time per output directory.** Concurrent runs can interleave.
- **"Publicly accessible" ≠ "officially supported."** Every technique here
  depends on surfaces X does not officially expose to tools.

## Legal / platform considerations

This tool reaches only publicly accessible content and depends on third-party
public services. Using it may be subject to — and is **your** responsibility
under — X's Terms of Service, the terms of the third-party services involved,
applicable copyright law, data-protection law, and any other rules that apply
to you or your jurisdiction. Nothing in this repository grants any license to
the content harvested: posts and media belong to their authors and rights
holders. Do not use the tool to harass, dox, or invade privacy; do not
republish harvested media commercially; archive responsibly and credit
creators. If your use case requires guaranteed, sanctioned access, use the
official X API.

## Ethics & disclaimer

For personal archiving and research. Respect creators: whoever curated the
thread you harvest added value; the underlying media belongs to its original
rights holders. Don't repost harvested media commercially. Don't use this tool
to invade anyone's privacy — it only reaches public content that any visitor
can see.

## License

MIT. See [`LICENSE`](LICENSE).

## Acknowledgments

- [FixTweet / FxTwitter](https://github.com/FixTweet/FxTwitter) — the public worker that decodes tweet payloads
- [vxtwitter](https://github.com/dylanpdx/BetterTwitFix) — the fallback decoder slot
- [UnrollNow](https://unrollnow.com) — public thread unrolling service
- [ytagent](https://github.com/Bilal140202/ytagent) — sibling project; the "document which doors remain open" philosophy started there

## Links

- **GitHub:** https://github.com/Bilal140202/xthread-agent
- **Issues:** https://github.com/Bilal140202/xthread-agent/issues
