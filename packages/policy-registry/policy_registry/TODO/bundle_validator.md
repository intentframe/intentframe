Yes — and once you read those two docs together, the "registry asks the bundle process" pattern is exactly the right shape, not a workaround.

## Why the future architecture makes this clean

`action-wiring-refactor.md` already commits IntentFrame to **process-isolated partner extensions** (MCP/gRPC sidecars, ranks 1-3). `path_to_production.md` flags the in-process `_LOADED_PACKAGES` global as one of the "not yet production-ready" items. Put those together and the bundle SDK becomes a **bundle service** — its own UDS process — for the same reasons `policy-registry` and `executor` already are.

When that lands, the supervisor graph becomes:

```
bundle-runtime (own process: ensure_loaded, validate, describe)
       ▲
       │ depends_on
       │
policy-registry ──────┐
resource-registry ────┤
executor ─────────────┤
                      │
                  intentframe-core
```

Now every property the old loader was implicitly giving you maps onto an explicit service contract:

- The bundle process is the **single owner** of the plugin set; nothing else hardcodes package names.
- The bundle process exposes `POST /policies/validate` (or the equivalent gRPC method) — one round trip, returns 204 / 422.
- The policy-registry server, on every `POST /policies` and `PATCH …/constraints`, calls the bundle service over UDS before storing. If the bundle service is down → registry refuses writes (fail closed). The supervisor `depends_on` ensures bundle-runtime is healthy first, so this is normal.

So the answer to your question — "registry makes an HTTP call to validate, internally or via an internal bundle SDK client?" — is: **HTTP/UDS, via a thin client**, mirroring how everything else in IntentFrame already talks. The same way `intentframe-core` reaches `policy-registry` today.

## Why this is strictly better than what the old loader did

| Property | Old loader | Future bundle-runtime service |
|---|---|---|
| Single place that catches all writes | Yes (per-process) | Yes (per-deployment) |
| Plugin set picked by deployment, not loader | Yes (`core.yaml` `bundles:`; gateway `resolve_core_config_path()`) | Yes (bundle-runtime decides) |
| Registry depends on bundle SDK at import time | Yes (layering violation) | No — only an HTTP client |
| Bypassable by external installers | Yes (raw POST works) | **No** — registry rejects unvalidated writes |
| Multi-process safety / isolation | No | Yes (separate process boundaries) |
| Path-to-production sandboxing prerequisite | No | Yes — required for MCP/WASM partner bundles anyway |

The most important row is the fourth one. Today, even with our `IntentFrameRuntime.startup()` validation, an external agent installer can POST a malformed policy directly to `policy-registry.sock` and it will land in the store. Per-intent enforcement still fail-closes, but the write succeeds. With a bundle-runtime service in front of registry writes, that write would be **structurally impossible** — exactly the property the old loader was reaching for, but at the right layer.

## So what does that mean for today's code?

The `IntentFrameRuntime.startup()` validation we just added is **on the path** to that future, not a detour from it:

- It's *additive*: when bundle-runtime arrives, you can keep core's boot validation as defense in depth, or remove it because writes are now pre-validated.
- It avoids the layering reversal the old loader had (no `policy_registry → intentframe_bundle_sdk` import).
- The function signature is small and easy to delete or keep — it doesn't bake in any assumption about validation living in the runtime.
- And critically: it does not require us to ship the bundle-runtime service today. That work is non-trivial (per `path_to_production.md` items 1-9), and tying validation to it would block correctness on platform work.

The conceptual model you're describing — registry asks the bundle owner — is the **target state**. The SDK is currently in-process, so today's validator can only run in the process that loaded the SDK. That happens to be `intentframe-core`. Once the SDK becomes its own service, the validator moves to that service and the registry calls it. Same idea, correct layer.

If you want to lay the groundwork without doing the full process split now, the smallest preparatory move is to **define the validation contract as an HTTP/RPC interface today** (e.g. `intentframe_bundle_sdk.client.BundleClient.validate_policy(policy)`) and have `IntentFrameRuntime.startup()` call that client against a local in-process implementation. When you later spin up `bundle-runtime` as its own UDS process, the only change is swapping the in-process implementation for a UDS HTTP client — registry and core code don't change. That's how you avoid two refactors instead of one.