# Publishing xthread-agent — the exact checklist

This project ships to **PyPI** (`pip install xthread-agent`). npm is not
applicable: both the harvester and the MCP wrapper are Python. The MCP
server can additionally be registered in the MCP server registry later
(see "Later" at the bottom).

Everything below is already prepared in the repository:

| Artifact | Status |
|---|---|
| `pyproject.toml` (PEP 621, setuptools backend, zero dependencies) | ✅ committed |
| `xthread_agent/` wheel package (byte-identical copy of `xthread-agent.py`) | ✅ committed |
| Drift guard: `tests/test_package_sync.py` fails if the copy ever diverges | ✅ in CI |
| Version consistency guard: `pyproject.toml` version == tool `__version__` | ✅ in CI |
| Build pipeline: `.github/workflows/release.yml` (tag `v*` → test → build → twine check → clean-venv smoke → GitHub Release → PyPI) | ✅ committed |
| `twine check` validated locally on sdist + wheel | ✅ passed |
| Clean-venv smoke: console script, `python -m`, import | ✅ passed |
| **First publication: `xthread-agent 3.2.0` live on PyPI** | ✅ **2026-09-27** |

## How publishing works now (API token)

The repo secret `PYPI_API_TOKEN` (project-scoped token for `xthread-agent`,
account `ansaribilal1402`) drives the Release workflow's `publish-pypi` job:
`pypa/gh-action-pypi-publish` with `user: __token__` /
`password: ${{ secrets.PYPI_API_TOKEN }}`. No long-lived credentials live in
the repo — only the encrypted Actions secret.

**If the token is ever revoked**, pick one of:

1. *Replace the secret* — create a fresh project-scoped API token on
   pypi.org (account → API tokens, scope it to `xthread-agent`), then update
   the repo secret `PYPI_API_TOKEN` (Settings → Secrets and variables →
   Actions). Zero workflow changes needed.
2. *Switch to Trusted Publishing (OIDC, no secrets at all)* — on pypi.org →
   project `xthread-agent` → Publish → Add a pending publisher with
   owner `Bilal140202`, repository `xthread-agent`, workflow `release.yml`,
   environment `pypi`; then in `release.yml` remove the `user`/`password`
   inputs and restore `id-token: write` in the workflow permissions.

## One-time setup (repo owner only) — DONE

### 1. PyPI credentials — complete 2026-09-27

The project-scoped API token was used for the first manual publication:

```bash
twine upload dist/*   # user __token__ + project-scoped API token
```

→ https://pypi.org/project/xthread-agent/3.2.0/ (both sdist and wheel).
The same token is stored as the encrypted repo secret `PYPI_API_TOKEN` so
future tags publish automatically. Trusted Publishing (below) remains the
recommended long-term replacement once the token is rotated.

<details>
<summary>Alternative: PyPI Trusted Publishing (no tokens, no secrets)</summary>

1. On pypi.org for the existing project `xthread-agent` → Publish →
   **"Add a pending publisher"**:
   - PyPI project name: `xthread-agent`
   - Owner: `Bilal140202`
   - Repository: `xthread-agent`
   - Workflow: `release.yml`
   - Environment name: `pypi`
2. In this GitHub repo: Settings → Environments → create `pypi`
   (no protection rules needed for a personal project).
3. In `release.yml`: drop the `user`/`password` inputs on the publish step
   and re-add `id-token: write` to the workflow permissions.

</details>

### 2. Ship a version

```bash
# (from a clean checkout on main, tests green)
git tag v3.2.0
git push origin v3.2.0
```

The Release workflow then: runs the offline suite → verifies package sync +
version consistency → builds sdist+wheel → `twine check` → smoke-tests the
wheel in a clean venv → attaches both artifacts to the GitHub Release →
publishes to PyPI via the `PYPI_API_TOKEN` secret.

### 3. Verify

```bash
pip install xthread-agent==3.2.0
xthread-agent --version            # console script
python -m xthread_agent --version  # module invocation
python -c "import xthread_agent; print(xthread_agent.__version__)"
```

## Version bump procedure (never forget a spot)

1. `xthread-agent.py` → `__version__`
2. `pyproject.toml` → `version` (a test enforces the match)
3. `RELEASE_NOTES.md` → new section
4. `scripts/sync_package.py` (regenerates the wheel copy)
5. `python3 -m unittest discover -s tests -p "test_*.py"` → green

## Why the package is a synced copy, not a refactor

The single-file constraint is a design feature ("copy one file into a bare
sandbox and run it" — see PROJECT_CONTEXT.md §5.1). Refactoring into a
package would break the curl-and-run story; keeping a hand-maintained copy
would drift. The sync script + drift-guard test make divergence a build
failure instead of a slow-motion bug.

## Later (optional)

- **MCP server registry**: `mcp_server.py` can be registered as an MCP
  server (stdio transport) once the MCP registry accepts submissions for
  stdlib-only servers.
- **conda-forge**: trivial after PyPI (stdlib-only, no builds needed).
