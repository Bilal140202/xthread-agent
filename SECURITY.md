# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 3.2.x | ✅ |
| < 3.2 | ❌ (upgrade — the walker/decoder slot architecture changed) |

## Reporting a vulnerability

Open a [GitHub security advisory](https://github.com/Bilal140202/xthread-agent/security/advisories/new)
(private disclosure) rather than a public issue. Expect a response within a week.

## Scope notes (read before reporting)

This tool is a *fetcher of public content*, and its threat model reflects
that:

- **In scope**: the media-URL allowlist (`*.twimg.com`, https only), remote-ID
  validation before filesystem use, response-body caps, subprocess argument
  handling in the MCP wrapper (no shell), the `read_manifest` filename guard,
  the atomic-write discipline, and any way a third-party payload could make
  the tool fetch non-CDN resources, write outside the output directory, or
  produce a manifest that misrepresents what happened.
- **Out of scope**: "X can see this" — the tool only reaches publicly
  accessible content by design; and upstream availability changes, which are
  tracked in `docs/endpoint-matrix.md`, not security advisories.
