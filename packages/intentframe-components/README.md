# intentframe-components

The LLM-facing engines of the [IntentFrame](https://github.com/intentframe/intentframe)
policy pipeline: the analysis engine, the guardian (AI + deterministic),
the onboarding engine, and the prompt-hardening layer.

These components are wired together by the `intentframe-server` runtime. They
depend on `intentframe-core`, `intentframe-bundle-sdk`,
`intentframe-policy-registry`, and `intentframe-prompt-library`.

```bash
pip install intentframe-components
```
