# Keycloak (dev OIDC provider)

Keycloak provides the development OpenID Connect (OIDC) identity provider for
the DPRK CTI platform. It is wired into `docker-compose.yml` as the `keycloak`
service and auto-imports `realm-export.json` on first boot, so the dev
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
- Source of truth: `infra/keycloak/realm-export.json`
- Auto-imported via `start-dev --import-realm`

## Test users

| Email               | Password   | Realm roles         |
| ------------------- | ---------- | ------------------- |
| `analyst@dev.local` | `test1234` | `analyst`           |
| `admin@dev.local`   | `test1234` | `admin`, `analyst`  |
| `policy@dev.local`  | `test1234` | `policy`            |

These three roles map to the §9.3 role matrix in
`DPRK_Cyber_Threat_Dashboard_설계서_v2.0.md`.

## OIDC client

| Field           | Value                                                |
| --------------- | ---------------------------------------------------- |
| Client ID       | `dprk-cti-api`                                       |
| Client type     | confidential (`publicClient: false`)                 |
| Client secret   | `dev-secret-rotate-in-prod` (literal placeholder)    |
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

## Re-exporting a modified realm

If you change the realm via the admin console and want to commit the change:

```sh
docker compose exec keycloak \
  /opt/keycloak/bin/kc.sh export \
  --realm dprk-cti \
  --file /tmp/export.json
docker compose cp keycloak:/tmp/export.json infra/keycloak/realm-export.json
```

Review the diff carefully — Keycloak exports are verbose and include
runtime IDs that should not always be committed.

## Production note

`dev-secret-rotate-in-prod` is a literal placeholder for local development
only. Production deployments MUST regenerate the client secret and store it
in a real secret manager (per §9.4 of the design doc). The
`KEYCLOAK_ADMIN_PASSWORD` and the realm itself must also be replaced with
production-grade values and a non-`start-dev` Keycloak boot mode.
