# Licensing Storage Migration (Schema v2)

Persisted license records carry `schema_version`. The current schema
is **v2**; **v1** (records without the field, as written before this
phase) is the only supported upgrade path.

## Current persisted schema: v2

```json
{
  "provider": "keygen",
  "key_hint": "EY-1",
  "state": "ACTIVE",
  "organization": "Acme",
  "expires": "2030-06-30",
  "device_activated": true,
  "schema_version": 2,
  "updated_at": 1700000000
}
```

## Supported upgrade paths: v1 -> v2

`migrate_license_data()` copies the record, sets `schema_version: 2`,
and stamps integer `updated_at` only when absent. Provider values are
never rewritten. Migrating v2 returns an identical copy (strictly
idempotent). `load_state()` reports `ok`, `migrated`, `missing`,
`corrupt`, or `future_schema`; it never persists (callers save
explicitly via `save_state()`).

## Backup retention rule (5 most recent)

Every `save_state()` over an existing parseable file copies it to
`<store-dir>/licensing/backups/<name>-<nanoseconds>.json` — i.e.
`%APPDATA%/CIVOLINK/licensing/backups/` under the default Windows
location — then prunes to the newest 5. Writes commit atomically
(tmp file + flush + fsync + `os.replace`); a failed write leaves the
prior file untouched.

## Future schema protection policy

Records or on-disk payloads with `schema_version` above v2 raise
`FutureSchemaError`: `load_state()` reports `future_schema` and
`save_state()` refuses to overwrite, so a newer build's license is
never downgraded by an older one. Minimum supported schema is v1.
