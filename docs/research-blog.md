# The X Lockdown: Building a No-Auth Thread Harvester for AI Agents

> **A research document on the 2026 state of X/Twitter's public surfaces —
> what broke, what survived, and how a single-file agent routes around the
> wreckage to harvest complete threads without login, cookies, or a browser.**

---

## Abstract

This document chronicles the design, implementation, and breakthroughs of a
media-harvesting system built specifically for cloud-based AI agents. The
project began with a straightforward goal — enable an AI agent running in a
headless cloud environment to archive a public X/Twitter thread end-to-end,
without authentication of any kind. What began as a simple "try gallery-dl"
plan evolved into a three-tier pipeline that composes the last surviving
public surfaces of X into a reliable harvest path.

The research reveals a pattern that generalizes far beyond one platform: the
public web is splitting into two tiers. Human traffic sees a full product.
Machine traffic sees walls — GraphQL gates, Cloudflare challenges, IP
reputation scoring. For AI agents operating from datacenter IPs, the useful
surface of a platform is no longer the platform itself; it is the *ecosystem
of mirror workers, unrollers, and CDNs* that grew up around it. This document
maps that ecosystem for X as of September 2026, and describes how the
survivors were composed into a deterministic tool.

---

## Table of Contents

1. [The Problem: Why Agents Can't Read X Anymore](#1-the-problem)
2. [Initial Research: Mapping the Wreckage](#2-initial-research)
3. [Failure Signatures: A Field Guide](#3-failure-signatures)
4. [The Survivors](#4-the-survivors)
5. [The Composition: Three Tiers](#5-the-composition)
6. [The Multi-Video Discovery](#6-the-multi-video-discovery)
7. [Resilience Engineering](#7-resilience-engineering)
8. [Ethics of the Open Ecosystem](#8-ethics)
9. [What Will Break Next (and How to Adapt)](#9-what-will-break-next)

---

<a name="1-the-problem"></a>
## 1. The Problem: Why Agents Can't Read X Anymore

X's public API is, for practical purposes, closed. The free tier no longer
covers read access at useful volumes; paid tiers are neither agent-friendly
nor cost-appropriate for archival tasks; and the GraphQL endpoints that the
website itself uses are gated behind an authentication layer that rejects
unauthenticated reads outright.

An agent cannot:

- Run a browser with an authenticated session
- Supply cookies (no human to log in)
- Pass Cloudflare's JS challenges reliably
- Use "guest token" tricks that worked until they didn't

And when the agent runs on a datacenter IP — the default condition for every
cloud CI runner, sandbox, and AI execution environment — X's edge treats it
with maximum suspicion. The question this research set out to answer: **is
there still a path from a bare status URL to the full thread's media, with
zero credentials?**

The answer turned out to be yes — but not through X itself.

---

<a name="2-initial-research"></a>
## 2. Initial Research: Mapping the Wreckage

The first phase was systematic demolition of assumptions. Every "known"
method for fetching tweet content was tested from a datacenter IP, in order
of reputation:

1. **gallery-dl with a fresh guest token.** The guest token activates
   flawlessly — and then the `TweetResultByRestId` GraphQL call returns an
   empty or error payload. The token is a key to a door that was removed.
2. **yt-dlp on status URLs.** Same GraphQL wall, same empty payload. The tool
   is excellent; the endpoint is gone.
3. **Nitter instances.** The public network is effectively dead:
   `nitter.net` and its well-known mirrors time out or return HTTP 451. The
   project's own maintainers documented the death of public instances after
   upstream API changes.
4. **Direct scraping of x.com.** The page shell loads for datacenter IPs; the
   data never arrives. React renders nothing because the GraphQL gate behind
   it returns nothing.
5. **vxtwitter / fxtwitter viewer services.** The viewer endpoints differ:
   one presents a Cloudflare JS challenge to datacenter traffic; the other
   answers with clean JSON. (This asymmetry matters — see §4.)
6. **Sotwe / twstalker mirrors.** Cloudflare 403 across the board.
7. **The syndication endpoints** (`syndication.twitter.com`,
   `cdn.syndication.twimg.com`). The timeline-profile service rate-limits
   aggressively (HTTP 429 after a handful of calls). The per-tweet
   `tweet-result` endpoint, however, still works — and accepts any bearer
   token string, including literal junk.

Eight approaches, six dead, one rate-limited, two functional but incomplete.

---

<a name="3-failure-signatures"></a>
## 3. Failure Signatures: A Field Guide

Recognizing *how* a method fails tells you whether retrying is worthwhile:

| Signature | Meaning | Retry? |
|---|---|---|
| HTTP 200 + empty/`no results` GraphQL payload | Endpoint gated upstream | Never |
| HTTP 403 with Cloudflare challenge page | Bot-score rejection at edge | Not from this IP |
| HTTP 451 | Legal takedown of the mirror network | Never |
| HTTP 000 / connection reset | Instance dead | Not for this instance |
| HTTP 429 after N calls | Rate limit, not a wall | Yes — but slow |
| HTTP 404 from the decoder worker | ID is not a tweet (it's a media ID) | No — it's a *filter signal* |

The 404 case is the most instructive: a "failure" that is actually
information. That reframing became a core mechanism of the final pipeline.

---

<a name="4-the-survivors"></a>
## 4. The Survivors

Three public surfaces survived every test:

### 4.1 UnrollNow — the thread walker

A public unrolling service renders an entire conversation as static HTML.
Crucially, that HTML embeds **every conversation member's ID, in thread
order** — including the IDs of "amplify" media objects, which are not tweets
at all. No auth, no challenge, datacenter-friendly. It is, as of this
writing, the only public source found that lists every tweet in a thread
without credentials.

### 4.2 FixTweet (`api.fxtwitter.com`) — the metadata decoder

An open-source link-rendering worker that returns complete tweet JSON:
text, author, engagement stats, timestamps, and — critically — a decoded
`media` array. Unlike its sibling viewer, the API host does not present a
Cloudflare challenge to datacenter IPs. Its 404 responses are clean and
fast, which makes them a perfect filter for the walker's candidate list.

### 4.3 The twimg CDNs — the media plane

`video.twimg.com` and `pbs.twimg.com` serve media **without auth**, once you
hold the URL. They have never (in our testing) required a session. All
authentication burden in X's stack sits in front of *discovery*, not
*delivery*. Whoever decodes the payload can fetch the bytes.

---

<a name="5-the-composition"></a>
## 5. The Composition: Three Tiers

The insight of the final architecture is that the three survivors are
complementary layers of one pipeline:

```
DISCOVERY  →  DECODE  →  DELIVER
(UnrollNow)   (FixTweet)  (twimg CDN)
```

- The walker provides *coverage* (the whole thread, in order).
- The decoder provides *truth* (what is actually a tweet, what media it
  carries) and *filtering* (404 on media IDs).
- The CDN provides *bytes* (no auth, resumable, high throughput).

Each tier can fail independently without collapsing the run: lose the walker
and you still harvest the root tweet; lose the decoder for one ID and you
skip that ID; lose a CDN transfer and you retry, then resume on a later run
(skip-if-exists makes every run idempotent).

---

<a name="6-the-multi-video-discovery"></a>
## 6. The Multi-Video Discovery

X's UI presents one video per tweet. The uploader-side "amplify" media
system, however, permits **several videos attached to a single tweet** — a
feature invisible in the app but fully present in the decoded payload. FixTweet
returns every video with its own direct CDN URL, duration, and poster image.

This single discovery changes the economics of thread harvesting: a fan
thread that appears to be "4 tweets, 4 videos" is, in reality, frequently
"4 tweets, 11 videos." Any pipeline that trusts the UI's mental model loses
most of the media. The manifest therefore keys media per-tweet with explicit
counts, and the walker's media-ID pollution (once a bug) becomes a second
harvest path.

---

<a name="7-resilience-engineering"></a>
## 7. Resilience Engineering

Rules the tool follows so it degrades the way distributed systems should:

1. **404 is a filter, not an error.** The decoder's negative responses carry
   information; the pipeline is built to consume it.
2. **Degrade to root.** If discovery dies, one tweet is still better than
   zero — but the summary reports honest counts so the caller can tell.
3. **Idempotent runs.** `skip-if-exists` turns any crashed run into a
   resumable one. The second run never repeats completed work.
4. **Backoff with ceilings.** Three attempts, linear sleep. No infinite
   retries against a wall.
5. **Politeness floors.** ~600ms between tweets. The open services this tool
   depends on are free; the correct response to free infrastructure is
   restraint.
6. **Honest exit codes.** `ok=true` means "at least one tweet harvested," and
   the JSON summary always reports exact counts so callers can validate
   against expectations.

---

<a name="8-ethics"></a>
## 8. Ethics of the Open Ecosystem

This tool reaches only **public** content — the same bytes any visitor could
see. It does not bypass paywalls, protected accounts, or deleted media; those
fail closed by design. It depends entirely on free community infrastructure
(an unroller, an open-source worker, X's own CDN), and it treats that
infrastructure politely: low rate, small bursts, idempotent retries.

Responsibility for the *content* harvested remains with the caller. Threads
are curated by real people; the underlying media belongs to its original
rights holders. Archive with respect, credit curators, and don't monetize
what you didn't make.

---

<a name="9-what-will-break-next"></a>
## 9. What Will Break Next (and How to Adapt)

The endpoint matrix in [`endpoint-matrix.md`](endpoint-matrix.md) is a living
document. The predictable failure modes:

- **UnrollNow dies or rate-limits.** Search for other unrolling/rendering
  services that embed conversation HTML. The walker is a *slot*, not a
  brand.
- **FixTweet gates datacenter IPs.** Its sibling already did. The decoder is
  likewise a slot — the requirements are "full payload JSON, clean 404s,
  no challenge." Monitor the open-source repo for mirrors.
- **twimg CDNs start requiring signed URLs.** Then delivery becomes the
  bottleneck and the pipeline's third slot needs a proxy tier (the ytagent
  project's bypass architecture is the reference for exactly this
  eventuality).

The tool's architecture anticipates all three: every stage is a replaceable
slot with a narrow contract, documented in [`agents.md`](../agents.md). When
a door closes, find the next door that is already open — and document it.
