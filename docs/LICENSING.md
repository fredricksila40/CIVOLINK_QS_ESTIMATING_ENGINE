# CIVOLINK Licensing Architecture (Integration Foundation)

Provider-neutral licensing boundary for CIVOLINK-QS. No provider is
integrated in this phase: there is no Keygen, Cryptlex, Paystack,
Lemon Squeezy, or Paddle code anywhere in the repository, and no
licensing server, database, admin portal, cryptography, or payment
flow was built.

## 1. Licensing architecture

```
UI (Help → License Status / Activate License…)
 ↓ (LicenseInfo snapshots only)
LicensingService (qs_engine/licensing/service.py)
 ↓  ↑  (ProviderResult only)
LicensingProvider ABC ── NullProvider (shipped default)
                     └─ FakeLicensingProvider (tests/dev only)
                     └─ KeygenProvider / CryptlexProvider (future)
LicenseStore (per-user license.json)
```

The desktop depends only on the `LicensingProvider` contract
(`activate` / `validate` / `deactivate` / `get_status` /
`get_license_info`). A future provider adapter implements those five
members; no caller changes.

## 2. Provider abstraction

`qs_engine/licensing/provider.py` defines the ABC plus two doubles.
`NullProvider` honestly reports `ACTIVATION_REQUIRED` with zero
network I/O and ships as the default so a fresh install is
unlicensed-but-functional. `FakeLicensingProvider` maps exact key
strings to canned results (plus a `network_down` flag) and is
docstring-marked never to ship as a real provider. Enforcement
policy (what unlicensed users may do) is deliberately absent — that
is a future product decision, not an architecture default.

## 3. Local storage approach

`LicenseStore` persists one JSON record
(`qs_engine/licensing/storage.py`): provider name, non-sensitive key
hint (last 4 chars), cached state/organization/expiry, device flag,
and the provider-supplied opaque artifact. Missing or corrupt files
read as `None` (fail closed to unlicensed, never crash).

Location is per-user, per-machine: `%APPDATA%/CIVOLINK/license.json`
on Windows, `~/.config/civolink/license.json` elsewhere,
overridable via `CIVOLINK_LICENSE_DIR` (tests use this). This
deliberately differs from the engine-root `config/` convention:
`config/` ships read-mostly defaults inside the install tree
(read-only `_MEIPASS` when frozen), while licensing state is
per-user and must survive upgrades.

## 4. Activation lifecycle

`UNLICENSED → (key entry) → provider.activate → ACTIVE` (persisted)
or a terminal verdict (`VALIDATION_ERROR`, `EXPIRED`, `REVOKED`,
`SUSPENDED`, `ACTIVATION_LIMIT_REACHED`). Only successful
activations are persisted; failed attempts leave existing state
untouched. `refresh()` re-validates; `deactivate()` clears the store
where the provider supports it (`supports_deactivation`).

## 5. Offline behavior

- **Online:** activation/validation flow through the provider.
- **Offline:** a cached `ACTIVE` record plus a retryable network
  failure yields `OFFLINE_GRACE` — a temporary outage is never
  reported as invalid, expired, or revoked. Without a cached
  activation, the same outage reports `NETWORK_ERROR`.
- **Reconnect:** `refresh()` re-validates and returns to `ACTIVE`.
- Local expiry is checked from the cached ISO date without network.
- There is **no hard-coded grace duration** in the application; any
  window (e.g. a cached `grace_until`) must arrive as
  provider/policy data. Do not invent a 30-day rule.

## 6. Security boundaries

The desktop application must NEVER contain: provider private keys,
admin API tokens, payment-provider secret keys, webhook secrets,
database credentials, or server-side signing secrets. No custom
encryption is implemented; the stored artifact is whatever signed/
encrypted blob the selected provider supplies. Public verification
material may be embedded only where the provider documents it safe.
Machine fingerprinting is deferred: no `Win32_ComputerSystemProduct`
UUID or raw hardware identifiers are collected or stored — the final
adapter must use the selected provider's official SDK/fingerprint,
minimum necessary data, with documented hardware-change limits.

## 7. How a future Keygen provider would be configured

`KeygenProvider` (`qs_engine/licensing/provider.py`) is implemented
and tested with mocked HTTP — no account exists yet, so production
needs two runtime values (never hard-coded, never committed):

- `KEYGEN_ACCOUNT_ID` (or constructor `account_id=`): the Keygen
  account slug/ID. Public identifier, safe to configure per
  deployment, but not embedded in source.
- `KEYGEN_PUBLIC_KEY` (or constructor `public_key=`): the account
  Ed25519 public key (base64 raw 32 bytes, or PEM) used solely for
  offline artifact verification. Public verification material only.

Wire it in `QSApp` in place of `NullProvider`:

```python
from qs_engine.licensing.provider import KeygenProvider
self.license_service = LicensingService(
    provider=KeygenProvider(fingerprint=<host-supplied>),
    store=LicenseStore())
```

Behavior: `activate()` runs validate-key then machine creation
(authenticating with the license key itself — no admin token);
`validate()` re-checks online, degrading to retryable
`NETWORK_ERROR` (service holds `OFFLINE_GRACE`) when a cached
signed artifact verifies or sits inside its provider-supplied
grace window, and failing closed on tamper or expiry; machine
creation conflicts map to `ACTIVATION_LIMIT_REACHED`; unknown
verdicts fail closed to `VALIDATION_ERROR`. Transport is stdlib
`urllib` (15s integer timeout); offline crypto needs the
`cryptography` package (pinned in `requirements.txt`). Machine
fingerprint remains host-supplied — adopt Keygen's documented
fingerprint mechanism before production.

## 8. How a future Cryptlex provider would be configured

Implement `CryptlexProvider(LicensingProvider)` the same way, using
Cryptlex offline activation + local activation persistence for the
cached record, mapping its status codes onto `LicenseState`. Same
single wiring point in `QSApp`.

## 9. How payment provisioning could later connect

```
PAYMENT → payment provider → order confirmation → license
provisioning → licensing provider → key/activation → CIVOLINK-QS
```

The desktop never trusts a payment provider directly and never sees
payment credentials; it consumes only the resulting license state
through this package. No payment integration exists today.

## 10. What must NEVER be placed in the desktop application

Private keys, admin API tokens, payment secrets, webhook secrets,
database credentials, server-side signing secrets, hard-coded API
tokens, custom license cryptography, custom license databases,
payment flows. `tests/test_licensing.py::test_no_provider_credentials_in_client_code`
AST-scans the package for embedded secret patterns on every run.
