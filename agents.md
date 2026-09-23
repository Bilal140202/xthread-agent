# agents.md — Perfection-Based Role Prompts for the `xthread-agent` Roster

> This file defines each internal stage of the system as a **role prompt**: a
> tight, opinionated, mandatory specification of what the stage is, what it
> does, what it must never do, and the exact interface it exposes. Every
> function in `xthread-agent.py` must conform to the prompt for its role.
>
> Read your role. Implement to your role. Test against your role. Deviate and
> the system fails.
>
> **v3.0.0 amendments:** Role 1 gained a root guarantee and a candidate cap;
> Role 2 gained a fallback decoder slot and real-HTTP-404 handling; Role 3
> gained streaming, atomic writes, size verification, and a CDN host
> allowlist; Role 4 gained the enveloped manifest and a thread-reconstruction
> stage between decoding and fetching.

---

## How to use this file

1. Each section is a **self-contained prompt**: given exactly one section and
   nothing else, an LLM or human engineer must be able to re-implement that
   stage correctly.
2. The prompts are **imperative and unconditional**. There is no "you may want
   to" — there is only "you will".
3. The interface signatures are the contract. Changing a signature is a
   breaking change requiring a RELEASE_NOTES amendment.
4. The "Forbidden" lists are exhaustive. Adding to a list is allowed; removing
   from one requires written justification in the PR.

---

## Role 1 — The Thread Walker

**Function:** `resolve_thread_ids(root_id)`
**One-line role:** *Receive a root status ID, return the ordered list of
candidate conversation member IDs — or degrade to `[root_id]`.*

### You are the Thread Walker. You will:

- Query the public thread-unroll source (currently UnrollNow) with the root ID
  and a hard 40-second timeout, reading at most 20 MB.
- Regex-extract every candidate ID from the returned HTML — both
  `status/<id>` occurrences and bare snowflake-style IDs.
- Deduplicate **preserving first-seen order** (candidate order is meaningful).
- **Guarantee the root is present** in the output (prepend if the extraction
  regex cannot see it — e.g. short legacy IDs).
- Cap candidates at `MAX_CANDIDATES` (50) without ever dropping the root.
- On *any* failure — timeout, HTTP error, garbage payload — log a single
  warning, record the structured error, and return `[root_id]`. A 200 page
  with zero candidates is also a failure (`E_WALKER_EMPTY`), not a success.
- Treat the output as **candidates**, not truth. Downstream decoding and chain
  reconstruction filter it (the page embeds same-author recommendations that
  are NOT thread members).

### Your interface (the contract)

```python
def resolve_thread_ids(root_id: str) -> list[str]: ...
```

### You are forbidden from:

- Verifying IDs yourself. That is the Decoder's job.
- Raising exceptions to the Orchestrator. Degrade, don't crash.
- Reordering IDs. First-seen order is the candidate spine.
- Dropping the root, even when capping.
- Caching across runs. Every run re-walks.
- Hitting the source more than once per run.

### Your success criteria

- A 4-tweet chain yields all 4 IDs in order (plus any media IDs, which are
  filtered downstream).
- A dead source yields exactly `[root_id]` and one warning line.

---

## Role 2 — The Metadata Decoder

**Function:** `fetch_tweet(tid, tries=3)` (+ `_fetch_fxtweet`,
`_fetch_vxtweet`, `_normalize_vxtweet`)
**One-line role:** *Receive a candidate ID, return the decoded tweet payload —
or `None` if the ID is not a live tweet.*

### You are the Decoder. You will:

- Query the primary worker (`api.fxtwitter.com/status/<id>`) with 3 attempts
  and linear backoff (2s, 4s), reading at most 5 MB per attempt.
- Return the `tweet` object when `code == 200`, tagged
  `_extraction_source = "fxtwitter"`.
- Return `None` **silently** when unavailability arrives as a 200 body with
  `code == 404` **or as a real HTTP 404/451 status** — both are the signal
  that the candidate was a media (amplify) ID or an unavailable tweet.
  Filtering is your job; neither case is ever retried.
- Reject payloads whose tweet id is not 1–25 plain digits (remote ids are used
  in filenames downstream — this is the injection guard).
- When the primary fails network-side (timeouts, connection errors, 5xx),
  try the fallback slot (`api.vxtwitter.com`, 2 attempts) and normalize its
  payload into the FixTweet-shaped subset, tagged
  `_extraction_source = "vxtwitter"`. Fields the fallback cannot provide
  become explicit nulls — never fabricated.
- Retry on network exceptions and non-404/451 error codes, then give up with
  `None` and a recorded `E_DECODE_FAILED`.

### Your interface (the contract)

```python
def fetch_tweet(tid: str, tries: int = 3) -> dict | None: ...
```

### You are forbidden from:

- Treating a 404/451 as an error condition. It is a *filter signal*.
- Retrying a 404/451. It is instant and final.
- Returning partial payloads. All-or-`None`.
- Fabricating values the fallback slot did not provide.
- Logging the tweet text. Stats go to the manifest, not to logs.

### Your success criteria

- Multi-video tweets return every video with direct CDN URLs, durations, and
  posters.
- A media ID candidate returns `None` without a single retry.
- A primary-slot outage still yields decoded posts via the fallback slot.

---

## Role 3 — The Media Fetcher

**Function:** `download(url, dest, tries=3)` (+ `_download_post_media`)
**One-line role:** *Receive a CDN URL and a destination path, ensure the file
exists on disk — or report failure.*

### You are the Fetcher. You will:

- **Refuse any URL that is not https on `*.twimg.com`** — media URLs come
  from third-party decoder payloads and must never reach local files or
  internal networks. Refusal is recorded as `E_DOWNLOAD_FAILED`.
- Skip immediately if the destination exists and is non-empty
  (resumability). A leftover `.part` file is never trusted.
- Stream the payload to a `.part` file (1 MB chunks, per-chunk socket timeout
  plus a whole-transfer deadline), then **verify size against
  `Content-Length` when present**, then **atomically `os.replace`** into
  place. A file is either fully written or absent.
- Create parent directories as needed.
- Log one line per file: `[dl ]` with size in MB, or `[err ]` with the reason.

### Your interface (the contract)

```python
def download(url: str, dest: Path, tries: int = 3) -> bool: ...
```

### You are forbidden from:

- Fetching non-CDN URLs (no `file://`, no internal hosts, no non-twimg hosts).
- Writing outside `dest.parent` (post IDs are validated digits before they
  reach you; you never build paths from raw remote data).
- Deleting or overwriting completed files.
- Retrying a download that already succeeded on disk.
- Accepting a truncated transfer (size mismatch = failure).
- Partial writes: a file is either fully written or absent.

### Your success criteria

- Two consecutive identical runs produce identical results; the second run
  performs zero network transfers for completed files.
- A corrupted or truncated transfer never lands in the output directory.

---

## Role 4 — The Orchestrator

**Function:** `normalize_input`, `reconstruct_thread`,
`harvest(root_id, out, do_download=True, request_info=None,
decode_sleep=DECODE_SLEEP) -> dict`, `main()`
**One-line role:** *Receive a status URL, normalize it, walk the thread,
decode, reconstruct the chain, map, fetch, and emit the enveloped manifest —
returning the envelope and a process exit code.*

### You are the Orchestrator. You will:

- Normalize and validate the input to a bare status ID
  (`https://x.com|twitter.com/[mobile.|www.]/<user>/status/<id>`, trailing
  `/photo|/video` suffixes and query strings tolerated; anything else →
  `E_INVALID_INPUT`, exit 1).
- Hand the ID to the Thread Walker, each candidate to the Decoder.
- **Reconstruct the true self-reply chain** (`reconstruct_thread`): walk UP
  from the requested root to the thread start and DOWN through same-author
  replies, using `replying_to_status` as the only membership signal. Decoded
  tweets that never chain are excluded and counted (`related_filtered`).
- Map each payload to the stable schema (`map_tweet` and friends): explicit
  nulls, ISO-8601 UTC timestamps, quoted posts one level deep, video variant
  selection, per-URL media dedupe.
- Assemble the **envelope** (`schema_version`, `source`, `request`, `status`,
  `thread`, `posts`, `errors`, `metadata`) in thread order and write
  `<out>/thread_manifest.json` atomically with `ensure_ascii=False`, UTF-8.
- Print human logs to **stderr** and, under `--json`, exactly one summary
  object to **stdout** — never mixed.
- Return exit code `0` iff at least one post was harvested; otherwise `1`;
  argparse usage errors are `2`.
- Rate-limit: ~0.6s between tweets. Serialize, don't parallelize.

### Your interface (the contract)

```python
def harvest(root_id: str, out: Path, do_download: bool = True,
            request_info: dict | None = None,
            decode_sleep: float = DECODE_SLEEP) -> dict: ...
def main() -> int: ...
```

*(v2 returned the bare posts list; v3 returns the envelope — a documented
breaking change in RELEASE_NOTES.md.)*

### You are forbidden from:

- Asking the user any question. The CLI is non-interactive.
- Calling an LLM. You are a deterministic state machine.
- Printing JSON to stderr or logs to stdout.
- Continuing past a manifest write failure.
- Exceeding the per-attempt timeouts. Timeouts are hard.

### Your success criteria

- `python3 xthread-agent.py <url> --json --quiet` is pipe-safe and
  parse-safe in every code path, including failures.
- A fresh environment running only this file can harvest a public thread
  end-to-end with zero configuration.

---

## Cross-role contracts

- The Walker's output is the Decoder's input; the Decoder's `None` is the
  filter; the Orchestrator's chain reconstruction is the truth; the Fetcher's
  `bool` feeds the manifest's `downloaded` field.
- Thread order is established by chain reconstruction (`replying_to_status`),
  never altered downstream.
- All roles log through the shared `log()` gate; `--quiet`/`--json` silence
  stderr globally. All roles record structured failures through
  `record_error()`; the Orchestrator snapshots them into `errors[]`.

## The perfection bar

A role is done when: its prompt matches the code line-for-line, its failure
modes degrade instead of crash, and a cold-start run in a clean environment
succeeds without human input.
