---
name: Bug report
about: Report something that is broken or behaving incorrectly
title: "[Bug]: "
labels: bug
assignees: ''
---

## What happened?

<!-- Describe the bug clearly and concisely. -->

## What did you expect?

<!-- What should have happened instead? -->

## How to reproduce

<!-- Minimal steps to reproduce the issue. -->

```bash
# paste commands or code here
```

## Environment

### Device & OS

> **Note:** IntentFrame currently supports macOS on Apple Silicon only (M1 and later). Intel Mac and Linux are not supported yet.

- Mac model (e.g. MacBook Pro M4 Pro, MacBook Air M2):
- macOS version (e.g. Tahoe 26.3, Sonoma 14.5):
- RAM:

### Python & tooling

- Python version (`python3 --version`):
- `uv` version (`uv --version`):
- Install method (fresh clone / `uv sync`):
- IntentFrame commit or version (`git rev-parse --short HEAD`):

### IntentFrame stack

- Gateway running? (yes / no):
- Supervisor running? (yes / no):
- Executor running? (yes / no):
- Active profile (`user` / `root`):
- Escalation state (ARMED / DISARMED — root demo only):
- macOS platform server running (for Calendar, Contacts, iMessage)? (yes / no / not needed):
- OpenAI model in use (default `gpt-5-mini` / other):

### Optional integrations active

- [ ] Jarvis PA
- [ ] Telegram bridge
- [ ] Email sync (EDI)
- [ ] Root demo profile

## Logs or output

<!-- Paste relevant logs, error messages, or stack traces. Redact any real credentials, tokens, or personal data. -->

<details>
<summary>Log output</summary>

```
paste logs here
```

</details>

## Security impact

Does this involve a policy bypass, unsafe execution, credential exposure, or unexpected Guardian/executor behaviour?

- [ ] Yes — please also see [SECURITY.md](../../SECURITY.md) for responsible disclosure
- [ ] No — standard functional bug
