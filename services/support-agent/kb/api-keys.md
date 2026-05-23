---
name: API keys
tags: [api-keys, auth, security, tokens, scopes]
last_reviewed: 2026-05-23
---

# API keys

## Token format

Versawiki API keys look like:

    vw_<prefix>_<secret>

- `vw_` is the literal product namespace.
- `<prefix>` is a 12-char URL-safe random string. **Safe to log.** We
  use it to look up the key row in O(1) before verifying the secret.
- `<secret>` is a 32-char URL-safe random string. We hash this with
  argon2id and store only the hash. The raw secret is shown **exactly
  once** at issue time.

## Issuing a key

Admin UI → **Settings → API keys → Issue new key**, or:

    POST /v1/admin/tenants/<tenant_id>/api-keys
    Authorization: Bearer vw_<admin_prefix>_<admin_secret>
    Content-Type: application/json
    { "label": "web-app", "scopes": ["query"] }

The 201 response includes the assembled token in a field shown once.
Persist it now — we cannot recover lost tokens.

## Listing keys

    GET /v1/admin/tenants/<tenant_id>/api-keys

Returns prefixes + metadata + revocation status. Never the raw token
and never the hash. Revoked keys remain in the list for audit.

## Revoking a key

Admin UI → **Settings → API keys → revoke**, or:

    DELETE /v1/admin/api-keys/<key_id>

Subsequent requests with the revoked token return 401.

## Reissuing (rotation)

We support reissue: the support agent can rotate a key you own. The
old key is revoked and a new one issued in the same operation. You'll
receive the new raw token in the same channel you asked from (chat,
email). We will ask for account verification before performing the
rotation.

## Security tips

- One key per integration. Easier to rotate when something leaks.
- Use the `query` scope by default. Promote to `admin` only for keys
  doing admin work.
- Store raw tokens in a secrets manager, not in source.
- Don't log raw tokens. Logging the prefix is fine.
- If you suspect a token leaked, revoke it now and reissue.

## What support can do

The agent can: list your keys, reissue a key you own (after account
verification), revoke a key you own. The agent cannot: see other
tenants' keys, reveal a hash, or recover a lost secret.
