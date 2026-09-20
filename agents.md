# agents.md — Perfection-Based Role Prompts for the `xthread-agent` Roster

> This file defines each internal stage of the system as a **role prompt**: a
> tight, opinionated, mandatory specification of what the stage is, what it
> does, what it must never do, and the exact interface it exposes. Every
> function in `xthread-agent.py` must conform to the prompt for its role.
>
> Read your role. Implement to your role. Test against your role. Deviate and
> the system fails.

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
  and a hard 40-second timeout.
- Regex-extract every conversation member ID from the returned HTML — both
  `status/<id>` occurrences and bare snowflake-style IDs.
- Deduplicate **preserving first-seen order** (thread order is meaningful).
- On *any* failure — timeout, HTTP error, garbage payload — log a single
  warning and return `[root_id]`. You never raise, never abort the run.
- Treat the output as **candidates**, not truth. Downstream decoding filters
  it.

### Your interface (the contract)

```python
def resolve_thread_ids(root_id: str) -> list[str]: ...
```

### You are forbidden from:

- Verifying IDs yourself. That is the Decoder's job.
- Raising exceptions to the Orchestrator. Degrade, don't crash.
- Reordering IDs. First-seen order is the thread's spine.
- Caching across runs. Every run re-walks.
- Hitting the source more than once per run.

### Your success criteria

- A 4-tweet chain yields all 4 IDs in order (plus any media IDs, which are
  filtered downstream).
- A dead source yields exactly `[root_id]` and one warning line.

---

## Role 2 — The Metadata Decoder

**Function:** `fetch_tweet(tid, tries=3)`
**One-line role:** *Receive a candidate ID, return the decoded tweet payload —
or `None` if the ID is not a live tweet.*

### You are the Decoder. You will:

- Query the FixTweet worker (`api.fxtwitter.com/status/<id>`) with 3 attempts
  and linear backoff (2s, 4s, 6s).
- Return the `tweet` object when `code == 200`.
- Return `None` **silently** when `code == 404` — this is the signal that the
  candidate was a media (amplify) ID, not a tweet. Filtering is your job.
- Retry on network exceptions and non-404 error codes, then give up with
  `None`.

### Your interface (the contract)

```python
def fetch_tweet(tid: str, tries: int = 3) -> dict | None: ...
```

### You are forbidden from:

- Treating a 404 as an error condition. It is a *filter signal*.
- Returning partial payloads. All-or-`None`.
- Following redirects to other services.
- Logging the tweet text. Stats go to the manifest, not to logs.

### Your success criteria

- Multi-video tweets return every video with direct CDN URLs, durations, and
  posters.
- A media ID candidate returns `None` without a single retry.

---

## Role 3 — The Media Fetcher

**Function:** `download(url, dest, tries=3)`
**One-line role:** *Receive a CDN URL and a destination path, ensure the file
exists on disk — or report failure.*

### You are the Fetcher. You will:

- Skip immediately if the destination exists and is non-empty
  (resumability).
- Stream the payload to disk with a 180-second timeout and 3 attempts.
- Create parent directories as needed.
- Log one line per file: `[dl ]` with size in MB, or `[err ]` with the reason.

### Your interface (the contract)

```python
def download(url: str, dest: Path, tries: int = 3) -> bool: ...
```

### You are forbidden from:

- Writing outside `dest.parent`.
- Deleting or overwriting completed files.
- Retrying a download that already succeeded on disk.
- Partial writes: a file is either fully written or absent.

### Your success criteria

- Two consecutive identical runs produce identical results; the second run
  performs zero network transfers for completed files.

---

## Role 4 — The Orchestrator

**Function:** `harvest(root_id, out, do_download)` + `main()`
**One-line role:** *Receive a status URL, walk the thread, decode, fetch, and
emit the manifest — returning a structured summary and a process exit code.*

### You are the Orchestrator. You will:

- Parse and canonicalize the input to a bare status ID.
- Hand the ID to the Thread Walker, each candidate to the Decoder, each media
  URL to the Fetcher.
- Assemble the manifest in **thread order**, writing
  `<out>/thread_manifest.json` with `ensure_ascii=False`.
- Print human logs to **stderr** and, under `--json`, exactly one summary
  object to **stdout** — never mixed.
- Return exit code `0` iff at least one tweet was harvested; otherwise `1`.
- Rate-limit: ~0.6s between tweets. Serialize, don't parallelize.

### Your interface (the contract)

```python
def harvest(root_id: str, out: Path, do_download: bool = True) -> list[dict]: ...
def main() -> int: ...
```

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
  filter; the Fetcher's `bool` feeds the manifest's `downloaded` field.
- Thread order established by the Walker is never altered downstream.
- All roles log through the shared `log()` gate; `--quiet`/`--json` silence
  stderr globally.

## The perfection bar

A role is done when: its prompt matches the code line-for-line, its failure
modes degrade instead of crash, and a cold-start run in a clean environment
succeeds without human input.
