# Release Notes

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
