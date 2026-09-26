#!/usr/bin/env python3
"""
xthread-agent — X/Twitter thread content & media harvester for AI agents
=========================================================================
A deterministic, self-contained agent that, given any public X status URL:

  1. Normalizes & validates the input URL/ID (t.co shortlinks are resolved
     through one network hop first)
  2. Resolves thread candidates via walker slots — UnrollNow primary,
     ThreadReaderApp fallback (root always kept; degraded to root-only
     when every slot fails)
  3. Fetches each tweet's metadata (text, author, stats, media) via FixTweet,
     with vxtwitter as an automatic fallback decoder slot
  4. Reconstructs the true self-reply chain from `replying_to_status`
     (walking up to the thread start and down through replies), excluding
     unrelated same-author recommendations
  5. Downloads every video (best-quality mp4, streaming, atomic writes),
     poster thumbnails and photos
  6. Emits `thread_manifest.json` — an enveloped, machine-readable result
     (schema_version 3.0) with posts, errors, and extraction metadata

Pipeline (no login, no API keys, no browser):
  Tier 1  UnrollNow            — thread candidate walk (ordered candidate IDs)
         (ThreadReaderApp      — fallback walker slot, used when the primary
          fallback)              slot fails or yields no candidates
  Tier 2  FixTweet API         — per-tweet metadata decode incl. multi-video
                                 "amplify" media with direct twimg CDN URLs
         (vxtwitter fallback   — used only when FixTweet fails network-side)
  Tier 3  video/pbs.twimg.com  — CDN fetch, no auth needed once URL is known

Usage:
  python3 xthread-agent.py <status_url_or_id> [--out DIR] [--no-download]
                            [--json] [--quiet] [--version]

Exit codes: 0 = at least one post harvested, 1 = nothing harvested / error,
            2 = usage error (argparse).

v3 note: the manifest changed from a bare tweet array (v2) to an enveloped
document. See RELEASE_NOTES.md for the migration note.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import argparse
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

__version__ = "3.2.0"
SCHEMA_VERSION = "3.0"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

LOG_QUIET = False

# Politeness / safety bounds
DECODE_SLEEP = 0.6        # seconds between decoder calls
MAX_CANDIDATES = 50       # hard cap on walker candidates decoded per run
MAX_ANCESTORS = 25        # hard cap on ancestor walk-up fetches
DOWNLOAD_TIMEOUT = 180    # seconds per media transfer attempt
DECODE_TIMEOUT = 30       # seconds per decoder attempt
WALK_TIMEOUT = 40         # seconds for the thread walk

# Error codes (stable, machine-readable)
E_INVALID_INPUT = "E_INVALID_INPUT"
E_ROOT_UNAVAILABLE = "E_ROOT_UNAVAILABLE"
E_WALKER_UNAVAILABLE = "E_WALKER_UNAVAILABLE"
E_WALKER_EMPTY = "E_WALKER_EMPTY"
E_DECODE_FAILED = "E_DECODE_FAILED"
E_DOWNLOAD_FAILED = "E_DOWNLOAD_FAILED"
E_MANIFEST_WRITE_FAILED = "E_MANIFEST_WRITE_FAILED"

# Response body caps (a malicious/broken source must not exhaust memory)
WALK_MAX_BYTES = 20 * (1 << 20)   # 20 MB — UnrollNow pages are ~1 MB today
DECODE_MAX_BYTES = 5 * (1 << 20)  # 5 MB — FixTweet payloads are a few hundred KB

# Media downloads are restricted to X's media CDN hosts (defense in depth:
# media URLs come from third-party decoder payloads and must never be able to
# make this tool fetch local files or internal network resources).
MEDIA_HOST_SUFFIX = ".twimg.com"

# Shared error sink: stages append here; the orchestrator snapshots into
# the envelope's `errors` array. Cleared at the start of each harvest.
ERRORS: list[dict] = []

SUPPORTED_HOSTS = {"x.com", "twitter.com", "mobile.x.com", "mobile.twitter.com"}
TCO_HOSTS = {"t.co", "www.t.co"}

# Walker slots, in priority order. Each is a replaceable implementation of
# the discovery contract: given a root ID, return a page whose status/<id>
# occurrences are candidate IDs (slot names appear in the envelope's
# thread.walker_slot so callers know who served the walk).
WALKER_SLOTS = (
    ("unrollnow", "https://unrollnow.com/status/{root}"),
    ("threadreaderapp", "https://threadreaderapp.com/thread/{root}"),
)


def log(msg: str) -> None:
    if not LOG_QUIET:
        print(msg, file=sys.stderr)


def record_error(stage: str, code: str, message: str, subject: str | None = None) -> None:
    """Append a structured error to the shared sink (snapshot into envelope)."""
    ERRORS.append({"stage": stage, "code": code, "message": message, "subject": subject})


# ── Input normalization & validation ─────────────────────────────────────────
class InputError(Exception):
    """Invalid or unsupported input. Carries a stable error code."""

    def __init__(self, message: str, code: str = E_INVALID_INPUT):
        super().__init__(message)
        self.code = code


def normalize_input(inp: str) -> dict:
    """Parse a status URL or bare status ID into {status_id, canonical_url}.

    Accepts:
      - https://x.com/<user>/status/<id>            (also /statuses/)
      - https://twitter.com/<user>/status/<id>      (and mobile./www. forms)
      - trailing /photo/<n>, /video/<n>, /media suffixes and query strings
      - https://x.com/i/web/status/<id>
      - a bare numeric status ID (1-25 digits)

    Rejects non-status URLs (profiles, hashtags, search, other hosts) with a
    stable error code so callers can branch on failure deterministically.
    """
    text = (inp or "").strip()
    if not text:
        raise InputError("empty input — provide an X/Twitter status URL or status ID")
    if re.fullmatch(r"\d{1,25}", text):
        sid = text
    else:
        raw = text if "://" in text else "https://" + text
        parsed = urllib.parse.urlparse(raw)
        host = (parsed.hostname or "").lower()
        host = host[4:] if host.startswith("www.") else host
        if host not in SUPPORTED_HOSTS:
            raise InputError(
                f"unsupported host '{host or '(none)'}' — expected x.com or twitter.com status URL")
        parts = [p for p in parsed.path.split("/") if p]
        sid = None
        for i, p in enumerate(parts):
            if p in ("status", "statuses"):
                if i + 1 >= len(parts) or not parts[i + 1].isdigit() or len(parts[i + 1]) > 25:
                    raise InputError("URL contains /status/ but no valid numeric status ID")
                sid = parts[i + 1]
                break
        if sid is None:
            raise InputError(
                "not a status URL — expected https://x.com/<user>/status/<id> or a bare status ID")
    return {
        "status_id": sid,
        "canonical_url": f"https://x.com/i/web/status/{sid}",
        "input": text,
    }


def is_tco(inp: str) -> bool:
    """True when the input is a t.co shortlink (any scheme-less form too)."""
    text = (inp or "").strip()
    if not text or "://" not in text:
        text = "https://" + text
    try:
        host = (urllib.parse.urlparse(text).hostname or "").lower()
    except ValueError:
        return False
    return host in TCO_HOSTS


def _interstitial_dest(body: str) -> str | None:
    """Extract the destination from a t.co HTML interstitial (t.co serves a
    200 page embedding the target instead of an HTTP redirect for some
    clients). Handles both shapes it emits: <noscript> meta-refresh and
    location.replace(...). Returns None when neither is present."""
    m = re.search(r"http-equiv=[\"']?refresh[\"']?[^>]*?"
                  r"content=[\"'][^\"']*?url=([^\"'>]+)", body, re.I | re.S)
    if m:
        return m.group(1).strip()
    m = re.search(r"location\.replace\(\s*[\"']((?:[^\"'\\]|\\.)*)[\"']\s*\)", body)
    if m:
        return m.group(1).replace("\\/", "/").strip()
    return None


def expand_tco(inp: str, timeout: int = DECODE_TIMEOUT) -> str:
    """Resolve a t.co shortlink to its destination URL (one network hop).

    t.co is X's canonical URL wrapper; a status link's destination is an
    x.com/twitter.com status URL. Two resolution paths, both honest:

      1. HTTP redirect — urllib follows it; the final URL is used.
      2. HTML interstitial — for some clients t.co answers 200 with a page
         embedding the target in a <noscript> meta-refresh or a
         location.replace() call; the embedded URL is parsed from the body
         (never executed).

    Raises InputError on failure: network error, an unparseable interstitial,
    or a destination that does not point at a supported X/Twitter host.
    Callers re-normalize the returned URL, so 't.co → non-status page' fails
    with the normal not-a-status-URL error instead of a silent wrong result.
    """
    text = (inp or "").strip()
    if not text:
        raise InputError("empty input — provide an X/Twitter status URL or status ID")
    raw = text if "://" in text else "https://" + text
    try:
        host0 = (urllib.parse.urlparse(raw).hostname or "").lower()
    except ValueError:
        raise InputError(f"not a t.co shortlink: '{inp[:60]}'")
    if host0 not in TCO_HOSTS:
        raise InputError(f"not a t.co shortlink: '{host0 or '(none)'}'")
    try:
        req = urllib.request.Request(raw, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(1 << 14).decode("utf-8", "replace")  # interstitials are tiny
            dest = r.geturl()
    except Exception as e:
        raise InputError(f"t.co resolution failed: {e}")
    host = (urllib.parse.urlparse(dest).hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    if host in TCO_HOSTS:
        # final URL is still t.co: dead link, or a non-HTTP-redirect
        # interstitial — parse the embedded target out of the page body
        embedded = _interstitial_dest(body)
        if embedded:
            dest = embedded
            host = (urllib.parse.urlparse(dest).hostname or "").lower()
            host = host[4:] if host.startswith("www.") else host
        else:
            raise InputError("t.co did not redirect to a status URL "
                             "(dead link or unparseable interstitial)")
    if host not in SUPPORTED_HOSTS:
        raise InputError(
            f"t.co link does not point at an X/Twitter status URL "
            f"(resolved host '{host or '(none)'}')")
    return dest


def http_get(url: str, timeout: int = DECODE_TIMEOUT, max_bytes: int | None = None) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        if max_bytes is None:
            return r.read()
        return r.read(max_bytes)


def _media_url_allowed(url: str) -> bool:
    """Only https URLs on X's media CDN may be fetched into the output dir."""
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False
    return (parsed.scheme == "https"
            and bool(parsed.hostname)
            and parsed.hostname.lower().endswith(MEDIA_HOST_SUFFIX))


def _safe_id(value) -> str | None:
    """Remote tweet IDs are used in filenames — only plain digits survive."""
    s = str(value) if value is not None else ""
    return s if re.fullmatch(r"\d{1,25}", s) else None


def _url_is_mp4(url: str | None) -> bool:
    """True when the URL's path ends in .mp4 (query strings excluded)."""
    if not url:
        return False
    try:
        return urllib.parse.urlparse(url).path.lower().endswith(".mp4")
    except ValueError:
        return False


# ── Tier 1: Thread Walker ────────────────────────────────────────────────────
def _extract_candidate_ids(raw: str, root_id: str) -> list[str]:
    """Extract ordered, deduped candidate IDs from a walker page, with the
    root always kept and the list capped at MAX_CANDIDATES (root never
    dropped by the cap). Shared by every walker slot."""
    ids = re.findall(r"status/(\d{15,25})", raw)
    ids += re.findall(r"\b(21\d{17,22})\b", raw)  # bare snowflake-ish ids
    seen, ordered = set(), []
    for i in ids:
        if i not in seen:
            seen.add(i)
            ordered.append(i)
    if root_id in seen:
        # Walker order is the candidate spine; keep it, root at its seen spot.
        candidates = ordered
    else:
        candidates = [root_id] + ordered  # root guarantee (e.g. short legacy IDs)
    if len(candidates) > MAX_CANDIDATES:
        # Cap without ever dropping the root.
        rest = [c for c in candidates if c != root_id]
        keep_rest = rest[:MAX_CANDIDATES - 1]
        log(f"[warn] {len(candidates)} candidates capped to {1 + len(keep_rest)}")
        candidates = ([root_id] if root_id not in seen else []) + keep_rest
        if root_id not in candidates:
            candidates = [root_id] + candidates[:MAX_CANDIDATES - 1]
    return candidates


def _walk_slot(slot: str, url: str, root_id: str) -> list[str] | None:
    """Query one walker slot. Returns its candidate list, or None when the
    slot failed (network) or yielded no conversation candidates (page-shape
    drift) — both are 'slot down' signals for the caller's fallback logic.
    The root guarantee is enforced by _extract_candidate_ids either way."""
    try:
        raw = http_get(url, timeout=WALK_TIMEOUT,
                       max_bytes=WALK_MAX_BYTES).decode("utf-8", "replace")
    except Exception as e:
        log(f"[warn] walker slot '{slot}' failed ({e})")
        record_error("walker", E_WALKER_UNAVAILABLE,
                     f"walker slot '{slot}' unavailable: {e}", subject=root_id)
        return None
    candidates = _extract_candidate_ids(raw, root_id)
    if len(candidates) <= 1:
        log(f"[warn] walker slot '{slot}' returned no conversation candidates "
            "(page layout change?)")
        record_error("walker", E_WALKER_EMPTY,
                     f"walker slot '{slot}' returned no conversation candidates",
                     subject=root_id)
        return None
    log(f"[ok ] walker slot '{slot}': {len(candidates)} candidate ids")
    return candidates


def resolve_thread_ids(root_id: str) -> tuple[list[str], str]:
    """Walk the thread via the walker slots, in order; root only when all fail.

    Slot 1 is UnrollNow, slot 2 is ThreadReaderApp. Both embed the raw page
    conversation plus noise (media (amplify) IDs, same-author recommendations,
    unrelated shares) — their output is strictly *candidates*. A later
    FixTweet 404 on an ID is the signal that the ID was a media ID
    (404 = filter, not failure), and chain reconstruction (downstream)
    excludes recommendations.

    The root ID is ALWAYS present in the returned list (prepended if the
    slots' pages missed it — e.g. short legacy IDs the regex cannot see).

    Returns (candidates, walker_slot) where walker_slot names the slot that
    served the walk, or "none" when every slot failed and the walk degraded
    to root-only. Politeness: at most one request per slot per run.
    """
    for name, template in WALKER_SLOTS:
        candidates = _walk_slot(name, template.format(root=root_id), root_id)
        if candidates:
            return candidates, name
    log("[warn] all walker slots failed — degrading to root only")
    return [root_id], "none"


# ── Tier 2: Metadata Decoder ─────────────────────────────────────────────────
def _fetch_fxtweet(tid: str, tries: int) -> tuple[dict | None, str]:
    """FixTweet slot. Returns (tweet_payload | None, outcome) where outcome is
    'ok' | 'unavailable' (clean 404 — filter signal, never retried) | 'failed'."""
    url = f"https://api.fxtwitter.com/status/{tid}"
    for attempt in range(1, tries + 1):
        try:
            body = http_get(url, timeout=DECODE_TIMEOUT, max_bytes=DECODE_MAX_BYTES)
            data = json.loads(body.decode("utf-8"))
            if data.get("code") == 200 and isinstance(data.get("tweet"), dict):
                return data["tweet"], "ok"
            if data.get("code") == 404:
                return None, "unavailable"  # media id or unavailable — filter silently
            log(f"[..] {tid}: code={data.get('code')} (try {attempt})")
        except urllib.error.HTTPError as e:
            # Unavailability can arrive as a REAL HTTP 404/451 status, not just
            # a 200-body — both are filter signals, never retry-worthy.
            if e.code in (404, 451):
                if e.code != 404:
                    log(f"[skip] {tid}: HTTP {e.code} (unavailable)")
                return None, "unavailable"
            log(f"[..] {tid}: HTTP {e.code} (try {attempt})")
        except Exception as e:
            log(f"[..] {tid}: {e} (try {attempt})")
        if attempt < tries:
            time.sleep(2 * attempt)
    return None, "failed"


def _normalize_vxtweet(vx: dict, depth: int = 0) -> dict | None:
    """Normalize a vxtwitter payload into the FixTweet-shaped subset we consume.
    Fields the fallback does not provide become explicit nulls (honest subset)."""
    if not isinstance(vx, dict) or not vx.get("tweetID"):
        return None
    media = {"photos": [], "videos": []}
    for m in vx.get("media_extended") or []:
        if not isinstance(m, dict):
            continue
        if m.get("type") == "photo":
            media["photos"].append({"url": m.get("url"), "alt_text": None,
                                    "width": m.get("width"), "height": m.get("height")})
        elif m.get("type") == "video":
            media["videos"].append({"url": m.get("url"),
                                    "thumbnail_url": m.get("thumbnail_url"),
                                    "duration": m.get("duration"),
                                    "width": m.get("width"), "height": m.get("height")})
    norm = {
        "id": str(vx.get("tweetID")),
        "url": vx.get("tweetURL"),
        "text": vx.get("text"),
        "created_at": vx.get("date"),
        "created_timestamp": vx.get("date_epoch"),
        "lang": vx.get("lang"),
        "author": {"screen_name": vx.get("user_screen_name"),
                   "name": vx.get("user_name"),
                   "avatar_url": vx.get("user_avatar_url")},
        "media": media,
        "likes": vx.get("likes"), "retweets": vx.get("retweets"),
        "replies": vx.get("replies"), "views": None,
        "quotes": None, "bookmarks": None,
        "replying_to": vx.get("replyingTo"),
        "replying_to_status": vx.get("replyingToID"),
        "quote": None,
        "_extraction_source": "vxtwitter",
    }
    if depth < 1 and isinstance(vx.get("qrt"), dict):
        norm["quote"] = _normalize_vxtweet(vx["qrt"], depth + 1)
    return norm


def _fetch_vxtweet(tid: str, tries: int = 2) -> dict | None:
    """Fallback decoder slot (vxtwitter). Used ONLY when the primary decoder
    fails network-side — a clean FixTweet 404 is trusted as a filter signal."""
    url = f"https://api.vxtwitter.com/status/{tid}"
    for attempt in range(1, tries + 1):
        try:
            body = http_get(url, timeout=DECODE_TIMEOUT, max_bytes=DECODE_MAX_BYTES)
            data = json.loads(body.decode("utf-8"))
            norm = _normalize_vxtweet(data)
            if norm is not None:
                log(f"[ok ] {tid}: decoded via fallback decoder")
                return norm
            log(f"[..] {tid}: fallback returned unusable payload (try {attempt})")
        except urllib.error.HTTPError as e:
            if e.code in (404, 451):
                return None  # genuinely unavailable — do not retry
            log(f"[..] {tid}: fallback HTTP {e.code} (try {attempt})")
        except Exception as e:
            log(f"[..] {tid}: fallback {e} (try {attempt})")
        if attempt < tries:
            time.sleep(2 * attempt)
    return None


def fetch_tweet(tid: str, tries: int = 3) -> dict | None:
    """Decode one tweet. Returns the payload dict, or None if the ID is not a
    live tweet (filter) or both decoder slots failed (error recorded)."""
    tw, outcome = _fetch_fxtweet(tid, tries)
    if outcome == "ok":
        if _safe_id(tw.get("id")) is None:
            log(f"[warn] {tid}: decoder returned a bogus tweet id — rejected")
            return None
        tw["_extraction_source"] = "fxtwitter"
        return tw
    if outcome == "unavailable":
        log(f"[skip] {tid}: not a tweet (media id or unavailable)")
        return None
    fallback = _fetch_vxtweet(tid)
    if fallback is not None:
        return fallback
    log(f"[warn] {tid}: decode failed after {tries} attempts (both slots)")
    record_error("decoder", E_DECODE_FAILED,
                 f"decode failed after {tries} attempts (primary + fallback)", subject=tid)
    return None


# ── Thread reconstruction ────────────────────────────────────────────────────
def reconstruct_thread(root_id: str, decoded: dict, fetch,
                       max_ancestors: int = MAX_ANCESTORS,
                       inter_fetch_sleep: float = DECODE_SLEEP) -> tuple[list[dict], dict]:
    """Rebuild the true self-reply chain from decoded payloads.

    Chain membership is decided by `replying_to_status`, NOT by page order:
      - walk UP from the requested root to the true thread start (fetching
        missing ancestors through the decoder, same author only),
      - walk DOWN through self-replies whose parent is already in the chain.

    Decoded tweets that never chain (same-author recommendations, other
    replies) are excluded. Returns (ordered_payloads, stats).
    """
    root_tw = decoded[root_id]
    author = (root_tw.get("author") or {}).get("screen_name")

    ancestors: list[dict] = []
    seen = {root_id}
    cur = root_tw
    while len(ancestors) < max_ancestors:
        raw_parent = cur.get("replying_to_status")
        parent_id = str(raw_parent) if raw_parent else None
        if not parent_id or parent_id in seen:
            break
        # Reuse an already-decoded ancestor before spending a network call.
        parent = decoded.get(parent_id)
        if parent is None:
            if inter_fetch_sleep:
                time.sleep(inter_fetch_sleep)
            parent = fetch(parent_id)
        if parent is None:
            break  # cannot verify ancestry — stop honestly
        if ((parent.get("author") or {}).get("screen_name")) != author:
            break  # crossed out of the self-reply chain
        ancestors.append(parent)
        seen.add(parent_id)
        decoded[parent_id] = parent  # cache so stats stay honest
        cur = parent

    children: dict[str, list[dict]] = {}
    for tid, tw in decoded.items():
        if tid == root_id or tid in seen:
            continue
        rts = tw.get("replying_to_status")
        if rts:
            children.setdefault(str(rts), []).append(tw)

    chain = list(reversed(ancestors)) + [root_tw]
    cur = root_id
    while True:
        kids = [k for k in children.get(cur, [])
                if (k.get("author") or {}).get("screen_name") == author
                and k.get("id") not in seen]
        if not kids:
            break
        nxt = kids[0]  # first-seen candidate order; linear chain approximation
        chain.append(nxt)
        seen.add(nxt.get("id"))
        cur = nxt.get("id")

    stats = {"ancestors_fetched": len(ancestors), "chain_length": len(chain)}
    return chain, stats


# ── Payload mapping (FixTweet/vxtwitter → stable schema) ─────────────────────
def _iso_from(unix_ts) -> str | None:
    try:
        if unix_ts is None:
            return None
        return datetime.fromtimestamp(int(unix_ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def map_author(a: dict | None) -> dict:
    a = a or {}
    ver = a.get("verification") or {}
    website = a.get("website") or {}
    return {
        "id": a.get("id"),
        "screen_name": a.get("screen_name"),
        "name": a.get("name"),
        "description": a.get("description"),
        "location": a.get("location") or None,
        "avatar_url": a.get("avatar_url"),
        "banner_url": a.get("banner_url"),
        "followers": a.get("followers"),
        "following": a.get("following"),
        "media_count": a.get("media_count"),
        "verified": bool(ver.get("verified", a.get("verified") or False)),
        "protected": bool(a.get("protected", False)),
        "joined": a.get("joined"),
        "website": {"url": website.get("url"), "display_url": website.get("display_url")}
                  if website.get("url") else None,
    }


def _best_mp4_variant(v: dict) -> dict | None:
    """Pick the highest-bitrate mp4 variant from formats[]/variants[]."""
    variants = []
    for f in (v.get("formats") or []):
        if isinstance(f, dict) and (f.get("container") == "mp4"
                                    or _url_is_mp4(f.get("url"))):
            variants.append({"url": f.get("url"), "bitrate": f.get("bitrate") or 0,
                             "codec": f.get("codec"), "container": "mp4"})
    if not variants:
        return None
    variants.sort(key=lambda x: x["bitrate"] or 0, reverse=True)
    return variants[0]


def map_video(v: dict) -> dict:
    v = v or {}
    url = v.get("url")
    playlist_url = None
    chosen = url
    if url and ".m3u8" in url:
        best = _best_mp4_variant(v)
        if best and best.get("url"):
            playlist_url, chosen = url, best["url"]
    variants = []
    for f in (v.get("formats") or [])[:10]:
        if isinstance(f, dict) and f.get("url"):
            variants.append({"url": f["url"], "container": f.get("container"),
                             "bitrate": f.get("bitrate"), "codec": f.get("codec")})
    return {
        "url": chosen,
        "playlist_url": playlist_url,
        "poster_url": v.get("thumbnail_url"),
        "format": v.get("format") or ("video/mp4" if _url_is_mp4(chosen) else None),
        "duration": v.get("duration"),
        "width": v.get("width"), "height": v.get("height"),
        "variants": variants,
        "file": None, "poster_file": None, "downloaded": False,
        "downloadable": _url_is_mp4(chosen),
        "reason": None if _url_is_mp4(chosen)
                  else ("hls_only" if (playlist_url or (chosen and ".m3u8" in chosen))
                        else "no_mp4_variant"),
    }


def map_photo(p: dict) -> dict:
    p = p or {}
    return {
        "url": p.get("url"),
        "alt_text": p.get("alt_text"),
        "width": p.get("width"), "height": p.get("height"),
        "file": None, "downloaded": False,
    }


def map_tweet(tw: dict, position: int | None = None, depth: int = 0) -> dict:
    tw = tw or {}
    media = tw.get("media") or {}
    photos, seen_urls = [], set()
    for p in (media.get("photos") or []):
        if isinstance(p, dict) and p.get("url") and p["url"] not in seen_urls:
            seen_urls.add(p["url"])
            photos.append(map_photo(p))
    videos = []
    for v in (media.get("videos") or []):
        if isinstance(v, dict) and v.get("url"):
            mv = map_video(v)
            if mv["url"] not in seen_urls:
                seen_urls.add(mv["url"])
                videos.append(mv)
    tweet_id = str(tw.get("id")) if tw.get("id") is not None else None
    screen = ((tw.get("author") or {}).get("screen_name")) or None
    out = {
        "id": tweet_id,
        "url": tw.get("url") or (f"https://x.com/{screen}/status/{tweet_id}"
                                 if screen and tweet_id else None),
        "text": tw.get("text"),
        "lang": tw.get("lang"),
        "source": tw.get("source"),
        "created_at": tw.get("created_at"),
        "created_at_iso": _iso_from(tw.get("created_timestamp")),
        "thread_position": position,
        "replying_to": tw.get("replying_to"),
        "replying_to_status": (str(tw["replying_to_status"])
                               if tw.get("replying_to_status") else None),
        "extraction_source": tw.get("_extraction_source"),
        "metrics": {
            "likes": tw.get("likes"), "retweets": tw.get("retweets"),
            "replies": tw.get("replies"), "quotes": tw.get("quotes"),
            "bookmarks": tw.get("bookmarks"), "views": tw.get("views"),
        },
        "author": map_author(tw.get("author")),
        "media": {"photos": photos, "videos": videos},
        "quoted_post": None,
    }
    if depth < 1 and isinstance(tw.get("quote"), dict) and tw["quote"].get("id"):
        out["quoted_post"] = map_tweet(tw["quote"], position=None, depth=depth + 1)
    return out


# ── Tier 3: Media Fetcher ────────────────────────────────────────────────────
def _ext_from_url(url: str, default: str) -> str:
    """Derive a safe file extension from a CDN URL (handles twimg size
    suffixes like '...jpg:large' and '?format=jpg' query forms)."""
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.split(":")[0]  # strip twimg ':large'-style size suffixes
    suffix = Path(path).suffix.lower()
    if suffix in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4"):
        return suffix
    query = urllib.parse.parse_qs(parsed.query)
    fmt = (query.get("format") or [None])[0]
    if fmt and f".{fmt.lower()}" in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        return f".{fmt.lower()}"
    return default


def download(url: str, dest: Path, tries: int = 3) -> bool:
    """Resumable CDN fetch (skip-if-exists), streamed to a .part file and
    atomically renamed — a file is either fully written or absent."""
    if not _media_url_allowed(url):
        log(f"[err] refusing non-CDN media URL: {url}")
        record_error("fetcher", E_DOWNLOAD_FAILED,
                     "refusing non-CDN media URL (scheme/host not allowed)", subject=url)
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        log(f"[skip] {dest.name} exists")
        return True
    part = dest.with_name(dest.name + ".part")
    for attempt in range(1, tries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            started = time.time()
            with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT) as r, \
                    open(part, "wb") as f:
                expected = r.headers.get("Content-Length")
                expected = int(expected) if expected and expected.isdigit() else None
                while True:
                    if time.time() - started > DOWNLOAD_TIMEOUT:
                        raise IOError("transfer deadline exceeded (slow drip)")
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
            size = part.stat().st_size
            if size == 0:
                raise IOError("empty response body")
            if expected is not None and size != expected:
                raise IOError(f"truncated transfer: got {size}, expected {expected} bytes")
            os.replace(part, dest)  # atomic: fully-written or absent
            log(f"[dl ] {dest.name}  {size / 1e6:.2f} MB")
            return True
        except Exception as e:
            log(f"[err] {dest.name}: {e} (try {attempt})")
            if attempt < tries:
                time.sleep(2 * attempt)
    try:
        part.unlink()
    except OSError:
        pass
    record_error("fetcher", E_DOWNLOAD_FAILED, f"download failed after {tries} attempts",
                 subject=url)
    return False


# ── Orchestrator ─────────────────────────────────────────────────────────────
def _download_post_media(post: dict, out: Path, do_download: bool) -> None:
    """Populate local file fields. `downloaded` is True only when the file is
    actually on disk (with --no-download it stays False and `file` is null)."""
    tid = _safe_id(post.get("id"))
    if tid is None:
        return  # remote-controlled ids must never reach the filesystem
    for i, v in enumerate(post["media"]["videos"], 1):
        if not v["downloadable"]:
            continue  # reason already set by map_video
        vname = f"{tid}_v{i}{_ext_from_url(v['url'], '.mp4')}"
        poster_ext = _ext_from_url(v.get("poster_url") or "", ".jpg")
        tname = f"{tid}_v{i}_poster{poster_ext}"
        if do_download:
            v["file"] = vname
            v["downloaded"] = download(v["url"], out / vname)
            if v.get("poster_url") and download(v["poster_url"], out / tname):
                v["poster_file"] = tname
    for i, p in enumerate(post["media"]["photos"], 1):
        pname = f"{tid}_p{i}{_ext_from_url(p['url'], '.jpg')}"
        if do_download:
            p["file"] = pname
            p["downloaded"] = download(p["url"], out / pname)


def harvest(root_id: str, out: Path, do_download: bool = True,
            request_info: dict | None = None,
            decode_sleep: float = DECODE_SLEEP) -> dict:
    """Walk → decode → reconstruct → map → fetch → envelope.

    Returns the enveloped manifest document and writes it to
    `<out>/thread_manifest.json` (UTF-8).
    """
    ERRORS.clear()
    out.mkdir(parents=True, exist_ok=True)
    started = time.time()

    root_tw = fetch_tweet(root_id)
    if root_tw is None:
        record_error("decoder", E_ROOT_UNAVAILABLE,
                     "root tweet unavailable (deleted, protected, or not a tweet)",
                     subject=root_id)
        envelope = {
            "schema_version": SCHEMA_VERSION,
            "source": {"tool": "xthread-agent", "version": __version__,
                       "generated_at": _iso_from(time.time())},
            "request": {"input": (request_info or {}).get("input"),
                        "status_id": root_id,
                        "canonical_url": (request_info or {}).get("canonical_url"),
                        "options": {"download_media": do_download}},
            "status": "empty",
            "thread": {"root_status_id": root_id, "tweet_count": 0,
                       "walker_candidates": 0, "decoded_tweets": 0,
                       "media_ids_filtered": 0, "decode_failed": 0,
                       "related_filtered": 0,
                       "ancestors_fetched": 0, "chain_reconstructed": False,
                       "degraded_to_root_only": False,
                       "walker_slot": "none"},
            "posts": [],
            "errors": [dict(e) for e in ERRORS],
            "metadata": {"duration_sec": round(time.time() - started, 1),
                         "counts": {"posts": 0, "photos": 0, "videos": 0,
                                    "downloaded_media": 0, "failed_downloads": 0}},
        }
        _write_manifest(out, envelope)
        return envelope

    candidates, walker_slot = resolve_thread_ids(root_id)
    decoded = {root_id: root_tw}
    media_ids_filtered = 0
    decode_failed = 0
    for tid in candidates:
        if tid in decoded:
            continue
        if decode_sleep:
            time.sleep(decode_sleep)
        tw = fetch_tweet(tid)
        if tw is None:
            # distinguish honest filter signals (media ids, unavailable) from
            # hard decode failures (already recorded in ERRORS)
            if any(e["code"] == E_DECODE_FAILED and e.get("subject") == tid
                   for e in ERRORS):
                decode_failed += 1
            else:
                media_ids_filtered += 1
            continue
        decoded[tid] = tw

    chain, chain_stats = reconstruct_thread(
        root_id, decoded, fetch_tweet, inter_fetch_sleep=decode_sleep)
    chain_in_decoded = sum(1 for tw in chain if str(tw.get("id")) in decoded)
    related_filtered = max(0, len(decoded) - chain_in_decoded)

    posts = [map_tweet(tw, position=i) for i, tw in enumerate(chain)]
    if do_download:
        for post in posts:
            _download_post_media(post, out, do_download=True)

    counts = {
        "posts": len(posts),
        "photos": sum(len(p["media"]["photos"]) for p in posts),
        "videos": sum(len(p["media"]["videos"]) for p in posts),
        "downloaded_media": sum(
            sum(1 for x in p["media"]["photos"] + p["media"]["videos"] if x.get("downloaded"))
            for p in posts),
        "failed_downloads": sum(
            sum(1 for x in p["media"]["photos"] + p["media"]["videos"]
                if x.get("file") is not None and not x.get("downloaded"))
            for p in posts),
    }
    status = "ok" if posts and not ERRORS else ("partial" if posts else "empty")
    envelope = {
        "schema_version": SCHEMA_VERSION,
        "source": {"tool": "xthread-agent", "version": __version__,
                   "generated_at": _iso_from(time.time())},
        "request": {"input": (request_info or {}).get("input"),
                    "status_id": root_id,
                    "canonical_url": (request_info or {}).get("canonical_url"),
                    "options": {"download_media": do_download}},
        "status": status,
        "thread": {"root_status_id": root_id,
                   "tweet_count": len(posts),
                   "walker_candidates": len(candidates),
                   "decoded_tweets": len(decoded),
                   "media_ids_filtered": media_ids_filtered,
                   "decode_failed": decode_failed,
                   "related_filtered": related_filtered,
                   "ancestors_fetched": chain_stats["ancestors_fetched"],
                   "chain_reconstructed": True,
                   "degraded_to_root_only": walker_slot == "none",
                   "walker_slot": walker_slot},
        "posts": posts,
        "errors": [dict(e) for e in ERRORS],
        "metadata": {"duration_sec": round(time.time() - started, 1),
                     "counts": counts},
    }
    _write_manifest(out, envelope)
    return envelope


def _write_manifest(out: Path, envelope: dict) -> None:
    try:
        final = out / "thread_manifest.json"
        part = out / "thread_manifest.json.part"
        part.write_text(json.dumps(envelope, indent=2, ensure_ascii=False),
                        encoding="utf-8")
        os.replace(part, final)  # atomic: the manifest is never half-written
    except OSError as e:
        record_error("orchestrator", E_MANIFEST_WRITE_FAILED, str(e))
        log(f"[err] manifest write failed: {e}")
        raise


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="xthread-agent",
        description="X/Twitter thread content & media harvester — no login, no API keys, no browser.")
    ap.add_argument("status", nargs="?", help="status URL or id")
    ap.add_argument("--out", default="x_thread_media", help="output directory")
    ap.add_argument("--no-download", action="store_true",
                    help="manifest only — skip media download")
    ap.add_argument("--json", action="store_true",
                    help="print a machine-readable summary to stdout (logs stay on stderr)")
    ap.add_argument("--quiet", action="store_true", help="suppress log lines")
    ap.add_argument("--version", action="store_true", help="print version and exit")
    args = ap.parse_args()

    if args.version:
        print(__version__)
        return 0
    if not args.status:
        ap.error("status url or id is required")

    global LOG_QUIET
    LOG_QUIET = args.quiet or args.json
    started = time.time()

    try:
        try:
            info = normalize_input(args.status)
        except InputError as first_err:
            # t.co shortlinks are valid status inputs: resolve one hop, then
            # re-parse the destination. Any other rejection stands as-is.
            if is_tco(args.status):
                dest = expand_tco(args.status)
                log(f"[ok ] t.co resolved -> {dest}")
                info = normalize_input(dest)
            else:
                raise first_err
    except InputError as e:
        if args.json:
            print(json.dumps({"ok": False, "status": "invalid_input",
                              "error": {"code": e.code, "message": str(e)}}))
            return 1
        print(f"error: {e}", file=sys.stderr)
        return 1

    try:
        envelope = harvest(info["status_id"], Path(args.out),
                           do_download=not args.no_download, request_info=info)
    except Exception as e:  # noqa: BLE001 — the CLI must never leak a traceback
        if not args.json:
            import traceback
            traceback.print_exc(file=sys.stderr)  # full detail for humans
        if args.json:
            print(json.dumps({"ok": False, "status": "error",
                              "error": {"code": E_MANIFEST_WRITE_FAILED,
                                        "message": f"{type(e).__name__}: {e}"}}))
            return 1
        print(f"error: {e}", file=sys.stderr)
        return 1

    counts = envelope["metadata"]["counts"]
    summary = {
        "ok": counts["posts"] > 0,
        "status": envelope["status"],
        "root_id": info["status_id"],
        "canonical_url": info["canonical_url"],
        "tweets": counts["posts"],
        "videos": counts["videos"],
        "photos": counts["photos"],
        "downloaded": counts["downloaded_media"],
        "failed_downloads": counts["failed_downloads"],
        "out_dir": str(Path(args.out)),
        "manifest_path": str(Path(args.out) / "thread_manifest.json"),
        "errors": len(envelope["errors"]),
        "duration_sec": round(time.time() - started, 1),
    }
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        # human summary lines go to STDERR (stdout stays data-only, pipe-safe)
        log(f"\n[done] {counts['posts']} posts · {counts['videos']} videos · "
            f"{counts['photos']} photos · {counts['downloaded_media']} files "
            f"-> {summary['manifest_path']}")
        for err in envelope["errors"]:
            log(f"[warn] {err['stage']}: {err['code']} — {err['message']}")
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
