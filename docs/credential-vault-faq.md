# Credential Vault FAQ

This FAQ explains the confusing parts of IntentFrame credential wiring: the vault service, the executor's `CredentialVault` object, the backend registry, executor packs, and `IF_VAULT_BACKEND`.

For the broader credential model, read [`credentials-vault.md`](credentials-vault.md) first. This page is the implementation-facing companion for people reading `intentframe_credentials`, `executor_sdk`, and executor packs.

---

## Short Version

There are three separate concepts that all use the word "vault":

1. The **credential-vault service** is a process on `credential-vault.sock`. It physically reads and writes secrets.
2. The **`CredentialVault` ABC** is a Python interface with methods like `get()`, `store()`, and `delete()`.
3. The **backend registry** maps names like `service`, `keyring`, `env`, and `hashicorp` to Python classes that implement the ABC.

In the normal runtime:

```text
executor.yaml
  credentials.backend: service

executor process
  creates ServiceVault
  ServiceVault calls VaultClient
  VaultClient talks over UDS to credential-vault.sock

credential-vault service
  reads IF_VAULT_BACKEND
  stores secrets in keyring / HashiCorp Vault / env backend
```

Rule of thumb: keep executor consumers on `credentials.backend: service`. Change `IF_VAULT_BACKEND` only when you want to change where the vault service stores secrets.

---

## What is `_BACKEND_REGISTRY`?

`_BACKEND_REGISTRY` in `intentframe_credentials.protocol` is an in-process plugin table:

```python
_BACKEND_REGISTRY: dict[str, type[CredentialVault]] = {}
```

It does not store secrets. It does not hold a running vault client. It maps a backend name to a class:

```text
"keyring"  -> KeyringVault
"env"      -> EnvVault
"hashicorp" -> HashiCorpVault
"service" -> ServiceVault
```

`register_backend(name, cls)` writes to the table. `create_vault(name, **options)` reads from it and constructs one instance.

---

## Who fills the backend registry?

Backend modules self-register when imported:

```text
intentframe_credentials.backends.keyring_backend   -> register_backend("keyring", KeyringVault)
intentframe_credentials.backends.env_backend       -> register_backend("env", EnvVault)
intentframe_credentials.backends.hashicorp_backend -> register_backend("hashicorp", HashiCorpVault)
intentframe_credentials.backends.service_backend   -> register_backend("service", ServiceVault)
```

`executor_sdk.services.credential_vault` imports those backend modules so executor startup can select any built-in backend by config name. It also re-exports `register_credential_vault`, which is an alias for `intentframe_credentials.protocol.register_backend`.

Executor packs can call that alias if they want to add a custom backend or replace an existing backend name.

---

## Does the executor honor a backend registered by a pack?

Yes, if two things are true:

1. The pack is loaded before `build_gateway()` creates the credential vault.
2. `executor.yaml` selects the backend name registered by the pack.

For the HTTP executor server path, this is the order:

```text
executor.server lifespan
  load executor.yaml
  _register_packs(config)
    pack.register_all()
      register_credential_vault("some_name", SomeVault)
  build_gateway(config)
    create_credential_vault(config.credentials)
      create_vault(config.credentials.backend)
```

So pack registration is honored by name. If a pack registers `"custom_vault"` and `executor.yaml` says `credentials.backend: custom_vault`, the executor instantiates that class.

If `executor.yaml` says `credentials.backend: service`, then a pack registration for `"keyring"` is irrelevant to the executor instance.

---

## Does a pack override the executor's backend?

Not directly.

There is no hierarchy where packs "win" or the executor "wins". There is a mutable registry and a config selector:

```text
register_credential_vault("keyring", MyKeyringVault)
  changes the class stored under the name "keyring"

credentials.backend: keyring
  chooses the class currently stored under "keyring"
```

If two packs register the same name, the last registration in pack load order wins for that name. That is normal for this registry pattern, but it means name collisions should be treated carefully.

The executor still decides which name to instantiate through `executor.yaml`.

---

## How is `IF_VAULT_BACKEND` different from `credentials.backend`?

They configure different processes.

`IF_VAULT_BACKEND` is read by the credential-vault service. It answers:

```text
Where does the vault service physically store secrets?
```

Examples:

```bash
IF_VAULT_BACKEND=keyring
IF_VAULT_BACKEND=hashicorp
IF_VAULT_BACKEND=env
```

`credentials.backend` in `executor.yaml` is read by the executor. It answers:

```text
How does the executor get a CredentialVault object?
```

Normal answer:

```yaml
credentials:
  backend: service
  options: {}
```

That means the executor creates `ServiceVault`, which is a client wrapper around `VaultClient` over the vault service's UDS socket.

In the normal runtime, these two settings are intentionally different:

```text
vault service: IF_VAULT_BACKEND=hashicorp
executor:      credentials.backend=service
```

That means secrets physically live in HashiCorp Vault, but executor still talks only to the local credential-vault service.

---

## What is the `service` backend?

`service` is not a physical storage backend. It is a consumer backend.

`ServiceVault` implements the `CredentialVault` ABC by delegating to `VaultClient`, which talks to the running credential-vault service over UDS.

Use `service` when a consumer process should not know whether secrets live in Keychain, HashiCorp Vault, env vars, or something else.

That is why the executor normally uses `credentials.backend: service`.

---

## Do adapters get the vault client?

Usually, no.

The executor gateway owns the `CredentialVault` instance. On each execution request:

1. The dispatcher resolves the adapter.
2. If `adapter.manifest().requires_credentials` is true, the gateway calls `vault.get(adapter_id, "api_key")`.
3. The gateway passes a plain `credentials` dict into `adapter.execute(action, params, credentials)`.

So the runtime path is:

```text
gateway owns vault client
  -> gateway fetches secret
  -> adapter receives dict | None for this call
```

`executor.main` also passes `credential_vault` into adapter constructors as part of `adapter_deps`, but most adapters accept `**_kwargs` and ignore it. That constructor injection is an escape hatch, not the normal credential flow.

---

## Why does the macOS pack call `register_credential_vault("keyring", KeychainVault)`?

Today, it is mostly documentation and symmetry with other pack registrations.

The macOS pack registers transport, auth, storage, adapters, and credential vault hooks from one `register_all()` function. The credential line says, "on macOS, the `keyring` backend means the OS Keychain."

But the current `KeychainVault` is just an alias:

```python
from executor_sdk.services.credential_vault import KeyringVault as KeychainVault
```

So the macOS pack re-registers the same class that `executor_sdk.services.credential_vault` already auto-registers under `"keyring"`. It does not change Jarvis if Jarvis uses `credentials.backend: service`.

This line would matter more if macOS later provided a distinct implementation, for example a native Keychain wrapper with behavior different from Python `keyring`.

---

## Why does the SDK expose `register_credential_vault` to pack authors?

For the same reason it exposes `register_adapter`, `register_transport`, and `register_auth_verifier`: packs are allowed to contribute executor implementations without changing executor core.

A third-party executor pack might add:

```python
register_credential_vault("aws_secrets_manager", AwsSecretsManagerVault)
```

Then a deployment could choose it:

```yaml
credentials:
  backend: aws_secrets_manager
  options:
    region: us-east-1
```

The SDK facade also keeps pack authors from importing internal packages directly. Pack code should import through `executor_sdk`, not reach around into executor internals.

---

## Is it good that packs mutate a global registry?

It is a tradeoff.

Pros:

- It matches the rest of the executor plugin model.
- Executor core stays deployment-neutral.
- Packs can add platform or organization-specific backends.
- Config can select implementations by name without importing concrete classes.

Cons:

- It is hidden process-global mutation.
- Import and pack load order can matter.
- Re-registering a common name like `keyring` can be surprising.
- The same backend names are used by both executor consumers and the vault service.
- The macOS registration currently looks more meaningful than it is because it re-registers an alias.

The pattern is defensible, but names and docs need to be explicit. Prefer adding unique backend names for custom behavior unless replacing a built-in name is deliberate.

---

## When should a pack register a credential backend?

Only when the pack provides a real backend implementation or a deliberate replacement for an existing one.

Good cases:

- `register_credential_vault("aws_secrets_manager", AwsSecretsManagerVault)`
- `register_credential_vault("gcp_secret_manager", GcpSecretManagerVault)`
- `register_credential_vault("company_vault", CompanyVault)`
- Replacing `"keyring"` with a platform-specific class that is meaningfully different.

Weak cases:

- Re-registering a built-in backend with the same class.
- Registering a backend just because adapters need secrets. Adapters usually should use the gateway-provided `credentials` dict or a service-specific client, not mutate the vault registry.

---

## What should normal deployments use?

For the executor:

```yaml
credentials:
  backend: service
  options: {}
```

For the vault service:

```bash
# workstation default
IF_VAULT_BACKEND=keyring

# headless/cloud/on-prem
IF_VAULT_BACKEND=hashicorp
VAULT_ADDR=...
VAULT_ROLE_ID=...
VAULT_SECRET_ID=...
```

Most deployments should not point executor directly at `keyring` or `hashicorp`. Keep executor on `service` so all consumers go through the same local vault service boundary.

---

## What happens if the vault service is down?

If the executor is configured with `credentials.backend: service`, `ServiceVault` is just a client to the vault service. If the service is down, calls like `vault.get(...)` fail when credentials are fetched.

The executor can still construct a `ServiceVault` object because construction only creates a client wrapper. The failure happens at request time when the gateway tries to fetch a secret.

For adapters that do not declare `requires_credentials=True`, the gateway does not fetch adapter credentials through this path.

---

## Why did this feel confusing?

Because four separate layers use overlapping words:

1. **Registry:** `register_backend("keyring", KeyringVault)` means "this name maps to this class in this Python process."
2. **Executor config:** `credentials.backend: service` means "executor should use a UDS client to reach the vault service."
3. **Vault service env:** `IF_VAULT_BACKEND=hashicorp` means "the vault service should store values in HashiCorp Vault."
4. **Adapter API:** `execute(..., credentials)` means "the gateway may pass a plain dict of fetched values for this one call."

The clean mental model is:

```text
Registry = available classes
executor.yaml = which class the executor constructs
IF_VAULT_BACKEND = where the vault service stores data
adapter credentials = per-call dict, not the registry
```

---

## Where should I read next?

- [`credentials-vault.md`](credentials-vault.md): vault service lifecycle, UDS API, delivery modes, and backend selection.
- [`../packages/intentframe-credentials/README.md`](../packages/intentframe-credentials/README.md): package-level implementation details.
- [`executor/architecture.md`](executor/architecture.md): executor registry pattern and pack loading.
- [`executor.md`](executor.md): executor credential isolation and adapter execution flow.
- [`plugin-profiles.md`](plugin-profiles.md): how `core.yaml` and `executor.yaml` load bundles and packs.
