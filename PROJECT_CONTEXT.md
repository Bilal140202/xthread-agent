# PROJECT_CONTEXT.md — Read Me Before Touching Anything

> **Who this is for:** Future Bilal (or any maintainer) who has completely
> forgotten why this project exists, what its load-bearing walls are, and
> which corners are fragile. Read this end-to-end once before changing code.
> It is opinion on purpose; the neutral specs live in `agent.md` /
> `agents.md` / `README.md`.

---

## 1. Why I originally built this

I wanted AI agents to be able to read X/Twitter content programmatically —
the same role [ytagent](https://github.com/Bilal140202/ytagent) plays for
YouTube. The official X API is priced for enterprises and useless for
archival agents; the agent runs from datacenter IPs where X blocks everything
interactive; and there is no human to log in, solve a CAPTCHA, or paste
cookies. So the question this project answers is: **given only a public
status URL, can an unauthenticated, headless, deterministic tool still
retrieve the post's thread, text, and media?** As of September 2026 the
answer is yes — but not through X's front door. It routes through the
ecosystem of open services that grew up around X.

## 2. What problem it solves

Input: one X status URL (or ID). Output: the reconstructed self-reply thread
as an enveloped JSON document (`thread_manifest.json`) plus every video and
photo in the thread as files on disk. Deterministic, no login, no API keys,
no browser, stdlib-only single file that runs anywhere Python 3.9+ exists.

## 3. The architecture (and why it is shaped like this)

Three tiers, each a *replaceable slot* with a narrow contract:

```
DISCOVERY (unrollnow.com)  →  DECODE (api.fxtwitter.com, fallback
                              api.vxtwitter.com)  →  DELIVER (*.twimg.com)
```

- X itself is never touched. Its auth wall guards discovery APIs; the twimg
  CDNs serve bytes to anyone holding the URL. Every authentication burden in
  X's stack sits in front of *discovery*, not *delivery*.
- Each tier can die independently: lose the walker → root-only harvest;
  lose the primary decoder → fallback slot; lose a transfer → retry/re-run
  (skip-if-exists makes runs idempotent).
- Everything is composed in one file (`xthread-agent.py`, ~850 lines) with
  four roles documented as contracts in `agents.md`. The single-file
  constraint is deliberate: an agent should be able to fetch ONE file and
  run it in a bare sandbox. Do not split it into a package without a very
  good reason.

## 4. How it works (the 60-second version)

1. `normalize_input` — proper URL parsing → bare status ID.
2. `resolve_thread_ids` — one GET to UnrollNow; regex-extracts *candidate*
   IDs (including media IDs and same-author recommendations — it is NOT a
   clean conversation list). Root always kept, capped at 50.
3. `fetch_tweet` — FixTweet JSON per candidate (3 tries, linear backoff).
   404/451 (both body-level and real HTTP status) = filter signal, never
   retried. Network failure → vxtwitter fallback (normalized subset,
   provenance-tagged).
4. `reconstruct_thread` — the truth layer: chain membership comes ONLY from
   `replying_to_status` (walk up from the requested root to the thread
   start, then down through same-author replies). Everything else decoded is
   counted as `related_filtered`.
5. `map_tweet`/`map_author`/`map_video`/`map_photo` — defensive mapping to
   the stable schema; explicit nulls; ISO timestamps; quoted posts one level
   deep; video variant selection (m3u8 → best mp4 in `formats[]`).
6. `download` — https + `*.twimg.com` allowlist, stream to `.part`,
   Content-Length check, atomic rename. Resumable via skip-if-exists.
7. `harvest`/`main` — envelope assembly, atomic UTF-8 manifest write,
   pipe-safe stdout/stderr split, honest exit codes (0/1/2).

## 5. Important design decisions (do not casually reverse)

1. **Single file, stdlib only.** The deployment story ("copy one file into a
   bare sandbox") is a feature. No pip, no node, no ffmpeg.
2. **Slots, not brands.** UnrollNow/FixTweet/vxtwitter are interchangeable
   implementations of discovery/decode. When one dies, replace the slot
   behind its contract (see `agents.md`) — don't restructure the pipeline.
3. **404 is a filter, not an error.** The decoder's negative responses carry
   information (media-ID candidates). Retrying them is a bug (v2 did).
4. **`replying_to_status` is the only thread truth.** Page order, "same
   author" heuristics, or first-seen ordering are NOT membership signals.
   UnrollNow pages are polluted with recommendations (verified 2026-09-24).
5. **Honesty over completeness.** `status: partial`, `errors[]`, `reason:
   "hls_only"`, `degraded_to_root_only` — the envelope always says what it
   did NOT get. Never fabricate a value; use `null`.
6. **Politeness is a hard constraint.** ~0.6s between decodes, bounded
   retries, candidate cap, body caps, one walk per run. The infrastructure
   this tool depends on is free; restraint is the rent.
7. **Data on stdout, logs on stderr, always.** Agents pipe stdout.
8. **Synthetic fixtures only in tests.** No real status IDs, account names,
   or harvested content ever gets committed (also a legal/hygiene rule).

## 6. What NOT to change casually

- The envelope field names/types (`schema/thread-result.schema.json` is the
  contract; AI agents key on it).
- Exit codes (0 = posts harvested, 1 = nothing, 2 = usage).
- stdout/stderr discipline.
- The 404/451 filter semantics in `_fetch_fxtweet` — adding retries back
  reintroduces the v2 retry storm.
- The `.part` + `os.replace` discipline in `download`/`_write_manifest` —
  it is what makes crashes non-corrupting.
- The media-URL allowlist (`_media_url_allowed`) and ID validation
  (`_safe_id`) — they are the security boundary against compromised decoder
  payloads.
- The politeness constants (`DECODE_SLEEP`, `MAX_CANDIDATES`,
  `MAX_ANCESTORS`).

## 7. Known limitations (documented honestly, accepted for now)

- Linear self-reply chains only; branching takes the first-seen branch.
- Quoted-post media recorded as URLs, not downloaded.
- Depends on free third-party services (UnrollNow, FixTweet, vxtwitter);
  any of them gating datacenter IPs degrades the tool (root-only or empty).
- Slow-drip transfers are cut at the deadline and restarted, not byte-resumed.
- One run per output directory at a time (no locking).
- t.co shortlinks are not resolved (would need a redirect-following step).
- Some X surfaces (communities, articles, polls-as-content) are not modeled.

## 8. Known fragile components (ranked by fragility)

1. **UnrollNow HTML structure** — the walker regexes depend on IDs appearing
   in the HTML. A redesign → `E_WALKER_EMPTY`/`E_WALKER_UNAVAILABLE`
   (degrades to root-only; the envelope will tell you). Replace the slot if
   it dies.
2. **FixTweet availability/edge policy** — if it gates datacenter IPs, the
   fallback slot (vxtwitter) takes over automatically, but vxtwitter's
   subset lacks some fields (views, bookmarks, quotes → null).
3. **FixTweet payload schema** — field drift would surface as nulls in the
   manifest. The mappers are defensive (``.get()`` everywhere) so drift
   degrades, never crashes.
4. **twimg CDN access rules** — if signed URLs ever become mandatory,
   delivery breaks and the pipeline needs a proxy tier (ytagent's bypass
   architecture is the reference).
5. **URL formats** — `normalize_input` covers x.com/twitter.com forms; new
   X URL shapes (e.g. new path suffixes) may need additions.

When something breaks: run `demo.py` on a known-good public post, check
`errors[]` in the manifest, consult `docs/endpoint-matrix.md`, verify the
suspect endpoint with curl from the same IP class, update the matrix row.

## 9. How to test it

```bash
# offline suite (89 tests, ~0.3s, no network)
cd tests && python3 -m unittest discover -p "test_*.py" -v

# live smoke (polite: one thread, ideally one you control)
python3 demo.py "https://x.com/<user>/status/<id>" --out /tmp/demo_out
python3 demo.py "<url>" --skip-download          # metadata only
python3 xthread-agent.py "<url>" --json --quiet  # raw agent contract
```

Live checks worth doing after big changes: photos download and are real
JPEGs; videos download and are real MP4s; a 2+ post self-reply thread
reconstructs in order with `related_filtered` > 0; a deleted post yields
`status: empty` + exit 1; re-running skips completed files.

## 10. Possible future directions (realistic only)

- A t.co resolver slot (follow one redirect) for shortlink inputs.
- A second walker slot (e.g. threadreaderapp or syndication-based) so
  discovery is dual-homed like decoding.
- Optional byte-range resume for very large videos.
- An MCP wrapper exposing the CLI as a tool for MCP-compatible agents
  (keep core stdlib-only; the wrapper can require deps).
- Media type expansion: GIFs are mp4s already; polls/cards/communities are
  out of scope until a decoder exposes them cleanly.
- A `--from-file` batch mode (still serialized, still polite).

## 11. What remains unfinished / known debts

- The QA review (2026-09-24) flagged two accepted-and-documented residuals:
  decoder redirects are followed by default (no cross-host guard) — the
  `agents.md` Role 2 "no redirects" line was relaxed accordingly; and the
  per-socket timeout is not a hard wall-clock bound for `http_get` small
  payloads (only downloads have a transfer deadline).
- `decoded_tweets` counts ancestors cached during the ancestor walk —
  semantics are documented in the schema but could be split further.
- No CI (GitHub Actions) yet — the suite is offline and fast; wiring it up
  is a 10-line workflow.
- v2→v3 consumers: any script reading the bare-array manifest must migrate
  to `.posts[]` (migration note in RELEASE_NOTES.md).

## 12. Field-provenance note

The endpoint claims in `docs/endpoint-matrix.md` were verified from a
datacenter IP on 2026-09-24 with a small number of polite probes (public
posts only). When you re-verify, update the "last verified" line — that line
is the load-bearing trust anchor of the whole matrix.
