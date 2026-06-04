# intentframe-supervisor

The IntentFrame supervisor: a process manager that spawns the runtime service
graph, waits for health, monitors child processes, and handles graceful
shutdown. It depends on [`intentframe-runtime`](https://github.com/intentframe/intentframe)
for the three substrate services it launches (`policy_registry.server:app`,
`executor.server:app`, `intentframe_server.server:app`).

Installing it provides the `intentframe` and `intentframe-backend` console
scripts and ships the default, dependency-free 3-service profile
(`supervisor/config/supervisor.yaml` — no resource-registry).

```bash
pip install intentframe-supervisor          # base: 3-service substrate
pip install "intentframe-supervisor[native]" # + resource-registry flavour
```

## Flavours are config-driven

The supervisor never imports or auto-detects optional services. Which services
start is decided entirely by the profile YAML it is pointed at, via
`--config <path>` or `INTENTFRAME_SUPERVISOR_CONFIG`:

- **Base** — the packaged `supervisor/config/supervisor.yaml` (policy-registry,
  executor, intentframe-server). No resource-registry.
- **`[native]`** — installs `intentframe-native-kit`, which provides the
  resource-registry service module and the 4-service profile
  (kit `supervisor_profile.yaml` in the installed package). Select it explicitly:

```bash
python -m supervisor.main start \
  --config "${KIT}/supervisor_profile.yaml"
```

The `[native]` extra only makes that module and profile *present*; it does not
change supervisor behavior on its own. This is the substrate the first-party
gateway / CLI manage.
