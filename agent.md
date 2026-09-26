# agent.md — Operating Manual for AI Agents

> **Read this file and nothing else.** If you are an AI model (or a human in a
> hurry) and you need to harvest an X/Twitter thread *right now*, this document
> is the complete, self-sufficient operating manual: what the tool is, exactly
> how to invoke it, how to parse the result, and what to do when something
> fails. No human help is required at any point.

---

## 1. What this tool is

`xthread-agent.py` is a single-file, stdlib-only Python CLI that converts an
X/Twitter status URL into:

1. **Media files on disk** — every video (best-quality mp4) and photo in the
   thread, plus poster thumbnails.
2. **A machine-readable manifest** — `thread_manifest.json`, an enveloped
   document (schema_version 3.0) mapping the reconstructed thread to posts
   (text, author, timestamps, metrics, quoted posts), media (URLs, local file
   paths, dimensions, durations), extraction statistics, and per-stage errors.

It works without login, cookies, OAuth, or a browser, from any IP class,
including datacenter IPs where X blocks everything else.

**Version contract:** `--version` prints a semver string. The JSON contract in
section 4 is stable within a major version. (v3 changed the manifest from a
bare array to an envelope — see RELEASE_NOTES.md.)

---

## 2. Preconditions (check once)

- Python **3.9+** on PATH (`python3 --version`).
- Outbound HTTPS to: `unrollnow.com`, `api.fxtwitter.com`,
  `api.vxtwitter.com` (automatic fallback, only on primary-decoder network
  failure), `video.twimg.com`, `pbs.twimg.com`.
- Nothing else. No pip, no ffmpeg, no browser, no env vars.

---

## 3. How to run

### Standard run (download everything)

```bash
python3 xthread-agent.py "https://x.com/<user>/status/<status_id>" --out media/
```

- Accepts a full URL, a bare numeric status ID, **or a t.co shortlink**
  (resolved one hop, then validated — non-status destinations fail closed
  with `E_INVALID_INPUT`).
- Logs stream to **stderr** as the pipeline runs:

  ```
  [ok ] walker slot 'unrollnow': 11 candidate ids
  [skip] 2199999999999999999: not a tweet (media id or unavailable)
  [dl ] 2100632011572727818_v1.mp4  17.35 MB
  [done] 2 posts · 2 videos · 0 photos · 2 files -> media/thread_manifest.json
  ```

  If the primary walker slot fails, the log names the fallback slot; the
  envelope's `thread.walker_slot` records who served the walk.

### Agent-friendly run (machine parsing)

```bash
python3 xthread-agent.py "<status_url>" --out media --json --quiet
```

- `--json`: a summary object is printed to **stdout** (see section 4).
- `--quiet`: stderr is silenced.
- Always keep stderr separate from stdout — they never interleave.

### Manifest-only run (fast probe)

```bash
python3 xthread-agent.py "<status_url>" --no-download
```

Use this when you only need the thread's text, structure, and media URLs
(no disk cost, faster). Local `file` fields are `null` and `downloaded` is
`false`; `url` fields are always populated.

### Via MCP (Model Context Protocol)

If you are an MCP client, run `python3 mcp_server.py` as a stdio server
(newline-delimited JSON-RPC 2.0; logs on stderr). It exposes four tools:

- `extract_thread` {url, out_dir?, download_media?} — full harvest; returns
  `{out_dir, manifest_path, summary, envelope}` where `envelope` is the exact
  manifest document (see section 4).
- `lookup_status` {url, out_dir?} — the same reconstruction with
  `--no-download`; the fast read-only path.
- `read_manifest` {path} — returns an existing `thread_manifest.json`
  verbatim; refuses any other filename.
- `get_schema` {} — returns the JSON Schema for the envelope.

Error semantics: `isError: true` means the invocation itself failed (bad
arguments, timeout, crash). `isError: false` with `envelope.status == "empty"`
is an honest negative result — the post is unavailable, and `errors[]` says
why. `lookup_status` applies a 120s hard timeout; `extract_thread` allows
up to 900s (override with `XTHREAD_MCP_EXTRACT_TIMEOUT`).

---

## 4. The JSON contract

`--json` prints exactly one JSON object on stdout:

```json
{
  "ok": true,
  "status": "ok",
  "root_id": "1234567890123456789",
  "canonical_url": "https://x.com/i/web/status/1234567890123456789",
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

| Field | Type | Meaning |
|---|---|---|
| `ok` | bool | `true` iff at least one post was harvested |
| `status` | string | `ok` / `partial` (posts, but errors present) / `empty` |
| `root_id` | string | The canonical status ID resolved from your input |
| `canonical_url` | string | `https://x.com/i/web/status/<id>` |
| `tweets` | int | Posts reconstructed into the manifest (thread order) |
| `videos` / `photos` | int | Media items discovered |
| `downloaded` / `failed_downloads` | int | Media files on disk / failed transfers |
| `out_dir`, `manifest_path` | string | Where the results live |
| `errors` | int | Number of structured error entries in the manifest |
| `duration_sec` | number | Wall-clock runtime |

**`thread_manifest.json` schema** (envelope; formal JSON Schema in
`schema/thread-result.schema.json`):

```json
{
  "schema_version": "3.0",
  "source":  { "tool": "xthread-agent", "version": "3.0.0", "generated_at": "2026-09-24T12:00:00Z" },
  "request": { "input": "<as given>", "status_id": "…", "canonical_url": "…",
               "options": { "download_media": true } },
  "status": "ok | partial | empty",
  "thread": { "root_status_id": "…", "tweet_count": 4, "walker_candidates": 11,
              "decoded_tweets": 5, "media_ids_filtered": 5, "decode_failed": 0,
              "related_filtered": 1, "ancestors_fetched": 0,
              "chain_reconstructed": true, "degraded_to_root_only": false },
  "posts": [
    {
      "id": "…",
      "url": "https://x.com/<user>/status/…",
      "text": "post text",
      "lang": "en",
      "source": "Twitter Web Client",
      "created_at": "raw decoder timestamp",
      "created_at_iso": "2026-09-17T17:04:34Z",
      "thread_position": 0,
      "replying_to": null,
      "replying_to_status": null,
      "extraction_source": "fxtwitter",
      "metrics": { "likes": 1631, "retweets": 112, "replies": 80,
                    "quotes": 14, "bookmarks": 30, "views": 123614 },
      "author": { "screen_name": "…", "name": "…", "verified": true,
                  "followers": 1768, "avatar_url": "…", "…": null },
      "media": {
        "photos": [ { "url": "…", "alt_text": null, "width": 1320, "height": 1350,
                      "file": "…_p1.jpg", "downloaded": true } ],
        "videos": [ { "url": "…mp4", "playlist_url": null, "poster_url": "…",
                      "format": "video/mp4", "duration": 22.613,
                      "width": 1436, "height": 1080, "variants": [],
                      "file": "…_v1.mp4", "poster_file": "…_v1_poster.jpg",
                      "downloaded": true, "downloadable": true, "reason": null } ]
      },
      "quoted_post": null
    }
  ],
  "errors": [ { "stage": "walker", "code": "E_WALKER_UNAVAILABLE",
                "message": "thread walk source unavailable: …", "subject": "…" } ],
  "metadata": { "duration_sec": 86.3,
                "counts": { "posts": 4, "photos": 2, "videos": 11,
                            "downloaded_media": 13, "failed_downloads": 0 } }
}
```

Rules of the envelope:

- **Explicit nullability**: a field you do not care about is still present
  (`null`), so keying never throws.
- **`thread_position`** orders the chain (0 = thread start). The chain is
  reconstructed from `replying_to_status`, not from page order.
- **`related_filtered`** counts decoded tweets that were *excluded* because
  they are not part of the self-reply chain — they are recommendations from
  the walk source, not thread members.
- **`extraction_source`** tells you which decoder slot produced the post
  (`fxtwitter` primary, `vxtwitter` fallback — the fallback provides a
  smaller but honest subset of fields).
- **Errors never corrupt posts.** A failed download marks that media item
  (`downloaded: false`), records an entry in `errors[]`, and flips the
  envelope `status` to `partial`. Successful data stays intact.

---

## 5. Decision tree

```
START
 ├─ Is the target a public status URL or ID?
 │    └─ No → STOP. Private/protected content is out of scope by design.
 ├─ Run: python3 xthread-agent.py "<url>" --json --quiet
 │
 ├─ exit 0 AND ok=true
 │    ├─ status == "ok"            → clean harvest. DONE.
 │    └─ status == "partial"       → posts harvested, but read errors[]
 │         ├─ E_WALKER_*           → chain may be root-only / incomplete;
 │         │                          retry later for the full thread.
 │         ├─ E_DECODE_FAILED      → a related candidate was lost; your
 │         │                          posts are unaffected unless tweet_count
 │         │                          is lower than expected.
 │         └─ E_DOWNLOAD_FAILED    → some media is missing on disk; the
 │                                    manifest marks each failed item.
 ├─ exit 0 AND ok=false, or exit 1
 │    ├─ status == "empty" + E_ROOT_UNAVAILABLE → root deleted/protected/
 │    │                                            not a tweet. STOP.
 │    ├─ Network errors in stderr (timeouts, DNS)?
 │    │    └─ Retry once after 60s. Still failing → STOP (environment issue).
 │    └─ status == "invalid_input" → your URL is malformed; supply
 │                                    https://x.com/<user>/status/<digits>.
 └─ Exit code 2 from argparse
      └─ Usage error (missing argument).
```

**Resumability:** downloads are skip-if-exists. If a run dies mid-way, simply
re-run the same command — completed files are never re-downloaded, and
truncated `.part` leftovers are re-downloaded (never trusted).

**Rate limits:** the tool sleeps ~0.6s between tweets and retries with
backoff. Do not run parallel harvests of many threads from one IP; serialize
them, and never run two harvests into the same output directory at once.

---

## 6. Common tasks (copy-paste)

```bash
# Harvest a thread to ./media
python3 xthread-agent.py "https://x.com/<user>/status/<id>" --out media

# JSON summary, pipeable
python3 xthread-agent.py "https://x.com/<user>/status/<id>" --json --quiet | jq .

# Only want the text of the thread? Manifest-only, then read it.
python3 xthread-agent.py "<url>" --no-download
cat media/thread_manifest.json | jq -r '.posts[].text'

# Count videos without downloading
python3 xthread-agent.py "<url>" --no-download --json --quiet | jq .videos

# Author + timestamps of every post, in thread order
cat media/thread_manifest.json | jq '.posts[] | {pos: .thread_position,
  author: .author.screen_name, at: .created_at_iso}'

# Batch: serialize threads, one at a time
for id in <id1> <id2> <id3>; do
  python3 xthread-agent.py "$id" --out "media_$id" --json --quiet
done

# Minimal programmatic consumption (see demo.py)
python3 demo.py "<url>" --out demo_output
```

---

## 7. Known limitations

- **Thread shape:** linear self-reply chains. Branching replies take the
  first-seen branch; cross-author reply trees are out of scope.
- **Walk source down** → root-only harvest; the envelope reports
  `degraded_to_root_only: true` and `status: partial`.
- **HLS-only videos** (no mp4 variant anywhere in `formats[]`) are reported
  with `downloadable: false, reason: "hls_only"` — URL references, not files.
- **Quoted-post media** is recorded as URLs, not downloaded.
- Nothing here bypasses paywalls, protected accounts, or deleted tweets —
  by design (`status: empty`).
- Media downloads are restricted to `*.twimg.com` https URLs and verified
  against `Content-Length`; transfers are restarted (not byte-resumed) on
  failure.

---

## 8. Hard constraints of this system

1. No login, cookies, OAuth, browser sessions, or interactive prompts.
2. Public content only.
3. No LLM at runtime — the tool is a deterministic state machine.
4. Logs on stderr, data on stdout. Always.
5. Files stay under `--out` (remote IDs validated before use in filenames;
   media fetches restricted to X's CDN hosts).
6. Respect creators and rights holders; archive responsibly.
