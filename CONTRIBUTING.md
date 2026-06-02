# Contributing to IntentFrame

Thanks for your interest in contributing. This guide covers the basics.

## Prerequisites

- **Python 3.14+**
- **[uv](https://docs.astral.sh/uv/)** — used for dependency management and virtual environments
- **macOS 14+** (Sonoma) if working on the Swift platform server

## Setup

```bash
git clone https://github.com/intentframe/intentframe.git
cd intentframe
bash intentframe_setup.sh
```

This installs `uv` if needed, creates the virtualenv, syncs all workspace
members, and (on macOS) builds the Swift platform server.

## Running

```bash
uv run intentframe-gateway-cli
```

## Running Tests

```bash
uv run pytest tests/                    # command shield + core tests
uv run pytest demo/tests/               # security demo tests (needs OpenAI key)
```

`tests/conftest.py` sets a temporary `INTENTFRAME_CORE_CONFIG` (autouse) so unit tests that construct core runtime pieces have a valid `bundles:` profile. Supervisor-backed demos must set `INTENTFRAME_CORE_CONFIG` and `EXECUTOR_CONFIG` explicitly — see [docs/plugin-profiles.md](docs/plugin-profiles.md).

## Project Structure

IntentFrame is a `uv` workspace. The root `pyproject.toml` defines the main
package; workspace members (`jarvis_pa`, `external_data_ingestion`,
`intentframe_credentials`, `jarvis_telegram`) have their own `pyproject.toml`
files and are linked via `[tool.uv.sources]`.

Do **not** install workspace members with `pip install -e .` individually —
use `uv sync` from the root.

## Making Changes

1. Create a branch off `main`
2. Make your changes
3. Run the relevant tests
4. Open a pull request with a clear description of what and why

## Style

- No linter is enforced yet — just be consistent with surrounding code
- Avoid adding comments that narrate what the code does; comment only
  non-obvious intent or trade-offs
- Keep commits focused — one logical change per commit

## Security

If you find a security vulnerability, **do not open a public issue**. See
[SECURITY.md](SECURITY.md) for responsible disclosure instructions.

## Contributor License Agreement (CLA)

By submitting a pull request, you agree to the [Contributor License
Agreement](CLA.md). In short: you keep copyright over your contribution, but
you grant IntentFrame a perpetual, irrevocable license to use, modify, and
relicense it — including under commercial terms. This is standard practice
for dual-licensed open source projects (Grafana, GitLab, Nextcloud, etc.).

## License

This project is licensed under the GNU Affero General Public License v3.0
(AGPL-3.0). By contributing, you agree that your contributions will be
licensed under the same terms. See [LICENSE](LICENSE).
