# Keycloak (dev OIDC provider)

Keycloak provides the development OpenID Connect (OIDC) identity provider for
the DPRK CTI platform. It is wired into `docker-compose.yml` as the `keycloak`
service and auto-imports a rendered realm export on first boot, so the dev
environment is fully repeatable with no manual admin-console clicks.

## Start

```sh
docker compose up -d keycloak
# Wait ~30 seconds for the realm import to complete on first run.
```

## Admin console

- URL: <http://localhost:8081/admin/>
- Username: `admin`
- Password: value of `KEYCLOAK_ADMIN_PASSWORD` from the repo-root `.env`

## Realm

- Name: `dprk-cti`
- Source template (committed): `infra/keycloak/realm-export.template.json`
- Rendered import file (ephemeral): `keycloak_realm_rendered` named volume
  written at startup by the `keycloak-init` service (PR #50)
- Auto-imported via `start-dev --import-realm`

## Test users

The user passwords below are substituted at container-startup time from
`DPRK_DEV_USER_PASSWORD` in the repo-root `.env` (default: `test1234`,
preserving the historical dev experience). The template itself contains
no plaintext credentials — only the `__DPRK_DEV_USER_PASSWORD__` marker.

| Email               | Password (env-driven)        | Realm roles         |
| ------------------- | ---------------------------- | ------------------- |
| `analyst@dev.local` | `$DPRK_DEV_USER_PASSWORD`    | `analyst`           |
| `admin@dev.local`   | `$DPRK_DEV_USER_PASSWORD`    | `admin`, `analyst`  |
| `policy@dev.local`  | `$DPRK_DEV_USER_PASSWORD`    | `policy`            |

These three roles map to the §9.3 role matrix in
`DPRK_Cyber_Threat_Dashboard_설계서_v2.0.md`.

To override the default for a contributor's local machine, set
`DPRK_DEV_USER_PASSWORD` in `.env` before `docker compose up`. All three
users share the same password by design (single-knob dev experience).

## OIDC client

| Field           | Value                                                |
| --------------- | ---------------------------------------------------- |
| Client ID       | `dprk-cti-api`                                       |
| Client type     | confidential (`publicClient: false`)                 |
| Client secret   | `$DPRK_DEV_CLIENT_SECRET` (env-driven, default: `dev-secret-rotate-in-prod`) |
| Flow            | Authorization Code + PKCE (S256)                     |
| Redirect URI    | `http://localhost:8000/api/v1/auth/callback`         |
| Web origins     | `http://localhost:5173`, `http://localhost:8000`     |

## Issuer URLs

- Internal (api/worker → keycloak over the `backend` Docker network):
  `http://keycloak:8080/realms/dprk-cti`
- Host-facing (browser redirects, discovery from outside compose):
  `http://localhost:8081/realms/dprk-cti`

The API service (Step 2 of P1.1) will validate JWTs against the OIDC discovery
document at `<issuer>/.well-known/openid-configuration`.

## How the render works

PR #50 closed the Phase 0 "remove plaintext passwords from committed JSON"
deferral by:

1. Renaming `realm-export.json` → `realm-export.template.json` with two
   placeholder markers — `__DPRK_DEV_USER_PASSWORD__` (3 occurrences in the
   `credentials` blocks) and `__DPRK_DEV_CLIENT_SECRET__` (1 occurrence in
   the OIDC client's `secret` field).
2. Adding a `keycloak-init` compose service (busybox:1.36) that runs `sed`
   over the template at startup, substitutes both env vars, and writes the
   rendered JSON to the `keycloak_realm_rendered` named volume.
3. Having the `keycloak` service mount that volume (read-only) at
   `/opt/keycloak/data/import/` and gate on
   `depends_on: keycloak-init: { condition: service_completed_successfully }`.

The committed template is the source of structural truth (roles, clients,
flows, claim mappers, etc.); the env vars are the credential surface.
Static-source regression test
`services/api/tests/unit/test_realm_export_template_no_plaintext.py`
fails CI if the template ever regrows a plaintext default password or
client secret.

## Re-exporting a modified realm

If you change the realm via the admin console and want to commit the change:

```sh
docker compose exec keycloak \
  /opt/keycloak/bin/kc.sh export \
  --realm dprk-cti \
  --file /tmp/export.json
docker compose cp keycloak:/tmp/export.json infra/keycloak/realm-export.template.json
```

Then manually re-introduce the `__DPRK_DEV_USER_PASSWORD__` /
`__DPRK_DEV_CLIENT_SECRET__` placeholders in the new export — Keycloak's
export emits the live (substituted) values, which would re-commit
plaintext credentials. The regression test will fail-loud if you forget.
Review the diff carefully — Keycloak exports are verbose and include
runtime IDs that should not always be committed.

## Production note

`dev-secret-rotate-in-prod` is the literal default for `DPRK_DEV_CLIENT_SECRET`
used only when no production override is in place. Production deployments
MUST regenerate the client secret and store it in a real secret manager
(per §9.4 of the design doc). The `KEYCLOAK_ADMIN_PASSWORD`,
`DPRK_DEV_USER_PASSWORD`, and the realm itself must also be replaced with
production-grade values and a non-`start-dev` Keycloak boot mode.
