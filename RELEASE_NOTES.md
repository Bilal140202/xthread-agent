# Release Notes

## v3.0.0 — 2026-09-24

The reliability release: true thread reconstruction, a fallback decoder slot,
hardened data integrity, a machine-readable envelope, and the project's first
test suite (89 tests). Built on a full re-verification of every endpoint from
a datacenter IP.

### ⚠️ BREAKING — manifest schema

`thread_manifest.json` changed from a **bare tweet array** (v2) to an
**enveloped document** (`schema_version: "3.0"`): `{schema_version, source,
request, status, thread, posts[], errors[], metadata}`. The v2 array shape is
preserved as the `posts` array. Formal JSON Schema:
`schema/thread-result.schema.json`. Agents pinned to v2 must read
`.posts[]` instead of the top-level array.

### Fixed (live-verified defects)

- **False thread members** (v2 correctness bug): UnrollNow pages embed
  same-author *recommendations* alongside the conversation; v2 harvested them
  as thread members. v3 reconstructs the true self-reply chain from
  `replying_to_status` (walking up to the thread start and down through
  replies) and counts excluded recommendations (`related_filtered`).
- **Root dropped for short legacy IDs** (v2 correctness bug): the walker
  regex (`\d{15,25}`) could not see e.g. `status/20`, silently excluding the
  root from harvesting. v3 guarantees the root is always present.
- **404 retry storm**: FixTweet returns real HTTP 404 statuses for
  unavailable tweets; urllib raises `HTTPError`, which v2 retried 3× with
  backoff before treating it as a filter. v3 treats HTTP 404/451 as instant
  filter signals (both response shapes).
- **Non-atomic downloads** (v2 integrity bug): a crash mid-write left a
  partial file that skip-if-exists treated as complete forever. v3 streams to
  `.part`, verifies against `Content-Length`, and atomically renames.
- **`write_text` without explicit encoding** (v2 mojibake risk): manifest now
  written UTF-8, atomically.
- **Python 3.9 support was broken** in v2 (PEP-604 annotations evaluated
  eagerly); v3 adds `from __future__ import annotations` — the advertised
  3.9+ is now true.

### Added

- Input normalization: proper URL parsing (x.com/twitter.com, mobile./www.,
  `/statuses/`, `/photo/<n>`, `/video/<n>`, query strings, bare IDs) with
  `E_INVALID_INPUT` rejection for non-status URLs.
- **Fallback decoder slot** (vxtwitter): used automatically when FixTweet
  fails network-side; payloads normalized to an honest subset, provenance
  recorded per post (`extraction_source`).
- **Enveloped manifest** with `status` (`ok`/`partial`/`empty`), structured
  `errors[]` (stable codes: `E_WALKER_UNAVAILABLE`, `E_WALKER_EMPTY`,
  `E_ROOT_UNAVAILABLE`, `E_DECODE_FAILED`, `E_DOWNLOAD_FAILED`,
  `E_MANIFEST_WRITE_FAILED`, `E_INVALID_INPUT`), and extraction statistics.
- Full author mapping (name, id, verified, protected, followers, avatar,
  banner, joined, website, …), post metrics incl. quotes/bookmarks, `lang`,
  posting client, `replying_to(_status)`, ISO-8601 UTC timestamps.
- **Quoted posts** recorded one level deep, including the quoted post's
  author, text, timestamps, and media URLs.
- Video `formats[]` variants (container/bitrate/codec) preserved; **m3u8-only
  videos now fall back to the highest-bitrate mp4 variant** instead of being
  skipped; non-downloadable videos explained (`downloadable: false`,
  `reason: "hls_only" | "no_mp4_variant"`).
- Candidate cap (50, root kept), response body caps (20 MB walk / 5 MB
  decode), transfer deadline against slow-drip servers.
- Security hardening: media fetches restricted to `https://*.twimg.com`;
  remote tweet IDs validated (`\d{1,25}`) before use in filenames.
- `demo.py` — minimal end-to-end consumption example.
- `tests/` — 89 offline tests (stdlib `unittest`, synthetic fixtures): URL
  normalization, walker, decoders, fallback slot, chain reconstruction,
  mapping, atomic downloads, envelope contract, CLI behavior.

### Changed

- `--json` summary gains additive fields (`status`, `canonical_url`,
  `downloaded`, `failed_downloads`, `errors`); all v2 fields keep their
  meaning.
- `downloaded` now means "file exists on disk" (v2 could report `true` under
  `--no-download`); with `--no-download`, `file` is `null`.
- Human summary lines (`[done]`, post-run warnings) moved to stderr —
  stdout is data-only in every mode.
- Filter logging is honest: media-ID candidates log `[skip] … not a tweet`,
  real decode failures log `[warn] … decode failed`; the misleading v2
  "[warn] unavailable — skipping" per media-ID is gone.
- `harvest()` signature extended (`request_info`, `decode_sleep`) and now
  returns the envelope dict (was: posts list) — see agents.md Role 4.
- README, agent.md, agents.md, endpoint-matrix updated; endpoint matrix
  re-verified 2026-09-24 (vxtwitter row corrected: alive, not Cloudflare-
  blocked; UnrollNow row corrected: candidates ≠ conversation).

### Removed

- `extract_status_id` (loose regex that matched any 10–25 digit number
  anywhere in a string) — replaced by `normalize_input`.

## v2.0.0 — 2026-09-20

The professional release: same three-tier pipeline, hardened contracts,
full documentation suite, and a machine-readable interface.

### Added
- `--json` flag: pipe-safe summary object on stdout (logs stay on stderr).
- `--quiet` flag: silence stderr logs.
- `--version` flag: semver output.
- Honest exit codes: `0` = at least one tweet harvested, `1` = nothing.
- `downloaded` boolean per media item in the manifest (works with
  `--no-download`, where `file` is `null` and `url` is always populated).
- `agent.md` — complete self-sufficient operating manual for AI agents.
- `agents.md` — perfection-based role prompts for the internal roster
  (Thread Walker, Metadata Decoder, Media Fetcher, Orchestrator).
- `docs/research-blog.md` — full research chronicle of the X lockdown and
  the three-tier bypass architecture.
- `docs/endpoint-matrix.md` — living endpoint status reference with
  maintenance protocol.

### Changed
- 404 from the decoder is now handled as an explicit *filter signal*
  (previously retried): media-ID candidates are skipped silently.
- Root-tweet fallback when the thread walk fails is logged as a warning
  and reflected in the summary (`tweets` count).
- README rewritten around the agent contract: quickstart, JSON schema,
  decision tree, constraints, documentation map.

### Removed
- All example targets and test artifacts from documentation. The tool's
  provenance is documented generically (scale, runtime, outcome) — no
  harvested content, account names, or status IDs appear anywhere in the
  repository.

## v1.0.0 — 2026-09-20

Initial release: single-file harvester with UnrollNow thread walk, FixTweet
decoding, resumable twimg CDN downloads, and `thread_manifest.json` output.
Validated end-to-end on a real multi-video fan thread (11 videos, 4 tweets,
~33 MB, under two minutes, zero auth).
