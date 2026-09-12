# Dependency review

Reviewed 2026-09-12 with pip-audit against the workspace environment.
After the changes below, the audit reports no known vulnerabilities. Local workspace
packages are reviewed as source, not audited against PyPI advisories. This result is
time-specific and does not establish the absence of undisclosed vulnerabilities.

Pytest was upgraded to 9.1.1 to remove PYSEC-2026-1845 (Unix temporary-directory
handling). It is a development dependency and is excluded from runtime exports.

## Removed unused ADK extensions

NLTK 3.10.3 was a transitive runtime dependency. The audit reported PYSEC-2026-3740
(GHSA-8mgp-746c-j5xp), with no fixed version supplied. The affected model-file APIs
can bypass NLTK pathsec restrictions when callers control import/export paths.
It entered through ADK's optional `extensions` extra, which no agent or workflow
in this repository uses. Removing that extra removes NLTK and its unused integration
dependencies from the lock and runtime exports. Agent Identity support is retained;
MCP agents continue to declare their MCP extra separately.

Do not restore the broad extensions extra for one integration. Declare only the
dependencies that integration needs and audit them. If NLTK is reintroduced before
an upstream fix, require a security review rather than suppressing the advisory.

Recheck with `uv run --with pip-audit pip-audit --path .venv/Lib/site-packages` on
Windows (adjust the site-packages path on Linux). Audit each exported runtime's
dependencies as well as development dependencies before release.
