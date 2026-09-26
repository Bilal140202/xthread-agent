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

## One-time setup (repo owner only)

### 1. PyPI Trusted Publishing (no tokens, no secrets)

1. Create the project name on PyPI if it does not exist yet: either upload
   once manually (`twine upload dist/*` with your account), or use
   **"Add a pending publisher"** on pypi.org for the name `xthread-agent`.
2. Publisher settings, exactly:
   - PyPI project name: `xthread-agent`
   - Owner: `Bilal140202`
   - Repository: `xthread-agent`
   - Workflow: `release.yml`
   - Environment name: `pypi`
3. In this GitHub repo: Settings → Environments → create `pypi`
   (no protection rules needed for a personal project).

### 2. Ship a version

```bash
# (from a clean checkout on main, tests green)
git tag v3.2.0
git push origin v3.2.0
```

The Release workflow then: runs the offline suite → verifies package sync +
version consistency → builds sdist+wheel → `twine check` → smoke-tests the
wheel in a clean venv → attaches both artifacts to the GitHub Release →
publishes to PyPI via OIDC.

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
