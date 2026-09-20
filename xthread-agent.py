#!/usr/bin/env python3
"""
xthread-agent — X/Twitter thread media harvester
=================================================
A deterministic, self-contained agent that, given any public X status URL:

  1. Resolves the FULL thread (self-reply chain) via a thread-walk source
  2. Fetches each tweet's metadata (text, author, stats, media) via FixTweet
  3. Downloads every video (best-quality mp4) + poster thumbnail + photos
  4. Emits `thread_manifest.json` — a machine-readable result

Pipeline (three tiers, no login, no API keys, no browser):
  Tier 1  UnrollNow            — thread walk (ordered conversation member IDs)
  Tier 2  FixTweet API         — per-tweet metadata decode incl. multi-video
                                 "amplify" media with direct twimg CDN URLs
  Tier 3  video/pbs.twimg.com  — CDN fetch, no auth needed once URL is known

Usage:
  python3 xthread-agent.py <status_url_or_id> [--out DIR] [--no-download]
                            [--json] [--quiet] [--version]

Exit codes: 0 = at least one tweet harvested, 1 = nothing harvested / error.
"""
import json
import re
import sys
import time
import argparse
import urllib.request
from pathlib import Path

__version__ = "2.0.0"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

LOG_QUIET = False


def log(msg: str) -> None:
    if not LOG_QUIET:
        print(msg, file=sys.stderr)


def http_get(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def extract_status_id(inp: str) -> str:
    m = re.search(r"(?:status(?:es)?/)?(\d{10,25})", inp)
    if not m:
        raise SystemExit(f"Cannot parse status id from: {inp}")
    return m.group(1)


# ── Tier 1: Thread Walker ────────────────────────────────────────────────────
def resolve_thread_ids(root_id: str) -> list[str]:
    """Walk the thread via UnrollNow; fallback: just the root.

    UnrollNow embeds the raw conversation in its HTML — both tweet IDs and
    media (amplify) IDs appear. A later FixTweet 404 on an ID is the signal
    that the ID was a media ID, so 404 is treated as *filter*, not *failure*.
    """
    url = f"https://unrollnow.com/status/{root_id}"
    try:
        raw = http_get(url, timeout=40).decode("utf-8", "replace")
    except Exception as e:
        log(f"[warn] thread walk failed ({e}); falling back to root only")
        return [root_id]
    ids = re.findall(r"status/(\d{15,25})", raw)
    ids += re.findall(r"\b(21\d{17,22})\b", raw)  # bare snowflake-ish ids
    seen, ordered = set(), []
    for i in ids:
        if i not in seen:
            seen.add(i)
            ordered.append(i)
    log(f"[ok] thread resolved: {len(ordered)} candidate ids")
    return ordered


# ── Tier 2: Metadata Decoder ─────────────────────────────────────────────────
def fetch_tweet(tid: str, tries: int = 3) -> dict | None:
    """Decode one tweet via FixTweet. 404s return None (filter, not failure)."""
    url = f"https://api.fxtwitter.com/status/{tid}"
    for attempt in range(1, tries + 1):
        try:
            data = json.loads(http_get(url, timeout=30).decode())
            if data.get("code") == 200:
                return data["tweet"]
            if data.get("code") == 404:
                return None  # media id or unavailable — filter out silently
            log(f"[..] {tid}: code={data.get('code')} (try {attempt})")
        except Exception as e:
            log(f"[..] {tid}: {e} (try {attempt})")
        time.sleep(2 * attempt)
    return None


# ── Tier 3: Media Fetcher ────────────────────────────────────────────────────
def download(url: str, dest: Path, tries: int = 3) -> bool:
    """Resumable CDN fetch (skip-if-exists)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        log(f"[skip] {dest.name} exists")
        return True
    for attempt in range(1, tries + 1):
        try:
            blob = http_get(url, timeout=180)
            dest.write_bytes(blob)
            log(f"[dl ] {dest.name}  {len(blob)/1e6:.2f} MB")
            return True
        except Exception as e:
            log(f"[err] {dest.name}: {e} (try {attempt})")
            time.sleep(2 * attempt)
    return False


# ── Orchestrator ─────────────────────────────────────────────────────────────
def harvest(root_id: str, out: Path, do_download: bool = True) -> list[dict]:
    """Walk → decode → fetch → manifest. Returns the manifest list."""
    out.mkdir(parents=True, exist_ok=True)
    manifest: list[dict] = []
    for tid in resolve_thread_ids(root_id):
        tw = fetch_tweet(tid)
        if tw is None:
            log(f"[warn] {tid} unavailable — skipping")
            continue
        entry = {
            "id": tw["id"],
            "author": tw["author"]["screen_name"],
            "text": tw.get("text", ""),
            "created_at": tw.get("created_at"),
            "likes": tw.get("likes"), "retweets": tw.get("retweets"),
            "replies": tw.get("replies"), "views": tw.get("views"),
            "videos": [], "photos": [],
        }
        media = tw.get("media") or {}
        for i, v in enumerate(media.get("videos") or [], 1):
            vurl = v["url"]
            ext = ".mp4" if ".mp4" in vurl else ".m3u8"
            vname = f"{tid}_v{i}{ext}"
            tname = f"{tid}_v{i}_poster.jpg"
            ok = True
            if do_download:
                ok = download(vurl, out / vname)
                if v.get("thumbnail_url"):
                    download(v["thumbnail_url"], out / tname)
            entry["videos"].append({
                "file": vname if do_download else None, "url": vurl,
                "downloaded": ok,
                "duration": v.get("duration"),
                "width": v.get("width"), "height": v.get("height"),
                "poster": tname if v.get("thumbnail_url") else None,
            })
        for i, p in enumerate(media.get("photos") or [], 1):
            pname = f"{tid}_p{i}.jpg"
            ok = True
            if do_download:
                ok = download(p["url"], out / pname)
            entry["photos"].append({"file": pname if do_download else None,
                                    "url": p["url"], "downloaded": ok,
                                    "alt": p.get("alt_text")})
        manifest.append(entry)
        time.sleep(0.6)

    (out / "thread_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False))
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="xthread-agent",
        description="X/Twitter thread media harvester — no login, no API keys, no browser.")
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
        root = extract_status_id(args.status)
    except SystemExit as e:
        if args.json:
            print(json.dumps({"ok": False, "error": str(e)}))
            return 1
        raise

    manifest = harvest(root, Path(args.out), do_download=not args.no_download)

    videos = sum(len(t["videos"]) for t in manifest)
    photos = sum(len(t["photos"]) for t in manifest)
    summary = {
        "ok": len(manifest) > 0,
        "root_id": root,
        "tweets": len(manifest),
        "videos": videos,
        "photos": photos,
        "out_dir": str(Path(args.out)),
        "manifest_path": str(Path(args.out) / "thread_manifest.json"),
        "duration_sec": round(time.time() - started, 1),
    }
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"\n[done] {len(manifest)} tweets · {videos} videos · {photos} photos "
              f"-> {summary['manifest_path']}")
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
