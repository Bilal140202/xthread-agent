# Endpoint Matrix — X/Twitter Public Surfaces (Living Reference)

> **Status as of September 2026, observed from a datacenter IP.** This is the
> operational reference behind the research blog. When something here changes,
> update the row, bump the "last verified" date, and commit.

Legend: ✅ working · ⚠️ degraded/rate-limited · ❌ dead/blocked

## Discovery (who lists the conversation?)

| Surface | Status | Failure signature | Notes |
|---|---|---|---|
| `unrollnow.com/status/<id>` | ✅ | — | Embeds candidate IDs incl. media (amplify) IDs. ⚠️ **Also embeds same-author recommendations that are NOT thread members** (verified 2026-09-24) — treat as candidates only; chain membership must come from decoder `replying_to_status`. Root may be absent for short legacy IDs. |
| `x.com` HTML shell | ❌ | Empty react root for datacenter IPs | Data gate never fires; scraping the shell is pointless. |
| Nitter public instances | ❌ | HTTP 000 / timeout, `nitter.net` 451 | Public network effectively dead since upstream API loss. |
| `syndication.twitter.com/srv/timeline-profile` | ⚠️ | HTTP 429 after a few calls | Occasionally usable for a single profile, never for a thread walk. |

## Decode (who turns an ID into tweet JSON?)

| Surface | Status | Failure signature | Notes |
|---|---|---|---|
| `api.fxtwitter.com/status/<id>` | ✅ | 404 arrives BOTH as 200-body `code:404` AND as real HTTP 404 (verify both paths!) | Full payload: text, author, stats, `media.videos[]` / `media.photos[]` with direct CDN URLs, `formats[]` variants, `quote`. Decodes multi-video "amplify" media. 404/451 = filter signal, not error. |
| `api.vxtwitter.com` | ✅ | clean 404 HTTP status for missing tweets | **Re-verified alive 2026-09-24** from a datacenter IP — the 2026-09-20 "Cloudflare challenge" row was stale. Now the fallback decoder slot (smaller payload subset, normalized). |
| `cdn.syndication.twimg.com/tweet-result` | ✅ | — | Single tweets only; no conversation traversal. Accepts any bearer token value. Good as a root-tweet sanity check (not used by the pipeline). |
| `x.com/i/api/graphql/…` (guest) | ❌ | HTTP 200 + empty/`no results` payload | Guest token activates, but the read gate rejects unauthenticated data. |
| gallery-dl guest-token path | ❌ | same as GraphQL | Tool is fine; endpoint is gone. |
| yt-dlp on status URLs | ❌ | same as GraphQL | Same wall. |

## Deliver (who serves the bytes?)

| Surface | Status | Failure signature | Notes |
|---|---|---|---|
| `video.twimg.com/...mp4` | ✅ | — | No auth once URL is known. Best-quality variant selectable. |
| `pbs.twimg.com/...jpg` | ✅ | — | Posters and photos; `?name=` param controls size. |

## Mirror/UI sites

| Surface | Status | Failure signature | Notes |
|---|---|---|---|
| sotwe.com | ❌ | Cloudflare 403 | — |
| twstalker.com | ❌ | Cloudflare 403 | — |

---

## Maintenance protocol

1. Re-verify a row by running the tool (or a curl probe) from the target
   environment class.
2. Update the row **and** the "last verified" line at the top.
3. If a ✅ row flips to ❌: open an issue, propose the replacement slot, and
   reference the research blog's "What Will Break Next" section.
4. Keep the matrix impersonal: endpoints and signatures only — no example
   targets, no harvested content, no account names.

## Field observations (2026-09-24 verification pass)

- FixTweet 404s arrive in **two shapes**: HTTP 200 + body `{"code":404}` for
  some IDs, and real `HTTP 404` statuses for others. Any probe script must
  handle both (urllib raises `HTTPError` on the second — do not retry it).
- FixTweet video payloads carry `formats[]` (container/bitrate/codec) and
  `variants[]`; the top-level `url` is the highest-bitrate mp4. m3u8-primary
  videos usually still have mp4 variants inside `formats[]`.
- UnrollNow candidate lists run ~5–11 IDs for single tweets, dominated by
  same-author recommendations in non-thread order.

*Last verified: 2026-09-24 (second pass, UTC — full pipeline E2E re-run:
metadata-only walk+decode+reconstruct, photo download, video+poster download,
and the fail-closed path for an unavailable root; all ✅ rows confirmed from
the same datacenter IP class).*
