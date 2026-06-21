# GitHub release wheels (fallback install)

Install IntentFrame packages from **GitHub release assets** when you need URL-pinned wheels or PyPI is unavailable. For normal projects, install from **PyPI** instead — see [`../../docs/package-consumers.md`](../../docs/package-consumers.md) and [`example-pyproject-pypi.toml`](example-pyproject-pypi.toml).

Wheels are ordinary `.whl` files attached to a release tag (e.g. [v0.1.1](https://github.com/intentframe/intentframe/releases/tag/v0.1.1)). The same artifacts are published on [PyPI](https://pypi.org/) for `0.1.1`.

Manual GitHub release publishing runbook: [`../github-release/README.md`](../github-release/README.md). PyPI publishing and rate limits: [`../release/README.md`](../release/README.md). Licensing: [`../../docs/licensing.md`](../../docs/licensing.md).

## Publisher workflow

1. Build and validate locally (output in `dist/publish/`):

   ```bash
   ./scripts/release/validate_publish.sh
   ```

2. Create a GitHub release for the lockstep version (tag must match package pins, e.g. `v0.1.1`).

3. Upload **wheels only** (sdists optional; wheels are what consumers need):

   ```bash
   gh release upload v0.1.1 dist/publish/*.whl
   ```

   Re-upload with `--clobber` if replacing files on an existing release.

4. Verify wheels install (disposable venv):

   ```bash
   ./scripts/github-install/verify_release_install.sh --tag v0.1.1
   ```

5. Optional — verify the wheels **boot** supervisor + edge (uses `.venv-release`, same stop/tests as kits-two-venv):

   ```bash
   export OPENAI_API_KEY=sk-...
   bash scripts/kits-two-venv/gh-release-venv/start_runtime_from_release.sh --tag v0.1.1
   bash scripts/kits-two-venv/stop_runtime.sh
   ```

   See [`../kits-two-venv/gh-release-venv/README.md`](../kits-two-venv/gh-release-venv/README.md).

## Verify script

[`verify_release_install.sh`](verify_release_install.sh) creates a disposable Python **3.14** venv, installs all **18** wheels from the release URL, checks each distribution version, and imports the installable modules (`intentframe-runtime` is dependency-only).

```bash
chmod +x scripts/github-install/verify_release_install.sh

./scripts/github-install/verify_release_install.sh
./scripts/github-install/verify_release_install.sh --tag v0.2.0
./scripts/github-install/verify_release_install.sh --repo intentframe/intentframe --python 3.14
./scripts/github-install/verify_release_install.sh --tag v0.1.1 --keep-dir /tmp/if-github-install-test
```

Requires `uv` on PATH and network access to GitHub + PyPI (third-party transitive deps).

### Future release tags

Pass `--tag` for any lockstep release where:

- The tag version matches wheel filenames (`v0.2.0` → `intentframe_core-0.2.0-py3-none-any.whl`).
- All **18** wheels are uploaded with the same naming pattern (`py3-none-any`).
- The package set and import smoke list in the script are unchanged.

The script does **not** support tags whose version string differs from wheel versions (e.g. tag `v0.1.0-alpha.6` with wheels still `*-0.1.0-*`). Add a package or rename a distribution → update `WHEELS` and the embedded Python lists in [`verify_release_install.sh`](verify_release_install.sh) and [`../kits-two-venv/gh-release-venv/start_runtime_from_release.sh`](../kits-two-venv/gh-release-venv/start_runtime_from_release.sh).

## Consumer install (`uv`, GitHub URLs)

**Prefer PyPI:** copy [`example-pyproject-pypi.toml`](example-pyproject-pypi.toml) — no `[tool.uv.sources]` needed.

**URL-pinned wheels:** copy [`example-pyproject.toml`](example-pyproject.toml). `uv` applies `[tool.uv.sources]` for the **whole** resolution, including transitive IntentFrame deps. List every IntentFrame package (simplest: all 18). Third-party deps (`fastapi`, `httpx`, …) still come from PyPI.

Then:

```bash
uv sync
```

For a new lockstep version, replace `v0.1.1` and `0.1.1` in every URL. Confirm filenames with `ls dist/publish/` after build.

## Wheels vs source distributions

| Artifact | Role |
|----------|------|
| `.whl` | Pre-built; use for GitHub release assets and `[tool.uv.sources]` URLs. |
| `.tar.gz` sdist | Optional on the release; slower to install from source. Both ship on PyPI for `0.1.1`. |

## Limitations

- **Public repo only** — release asset URLs work without auth on public repositories.
- **No upload API** — attach files to the GitHub release manually (or your own automation).
- **18-package lockstep** — all packages share one version; intra-org deps are pinned `==<version>`.
