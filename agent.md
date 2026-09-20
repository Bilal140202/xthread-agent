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
2. **A machine-readable manifest** — `thread_manifest.json`, mapping each tweet
   to its text, author, engagement stats, media URLs, and local file paths.

It works without login, cookies, OAuth, or a browser, from any IP class,
including datacenter IPs where X blocks everything else.

**Version contract:** `--version` prints a semver string. The JSON contract in
section 4 is stable within a major version.

---

## 2. Preconditions (check once)

- Python **3.9+** on PATH (`python3 --version`).
- Outbound HTTPS to: `unrollnow.com`, `api.fxtwitter.com`,
  `video.twimg.com`, `pbs.twimg.com`.
- Nothing else. No pip, no ffmpeg, no browser, no env vars.

---

## 3. How to run

### Standard run (download everything)

```bash
python3 xthread-agent.py "https://x.com/<user>/status/<status_id>" --out media/
```

- Accepts a full URL **or** a bare numeric status ID.
- Logs stream to **stderr** as the pipeline runs:

  ```
  [ok ] thread resolved: N candidate ids
  [dl ] <id>_v1.mp4  2.31 MB
  [skip] <id>_v1_poster.jpg exists
  [done] 4 tweets · 11 videos · 0 photos -> media/thread_manifest.json
  ```

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
(no disk cost, faster). Local `file` fields are `null`; `url` fields are
always populated.

---

## 4. The JSON contract

`--json` prints exactly one JSON object on stdout:

```json
{
  "ok": true,
  "root_id": "1234567890123456789",
  "tweets": 4,
  "videos": 11,
  "photos": 2,
  "out_dir": "media",
  "manifest_path": "media/thread_manifest.json",
  "duration_sec": 86.3
}
```

| Field | Type | Meaning |
|---|---|---|
| `ok` | bool | `true` iff at least one tweet was harvested |
| `root_id` | string | The canonical status ID resolved from your input |
| `tweets` | int | Tweets decoded into the manifest |
| `videos` / `photos` | int | Media items discovered (and downloaded, unless `--no-download`) |
| `out_dir` | string | Directory holding the files |
| `manifest_path` | string | Path to the full manifest |
| `duration_sec` | number | Wall-clock runtime |

**`thread_manifest.json` schema** (array, one entry per tweet, thread order):

```json
[
  {
    "id": "…",
    "author": "screen_name",
    "text": "tweet text",
    "created_at": "…",
    "likes": 0, "retweets": 0, "replies": 0, "views": 0,
    "videos": [
      {
        "file": "media/<id>_v1.mp4",
        "url": "https://video.twimg.com/…",
        "downloaded": true,
        "duration": 41.6,
        "width": 1280, "height": 720,
        "poster": "media/<id>_v1_poster.jpg"
      }
    ],
    "photos": [ { "file": "media/<id>_p1.jpg", "url": "…", "downloaded": true, "alt": "…" } ]
  }
]
```

---

## 5. Decision tree

```
START
 ├─ Is the target a public status URL or ID?
 │    └─ No → STOP. Private/protected content is out of scope by design.
 ├─ Run: python3 xthread-agent.py "<url>" --json --quiet
 │
 ├─ exit 0 AND ok=true
 │    ├─ Need the media? Files are already in out_dir.
 │    ├─ Need per-tweet detail? Read manifest_path.
 │    └─ DONE.
 │
 ├─ exit 0 AND ok=false, or exit 1
 │    ├─ Root tweet deleted / protected? → STOP. Nothing to harvest.
 │    ├─ Network errors in stderr (timeouts, DNS)?
 │    │    └─ Retry once after 60s. Still failing → STOP (environment issue).
 │    └─ Thread walk degraded? The tool already fell back to root-only;
 │         if you need the full chain, retry later — UnrollNow outages
 │         are transient.
 │
 └─ Exit code from shell is 2 / argparse error
      └─ Your input is malformed. Supply a URL containing /status/<digits>.
```

**Resumability:** downloads are skip-if-exists. If a run dies mid-way, simply
re-run the same command — completed files are never re-downloaded.

**Rate limits:** the tool sleeps ~0.6s between tweets and retries with
backoff. Do not run parallel harvests of many threads from one IP; serialize
them.

---

## 6. Common tasks (copy-paste)

```bash
# Harvest a thread to ./media
python3 xthread-agent.py "https://x.com/<user>/status/<id>" --out media

# JSON summary, pipeable
python3 xthread-agent.py "https://x.com/<user>/status/<id>" --json --quiet | jq .

# Only want the text of the thread? Manifest-only, then read it.
python3 xthread-agent.py "<url>" --no-download
cat media/thread_manifest.json | jq -r '.[].text'

# Count videos without downloading
python3 xthread-agent.py "<url>" --no-download --json --quiet | jq .videos

# Batch: serialize threads, one at a time
for id in <id1> <id2> <id3>; do
  python3 xthread-agent.py "$id" --out "media_$id" --json --quiet
done
```

---

## 7. Known limitations

- Media-only conversation members are *filtered*, not returned (they are not
  tweets).
- If the thread walk source is down, only the root tweet is harvested (the
  summary still reports `ok=true` — check `tweets` against your expectations).
- HLS-only videos (`.m3u8`) are saved as URL references, not files.
- Nothing here bypasses paywalls, protected accounts, or deleted tweets —
  by design.

---

## 8. Hard constraints of this system

1. No login, cookies, OAuth, browser sessions, or interactive prompts.
2. Public content only.
3. No LLM at runtime — the tool is a deterministic state machine.
4. Logs on stderr, data on stdout. Always.
5. Files stay under `--out`.
6. Respect creators and rights holders; archive responsibly.
