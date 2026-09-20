# Endpoint Matrix — X/Twitter Public Surfaces (Living Reference)

> **Status as of September 2026, observed from a datacenter IP.** This is the
> operational reference behind the research blog. When something here changes,
> update the row, bump the "last verified" date, and commit.

Legend: ✅ working · ⚠️ degraded/rate-limited · ❌ dead/blocked

## Discovery (who lists the conversation?)

| Surface | Status | Failure signature | Notes |
|---|---|---|---|
| `unrollnow.com/status/<id>` | ✅ | — | Embeds every conversation member ID in thread order, incl. media (amplify) IDs. The only working no-auth thread walker found. |
| `x.com` HTML shell | ❌ | Empty react root for datacenter IPs | Data gate never fires; scraping the shell is pointless. |
| Nitter public instances | ❌ | HTTP 000 / timeout, `nitter.net` 451 | Public network effectively dead since upstream API loss. |
| `syndication.twitter.com/srv/timeline-profile` | ⚠️ | HTTP 429 after a few calls | Occasionally usable for a single profile, never for a thread walk. |

## Decode (who turns an ID into tweet JSON?)

| Surface | Status | Failure signature | Notes |
|---|---|---|---|
| `api.fxtwitter.com/status/<id>` | ✅ | clean 404 for non-tweet IDs | Full payload: text, author, stats, `media.videos[]` / `media.photos[]` with direct CDN URLs. Decodes multi-video "amplify" media. 404 = filter signal, not error. |
| `api.vxtwitter.com` | ❌ | Cloudflare JS challenge | Sibling service, different edge policy. Re-check periodically. |
| `cdn.syndication.twimg.com/tweet-result` | ✅ | — | Single tweets only; no conversation traversal. Accepts any bearer token value. Good as a root-tweet sanity check. |
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

*Last verified: 2026-09-20.*
