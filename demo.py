#!/usr/bin/env python3
"""
demo.py — minimal end-to-end demonstration of xthread-agent.

INPUT:  one X/Twitter status URL (or bare status ID)
OUTPUT: a readable summary of everything the agent harvested — author,
        post/thread text, timestamps, media with metadata, downloadable
        file references, and extraction metadata — straight from
        thread_manifest.json (the machine-readable artifact).

Usage:
    python3 demo.py "https://x.com/<user>/status/<id>"
    python3 demo.py "<url>" --skip-download     # metadata only, no files
    python3 demo.py "<url>" --raw               # print the JSON envelope too

This is intentionally tiny: if you can read this file, you know exactly how
to consume xthread-agent programmatically.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

TOOL = Path(__file__).resolve().parent / "xthread-agent.py"


def run(url: str, out_dir: str, skip_download: bool) -> dict:
    """Run the harvester exactly the way an external agent would: a
    subprocess call, JSON summary on stdout, manifest file on disk."""
    cmd = [sys.executable, str(TOOL), url, "--out", out_dir, "--json", "--quiet"]
    if skip_download:
        cmd.append("--no-download")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    summary = json.loads(proc.stdout)  # pipe-safe: logs never touch stdout
    if proc.returncode not in (0, 1):
        raise RuntimeError(f"unexpected exit code {proc.returncode}: {proc.stderr}")
    return summary


def show(env_path: str) -> None:
    env = json.loads(Path(env_path).read_text(encoding="utf-8"))
    bar = "=" * 62

    print(f"\n{bar}\n xthread-agent result — status: {env['status'].upper()}"
          f"\n{bar}")

    req = env["request"]
    print(f"requested : {req['input']}\ncanonical : {req['canonical_url']}")
    th = env["thread"]
    print(f"thread    : {th['tweet_count']} post(s) reconstructed "
          f"(candidates={th['walker_candidates']}, related filtered={th['related_filtered']})")

    for err in env["errors"]:
        print(f"WARNING   : [{err['stage']}] {err['code']} — {err['message']}")

    for post in env["posts"]:
        a = post["author"]
        print(f"\n--- post {post['thread_position']} ---")
        print(f"  id       : {post['id']}")
        print(f"  author   : @{a['screen_name']} ({a['name']})"
              f"{'  [verified]' if a['verified'] else ''}"
              f"  followers={a['followers']}")
        print(f"  when     : {post['created_at_iso']} (UTC)")
        text = (post["text"] or "").replace("\n", "\n             ")
        print(f"  text     : {text}")
        m = post["metrics"]
        print(f"  metrics  : {m['likes']} likes · {m['retweets']} RT · "
              f"{m['replies']} replies · {m['views']} views")
        if post["quoted_post"]:
            q = post["quoted_post"]
            print(f"  quotes   : @{q['author']['screen_name']}: "
                  f"{(q['text'] or '')[:70]}…")
        for i, ph in enumerate(post["media"]["photos"], 1):
            print(f"  photo {i}   : {ph['file'] or '(not downloaded)'}"
                  f"  {ph['width']}x{ph['height']}  {ph['url'][:60]}…")
            if ph["alt_text"]:
                print(f"             alt: {ph['alt_text'][:70]}")
        for i, v in enumerate(post["media"]["videos"], 1):
            state = v["file"] if v["downloaded"] else (
                f"NOT downloaded ({v['reason']})" if not v["downloadable"]
                else "NOT downloaded (failed)")
            print(f"  video {i}  : {state}  {v['duration']}s "
                  f"{v['width']}x{v['height']} {v['format']}")

    c = env["metadata"]["counts"]
    print(f"\n{bar}")
    print(f" totals   : {c['posts']} posts · {c['photos']} photos · "
          f"{c['videos']} videos · {c['downloaded_media']} files on disk "
          f"· {env['metadata']['duration_sec']}s")
    print(f" manifest : {env_path}")
    print(f"{bar}\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="xthread-agent end-to-end demo")
    ap.add_argument("url", help="X/Twitter status URL or bare status id")
    ap.add_argument("--out", default="demo_output", help="output directory")
    ap.add_argument("--skip-download", action="store_true",
                    help="metadata only — no media files")
    ap.add_argument("--raw", action="store_true",
                    help="also print the raw JSON envelope to stdout")
    args = ap.parse_args()

    summary = run(args.url, args.out, args.skip_download)
    if not summary["ok"]:
        print(f"nothing harvested (status={summary.get('status')}) — "
              f"is the post public and available?", file=sys.stderr)
        return 1

    show(summary["manifest_path"])
    if args.raw:
        print(Path(summary["manifest_path"]).read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
