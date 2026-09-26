# Contributing to xthread-agent

Thanks for helping keep an open, no-auth path to public X content alive.

## Ground rules

1. **Public content only.** No features that bypass protected accounts,
   deleted media, or paywalls. Those fail closed by design.
2. **stdlib only.** The tool must keep running as a single file on a bare
   Python 3.9+. No pip dependencies, no compiled extensions.
3. **Politeness is not optional.** Low rate limits, small retries, idempotent
   runs. The infrastructure this tool depends on is free; treat it well.
4. **Nothing personal in the repo.** Issues, docs, tests, and fixtures must
   never contain real harvested content, account names, or status IDs. Test
   against fixtures and synthetic IDs; describe provenance generically.

## How to contribute

1. Open an issue describing the problem or the dead endpoint *first*.
2. Fork, branch (`feat/...` or `fix/...`), implement.
3. If you changed a public contract (CLI flags, JSON schema, exit codes),
   update `agent.md`, `README.md`, `schema/thread-result.schema.json`, and
   `RELEASE_NOTES.md` in the same PR.
4. If you changed a pipeline stage's behavior, update the matching role
   prompt in `agents.md` — the prompt is the spec.
5. If you discovered a new endpoint (alive or dead), update
   `docs/endpoint-matrix.md` with its status and failure signature.
6. Test:
   - `cd tests && python3 -m unittest discover -p "test_*.py" -v`
     — the full offline suite (synthetic fixtures only, no network) must
     pass before any PR.
   - Then run the tool against a live public thread you control, in
     `--no-download` mode, and confirm the manifest is correct; then run one
     full download and confirm resumability by running it twice.
7. Commit in conventional style (`feat:`, `fix:`, `docs:`, `chore:`).

### Test conventions

- Tests import the tool through `tests/_loader.py` (the hyphenated filename
  cannot be imported normally).
- Fixtures live in `tests/fixtures.py` and are 100% synthetic — the
  "nothing personal in the repo" rule applies to test data too.
- New failure modes deserve a regression test: reproduce the bug with a
  mock, fix it, keep the test.

## Reporting a broken endpoint

Include: environment class (datacenter/residential), HTTP status, response
excerpt (redact any content), and the date. Open a PR against
`docs/endpoint-matrix.md` if you already know the replacement.
