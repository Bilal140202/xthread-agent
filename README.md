# xthread-agent 🧵

**An agentic X/Twitter thread media harvester for cloud-based AI agents.**

[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![GitHub](https://img.shields.io/badge/GitHub-Bilal140202%2Fxthread--agent-black.svg)](https://github.com/Bilal140202/xthread-agent)
[![stdlib only](https://img.shields.io/badge/dependencies-stdlib%20only-success.svg)](#requirements)

`xthread-agent` is a deterministic, single-file CLI agent built specifically for
cloud-based AI agents and headless environments. Give it any public X status URL
and it returns a directory of verified media files plus a machine-readable
manifest. No login. No API keys. No browser. No cookies.

**One goal:** the calling agent gives us an X status URL; we return every video
and photo in the thread, on disk, with a manifest. Everything else is
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
| `api.vxtwitter.com` | ❌ Blocked — Cloudflare JS challenge |
| sotwe.com / twstalker.com mirrors | ❌ Blocked — Cloudflare 403 |
| `syndication.twitter.com` timeline endpoint | ⚠️ Rate-limited (429) — unusable for thread walking |
| `cdn.syndication.twimg.com/tweet-result` | ✅ Works — single tweets only, no traversal |
| `api.fxtwitter.com/status/<id>` | ✅ **Works** — full tweet JSON incl. multi-video "amplify" media |
| **unrollnow.com/status/<id>** | ✅ **Works** — the only public source that lists every tweet ID in a thread, in order, without auth |

**xthread-agent = Thread Walker (UnrollNow) + Metadata Decoder (FixTweet) +
Media Fetcher (twimg CDN).**

---

## Architecture

```
status URL
   │
   ▼
┌───────────────────────────────┐
│ 1. THREAD WALK                │  GET unrollnow.com/status/<root_id>
│    regex-extract every        │  → ordered, deduped list of candidate IDs
│    conversation member ID     │    (includes media IDs — filtered later
└───────────────┬───────────────┘     by FixTweet 404 handling)
                ▼
┌───────────────────────────────┐
│ 2. METADATA DECODE            │  GET api.fxtwitter.com/status/<id>
│    (3 retries, backoff)       │  → text, author, stats, media[]
│    404s = media IDs, skipped  │    multi-video tweets fully decoded
└───────────────┬───────────────┘
                ▼
┌───────────────────────────────┐
│ 3. CDN DOWNLOAD               │  video.twimg.com/…mp4  (best available)
│    resumable (skip-if-exists) │  pbs.twimg.com/…jpg     (posters, photos)
└───────────────┬───────────────┘
                ▼
┌───────────────────────────────┐
│ 4. thread_manifest.json       │  tweet text + stats + local file map
└───────────────────────────────┘
```

### Key research findings baked into the code

- **The thread walk embeds the raw conversation** — tweet *and* media
  (amplify) IDs both appear in the HTML. FixTweet's 404 on a "tweet" is the
  signal that the ID was a media ID, so 404 is treated as *filter*, not
  *failure*.
- **FixTweet decodes multi-video tweets.** X allows 1 video per tweet in the
  UI, but uploader-side "amplify" media can attach several — FixTweet returns
  them all with direct CDN URLs, durations, and poster images.
- **`video.twimg.com` and `pbs.twimg.com` need no auth** once you have the URL.
- **The syndication `tweet-result` endpoint** accepts any bearer token value
  and is used as a lightweight single-tweet sanity check.

---

## Quickstart

```bash
# stdlib only — Python 3.9+, nothing to install
python3 xthread-agent.py "https://x.com/<user>/status/<id>"
```

Output layout:

```
media/
├── <tweetid>_v1.mp4           # videos (best quality mp4)
├── <tweetid>_v1_poster.jpg    # poster frames
├── <tweetid>_p1.jpg           # photos
└── thread_manifest.json       # everything, mapped
```

### CLI reference

```bash
python3 xthread-agent.py <status_url_or_id> [--out DIR] [--no-download]
                                               [--json] [--quiet] [--version]
```

| Flag | Purpose |
|---|---|
| `--out DIR` | Output directory (default `x_thread_media`) |
| `--no-download` | Manifest only — resolve and decode, skip media |
| `--json` | Machine-readable summary on **stdout** (all logs stay on stderr) |
| `--quiet` | Suppress log lines |
| `--version` | Print version |

### JSON output (for AI agents)

```bash
python3 xthread-agent.py "https://x.com/<user>/status/<id>" --json --quiet
```

```json
{
  "ok": true,
  "root_id": "…",
  "tweets": 4,
  "videos": 11,
  "photos": 0,
  "out_dir": "media",
  "manifest_path": "media/thread_manifest.json",
  "duration_sec": 86.3
}
```

Per-tweet detail — including local file paths, CDN URLs, durations, and
engagement stats — lives in `thread_manifest.json`.

---

## Proof of work

The system has been run end-to-end in a real cloud environment from a
datacenter IP — the environment class where X blocks everything else. A real
multi-tweet, multi-video thread (self-reply chain, mixed video counts per
tweet, tens of MB of media) was harvested completely: every video and poster
downloaded, manifest written, in under two minutes with zero auth and zero
failures. The same run validated the three-tier fallback: even when the thread
walk is unavailable, the tool degrades gracefully to root-tweet harvest.

For the full methodology — every endpoint tried, every failure signature
observed, and why the surviving paths work — read the
[research blog](docs/research-blog.md).

---

## For AI agents

### The 3-command contract

```bash
python3 xthread-agent.py "<status_url>" --json --quiet   # run
cat <out>/thread_manifest.json                           # inspect
```

Exit code `0` = at least one tweet harvested. `1` = nothing harvested.
Logs are always on **stderr**; `--json` results are always on **stdout**, so
the two can be piped safely.

`agent.md` is the complete operating manual — an AI agent reading only that
file can run this tool end-to-end without asking a human a single question.
`agents.md` defines the role prompts each internal stage must conform to.

---

## Documentation

| File | Purpose |
|---|---|
| [`agent.md`](agent.md) | Agent entry point — how to run, the JSON contract, decision tree |
| [`agents.md`](agents.md) | Perfection-based role prompts for the internal agent roster |
| [`docs/research-blog.md`](docs/research-blog.md) | In-depth research document on the X lockdown and the bypass architecture |
| [`docs/endpoint-matrix.md`](docs/endpoint-matrix.md) | Living reference: every endpoint, its status, its failure signature |
| [`RELEASE_NOTES.md`](RELEASE_NOTES.md) | Version history |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | How to contribute |

---

## Constraints (non-negotiable)

1. **No login. No cookies. No OAuth. No browser.** Public content only.
2. **No GUI. No interactive prompts.** 100% non-interactive CLI.
3. **No LLM at runtime.** Deterministic state machine.
4. **stdlib only.** Single file, no pip installs, Python 3.9+.
5. **Logs on stderr, data on stdout.** Always pipe-safe.
6. **Files stay under the output directory.**

---

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
- [UnrollNow](https://unrollnow.com) — public thread unrolling service
- [ytagent](https://github.com/Bilal140202/ytagent) — sibling project; the "document which doors remain open" philosophy started there

## Links

- **GitHub:** https://github.com/Bilal140202/xthread-agent
- **Issues:** https://github.com/Bilal140202/xthread-agent/issues
