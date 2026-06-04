# Release tooling (`packages/` → PyPI)

Only distributions under `packages/` are published. Product-facing code (root `intentframe`, gateway, Jarvis, EDI) stays out of scope.

## Lockstep versioning

All 18 packages share one version. Intra-workspace dependencies are pinned to `==<version>` so wheels resolve correctly off PyPI (workspace sources are dev-only).

```bash
# Apply pins for a release (review git diff, then commit)
python scripts/release/set_version.py 0.1.0

# CI guard: fail if any package drifted
python scripts/release/set_version.py 0.1.0 --check
```

## Pre-publish validation

Builds every package, runs `twine check`, verifies wheels ship `LICENSE` and key data files, then installs from the local `dist/` set with `--no-index` to prove the dependency graph is closed.

```bash
chmod +x scripts/release/validate_publish.sh
./scripts/release/validate_publish.sh
```

Optional TestPyPI upload (needs credentials):

```bash
./scripts/release/validate_publish.sh --publish-test
```

Requires Python **3.14** (project floor) and `uv` on PATH.

## Suggested release order

1. `set_version.py <version>` → `uv sync` → run tests
2. `./scripts/release/validate_publish.sh`
3. Upload wheels/sdists to PyPI (topological order is handled by pip if all versions are pinned)
4. Tag the release in git

See [docs/licensing.md](../../docs/licensing.md) for AGPL vs Apache split.
