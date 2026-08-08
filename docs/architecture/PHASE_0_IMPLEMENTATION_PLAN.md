---
title: Enterprise Platform — Phase 0 Implementation Plan
document_id: ENTERPRISE_PLATFORM_PHASE_0_PLAN
version: 1.0
status: Implemented on branch phase-0-enterprise-platform (2026-08-07) — pending review; Phase 1 NOT authorized
owner: Beacon Innovation, LLC
authoritative: true
classification: Internal
layer: Architecture (Level 4)
audience:
  - Architects
  - Engineers
  - AI Assistants
last_updated: 2026-08-07
---

# Enterprise Platform — Phase 0 Implementation Plan

> **Gate:** This is a plan for review. **No application code is to be written until
> this plan is approved.** Governed by
> [`ENTERPRISE_PLATFORM_ARCHITECTURE_PROPOSAL`](ENTERPRISE_PLATFORM_ARCHITECTURE_PROPOSAL.md)
> §K (approved decisions B1–B4 + standing decisions).

## Phase 0 objective

Make the **architectural boundary real** and prove the load-bearing seams —
separate Postgres, DB routing, multi-tenancy, platform-owned identity, RBAC,
tenant scoping, and wired audit — behind a minimal `/platform/` shell.
**No business features** (no Employee, no Credential, no Badging). When Phase 0
is done, every downstream requirement is enforced by scaffolding rather than by
memory: you cannot write a tenant-owned model without `tenant_id`, cannot get
platform access without an explicit `Membership`, and cannot create a cross-DB FK.

`aegis` is the internal package name only (not the product name); user-facing
strings say **"Enterprise Platform"**. Route: **`/platform/`**.

---

## 1. MUST BUILD IN PHASE 0  vs  ARCHITECTURE SEAMS ONLY

| Concern | Phase 0 disposition |
|---|---|
| Separate PostgreSQL + `dj-database-url` + `psycopg` | **MUST BUILD** |
| `PlatformRouter` (routing + migration isolation + relation guard) | **MUST BUILD** |
| Per-database deploy migrations (`Procfile`) | **MUST BUILD** |
| `aegis` package + `aegis.core` app + base abstractions | **MUST BUILD** |
| `Tenant` + seed Beacon = Tenant #1 (idempotent command) | **MUST BUILD** |
| `PlatformUser`, `ProviderIdentity`, `AuthenticationProvider` seam + **one** concrete provider (Beacon session) | **MUST BUILD** |
| RBAC: `Role`, `Permission`, `Membership` + access enforcement | **MUST BUILD** |
| Tenant context (contextvar) + `TenantMiddleware` + `TenantScopedManager` | **MUST BUILD** |
| Immutable `AuditEvent` + audit service, **actually wired** | **MUST BUILD** |
| `/platform/` shell: own `base.html`, login-gated placeholder dashboard | **MUST BUILD** |
| Tests for router, scoping, audit immutability, access denial, seed idempotency | **MUST BUILD** |
| **`Employee`** and people reference tables (Job/Dept/Company/Location) | **SEAM ONLY — Phase 1–2** |
| **`Credential`, `CredentialType`, `CredentialEvent`** | **SEAM ONLY — Phase 3** |
| **`Certificate`** (PKI metadata) | **SEAM ONLY — Phase 5** |
| **`BadgeTemplate`, `BadgePrintEvent`** | **SEAM ONLY — Phase 4** |
| **Local issuance client** + agent API + per-device auth | **SEAM ONLY — Phase 4+** |
| **Smart-card / PIV / printer / CA** provider adapters | **SEAM ONLY — Phase 4–5** |
| Additional auth providers (Entra/OIDC, Google, SAML, PIV/smart-card) | **SEAM ONLY — Phase 7** |
| PostgreSQL **Row-Level Security** policies | **SEAM ONLY — schema is RLS-ready now; enable Phase 7** |
| UUIDv7 | **SEAM ONLY — one-line swap; Phase 0 uses UUIDv4 via a central helper** |

**Seam discipline:** for every "seam only" item, Phase 0 leaves the *shape* correct
(tenant-scoped base classes, the provider interface, `PlatformUser`-not-`auth.User`,
UUID PKs, `/platform/` namespace, RLS-ready columns) so later phases are additive,
never a redesign. Phase 0 does **not** create the `people/identity/badging/hardware`
apps or any hardware/provider adapters.

---

## 2. Files / modules to CREATE

```
aegis/
  __init__.py
  apps.py                      # (optional package-level; core carries the AppConfig)
  urls.py                      # app_name='platform'; mounted at /platform/
  core/
    __init__.py
    apps.py                    # AppConfig, explicit label='aegis_core'
    fields.py                  # new_uuid() helper (uuid4 now; single swap point → uuid7)
    models.py                  # Tenant, PlatformUser, ProviderIdentity, Role,
                               #   Permission, Membership, AuditEvent + base models
    managers.py                # TenantScopedManager (+ AllTenantsManager escape hatch)
    context.py                 # contextvar current_tenant / current_platform_user + helpers
    middleware.py              # TenantMiddleware (resolves tenant + platform user per request)
    routers.py                 # PlatformRouter
    auth/
      __init__.py
      base.py                  # AuthenticationProvider ABC + provider registry
      beacon_session.py        # BeaconSessionProvider (incubation provider)
      access.py                # require_platform_access / require_permission decorators+mixins
    audit.py                   # record_event() service writing immutable AuditEvent
    views.py                   # dashboard placeholder (login + membership gated)
    urls.py                    # platform:dashboard
    migrations/__init__.py
    management/commands/__init__.py
    management/commands/seed_platform_tenant.py   # idempotent: Beacon = Tenant #1 (+ bootstrap admin)
    templates/aegis/base.html                     # own chrome, NOT Beacon-branded
    templates/aegis/dashboard.html
    static/aegis/                                  # own CSS (no Beacon assets)
    tests/__init__.py
    tests/test_router.py
    tests/test_tenant_scoping.py
    tests/test_audit.py
    tests/test_access_control.py
    tests/test_seed.py
```

Also create: `docs/architecture/PHASE_0_IMPLEMENTATION_PLAN.md` (this file) and, on
completion, changelog entries.

## 3. Files / modules to MODIFY

- `beaconinnovation/settings.py`
  - `INSTALLED_APPS += ['aegis.core']`.
  - `DATABASES`: keep `default` (SQLite, unchanged); add `platform` from
    `PLATFORM_DATABASE_URL` (see §6).
  - `DATABASE_ROUTERS = ['aegis.core.routers.PlatformRouter']`.
  - `MIDDLEWARE`: add `aegis.core.middleware.TenantMiddleware` **after** auth
    middleware.
  - *(Opportunistic, non-blocking):* fix `STATICFILES_STOREAGE` → `STORAGES`/
    `STATICFILES_STORAGE` typo — call out in review; do only if approved.
- `beaconinnovation/urls.py` — add `path('platform/', include('aegis.urls'))`
  **before** the `''` website catch-all (`urls.py:19`).
- `requirements.txt` — add `psycopg[binary]>=3.1`, `dj-database-url>=2.1`.
- `Procfile` — add per-DB migrate + platform seed (see §13).
- `CLAUDE.md` / deploy + changelog docs (see §16).

---

## 4. PostgreSQL provisioning & configuration (B1)

- Provision a **separate managed PostgreSQL instance** (Railway Postgres) for the
  platform — **not** shared with Beacon. Expose it as **`PLATFORM_DATABASE_URL`**.
- **Independent credentials** (B1): the platform DB has its own role/password,
  distinct from anything Beacon uses; least-privilege (owns only its schema).
- Beacon's `default` stays SQLite (out of scope; the ephemeral-disk data-loss issue
  is a **separate recorded risk**, not fixed here).
- Parity note: production/staging **must** use Postgres. Local dev may fall back to
  a separate `db_platform.sqlite3` when `PLATFORM_DATABASE_URL` is unset (dev
  convenience, loud warning) — **or** run Postgres via docker-compose for parity.
  *Recommendation: docker-compose Postgres for anyone touching migrations/RLS; the
  sqlite fallback is only for quick UI/dev loops.* (Minor open choice, non-blocking.)

## 5. Django database routing (B1)

`PlatformRouter` is the enforced boundary:

- `PLATFORM_APPS = {'aegis_core'}` now; **reserve** `people/identity/badging/hardware`
  labels (added as those apps are created).
- `db_for_read` / `db_for_write`: `'platform'` if `model._meta.app_label in
  PLATFORM_APPS`, else `None` (defer → `default`).
- `allow_migrate(db, app_label, ...)`: platform apps migrate **only** on
  `platform`; all other apps (`auth`, `admin`, `contenttypes`, `sessions`, Beacon
  apps) migrate **only** on `default`. Return explicit `True`/`False`, never `None`.
- `allow_relation`: allow only when both objects are on the same side of the
  boundary; **deny cross-DB relations** (belt-and-suspenders against accidental
  FKs). This is what makes "no cross-DB FK to `auth.User`" (B4) structurally true.

## 6. Environment variables

| Variable | Purpose | Notes |
|---|---|---|
| `PLATFORM_DATABASE_URL` | Platform Postgres DSN | **required** in prod/staging; dev may omit → sqlite fallback |
| *(existing)* `DJANGO_SECRET_KEY`, `DJANGO_DEBUG` | unchanged | platform reuses Django's signing/session for now |

All platform-specific env uses the **`PLATFORM_*`** prefix (extraction hygiene —
the platform never reads Beacon's finance/OTA/Cloudinary settings).

## 7. Migration strategy

- `makemigrations aegis_core` → migrations live under `aegis/core/migrations/`.
- Apply per DB: `migrate` (default, unchanged Beacon/Django apps) **and**
  `migrate --database=platform` (aegis apps only, enforced by `allow_migrate`).
- No cross-DB data migrations. Seed data (Tenant #1) is an **idempotent management
  command**, not a migration (mirrors `bootstrap_portal`), so it survives re-runs.

---

## 8. Tenant foundation (standing decision 4)

- `Tenant` (core): `id` (UUID PK), `tenant_code` (business key, globally unique,
  e.g. `BEACON`), `name`, `status`, audit columns. `Tenant` is the **only**
  tenant-owned model without a `tenant_id`.
- `TenantScopedModel` (abstract base): `id` UUID PK, `tenant` FK → `Tenant`
  (`NOT NULL`), `created_at/updated_at`, `created_by/updated_by` (UUID → PlatformUser,
  same DB), default manager = `TenantScopedManager`. Every future tenant-owned
  model inherits this — RLS-ready columns present from day one.
- `seed_platform_tenant` command: idempotently create Beacon = **Tenant #1**, plus
  a clearly-separated **bootstrap admin** `PlatformUser` + `Membership` so the owner
  can reach the shell (see §9). Idempotent = safe on every deploy.

## 9. PlatformUser & authentication-provider foundation (B2, B4)

- `PlatformUser` (core): UUID PK, display fields, `is_active` — **no FK to
  `auth.User`** (B4). Authoritative application principal.
- `ProviderIdentity` (core): `(provider, subject)` → `PlatformUser`. Stores the
  **stable external subject identifier** per provider (B4). Unique on
  `(provider, subject)`.
- `AuthenticationProvider` ABC (`auth/base.py`): `authenticate(request) →
  external subject | None`; concrete providers register in a small registry.
- **Phase 0 concrete provider = `BeaconSessionProvider`** (incubation, per B2):
  reads the already-authenticated Beacon `auth.User` from the request, derives a
  stable subject, resolves/records a `ProviderIdentity`, and yields the mapped
  `PlatformUser`. This **reuses Beacon auth as one provider** — it does **not**
  build a new username/password system.
- **Hard rule (B2):** authentication ≠ access. A resolved `PlatformUser` with **no
  active `Membership`** in the target tenant is **denied** (access enforced in §10).
  First access is granted only via the bootstrap admin seed or an explicit grant.
- **Seam only:** Entra/OIDC, Google, SAML, PIV/smart-card providers — new classes behind
  the same ABC later; no PlatformUser/RBAC/session rework needed to add them.
- Any temporary local dev credential path stays isolated in the bootstrap command,
  clearly labeled dev/bootstrap, never the long-term mechanism.

## 10. RBAC foundation (B2)

- `Permission` (core): stable string `code` (e.g. `platform.view_dashboard`),
  description. Seeded set is tiny in Phase 0.
- `Role` (core): tenant-scoped named set of permissions (M2M), plus a small number
  of system roles (e.g. Tenant Admin). **Credential Administrator** role is
  *reserved/seeded but unused* until the credential domain exists.
- `Membership` (core): `(PlatformUser, Tenant, Role)` — the object that grants
  access. Unique per `(platform_user, tenant, role)`.
- Enforcement (`auth/access.py`): `require_platform_access` (resolves provider →
  PlatformUser → active Membership in current tenant, else 403) and
  `require_permission(code)` decorator/mixin. **Every** platform view uses these —
  never UI-only gating (explicitly closing Beacon's authentication-only gap).

## 11. Tenant context / scoping

- `context.py`: `contextvar`s for `current_tenant` and `current_platform_user`,
  with getters/setters and a context manager for background/command use.
- `TenantMiddleware`: after auth middleware, resolves the platform user (via the
  provider) and the active tenant for the request, sets the contextvars, clears
  them in `finally`. During single-tenant incubation the tenant resolves to
  Beacon; the mechanism is already multi-tenant.
- `TenantScopedManager`: default queryset **filters by `current_tenant`**; raises
  if no tenant is set (fail-closed). An explicit `all_tenants()` escape hatch is
  provided for admin/ops and is itself permission-gated. No un-scoped `.objects`
  path to tenant data.

## 12. Audit foundation (standing decision 7)

- `AuditEvent` (core): immutable (override `save` to block updates, `delete` to
  raise — mirrors `finance.AuditLog` at `finance/models.py:531-538`), keyed by
  string `model_name` + `object_id` (UUID) — **no `ContentType` FK** (cross-DB
  safe), plus `tenant`, `actor` (PlatformUser), `action`, `occurred_at`, `detail`
  (JSON), request metadata (ip/user-agent).
- `audit.py::record_event(...)`: the single write path, called by services —
  **actually wired** in Phase 0 for the foundational events (membership
  grant/revoke, provider-identity link, bootstrap seed). This closes the "mixin
  exists but is never called" gap (`finance/mixins.py` is dormant today).
- Domain-specific immutable histories (`CredentialEvent`, `BadgePrintEvent`) reuse
  this pattern later — **seam only** now.

## 13. `/platform/` application shell

- `aegis/urls.py` (`app_name='platform'`) mounted at `/platform/`, **before** the
  website catch-all.
- `templates/aegis/base.html`: the platform's **own** chrome and CSS — must **not**
  extend or inherit any Beacon app base or branding (extraction hygiene, §H).
- `dashboard` view: login + membership gated; renders tenant name, the signed-in
  `PlatformUser`, their roles, and an explicit "no business modules yet — Phase 0
  foundation" state. This is the proof-of-life that all seams work end-to-end.

## 14. Testing strategy

- Runner: `python manage.py test aegis.core` (no CI exists yet — see risk).
- Tests declare `databases = {'default', 'platform'}` so the runner builds
  `test_platform`; verify:
  - **Router:** aegis models read/write `platform`; `allow_migrate` isolates
    per DB; `allow_relation` denies a cross-DB relation.
  - **Tenant scoping:** a scoped queryset returns only current-tenant rows;
    no-tenant access fails closed; a second tenant's rows are invisible.
  - **Access control:** authenticated-but-no-Membership → 403; with Membership +
    permission → 200; UI-only bypass impossible.
  - **Audit immutability:** update/delete of `AuditEvent` raises; `record_event`
    writes exactly once.
  - **Seed idempotency:** running `seed_platform_tenant` twice yields one Tenant #1
    and no duplicate memberships.
- Parity: run the suite against **Postgres** for the `platform` DB before sign-off
  (RLS/UUID/constraints behave differently from sqlite).

## 15. Deployment implications

- **Provision** the platform Postgres and set `PLATFORM_DATABASE_URL` in Railway
  **before** the first deploy of this branch.
- `Procfile` (new):
  ```
  web: python manage.py migrate && \
       python manage.py migrate --database=platform && \
       python manage.py create_wlj_superuser && \
       python manage.py bootstrap_portal && \
       python manage.py seed_platform_tenant && \
       gunicorn beaconinnovation.wsgi --log-file -
  ```
- Deploy order matters: if `PLATFORM_DATABASE_URL` is missing at boot, fail fast
  with a clear error rather than silently falling back in production.

## 16. Rollback strategy

Phase 0 is **additive and isolated** — it does not touch Beacon data or schema:

- **Code rollback:** revert the branch/commit — removes `aegis.core` from
  `INSTALLED_APPS`, the router, the `/platform/` include, the middleware, and the
  `Procfile` additions. Beacon runs exactly as before.
- **Data rollback:** the platform DB is a **separate instance** — it can be
  dropped/re-created independently with zero impact on Beacon's `default` DB.
- **No destructive default-DB migrations** are introduced, so there is nothing to
  reverse on Beacon's side. This clean rollback is a direct benefit of B1.

## 17. Documentation changes

- Update the changelog (`docs/beacon_claude_changelog.md`) on completion.
- Update deploy doc (`docs/beacon_claude_deploy.md`) with the second DB, the
  per-DB migrate step, and `PLATFORM_DATABASE_URL`.
- Reconcile `CLAUDE.md` (it currently claims Postgres/`DATABASE_URL` for Beacon,
  which is false) and add an Enterprise Platform section pointing at the proposal +
  this plan.
- (Later) a dedicated Enterprise Platform Master Strategy is out of scope here.

---

## 18. Open (non-blocking) choices to confirm during build

1. **Local dev DB parity** — docker-compose Postgres vs. `db_platform.sqlite3`
   fallback (§4). *Rec: Postgres for migration/RLS work.*
2. **UUID version** — start UUIDv4 via `new_uuid()`; swap to UUIDv7 in one place
   later. *Rec: accept v4 for Phase 0.*
3. **Fix `STATICFILES_STOREAGE` typo** while in settings (§3). *Rec: yes, tiny.*
4. **Session ownership detail** — Phase 0 reuses Django's session with the Beacon
   provider; a fully platform-owned session cookie/policy can be layered in Phase 7
   without model changes. *Rec: accept for incubation.*

None of these block starting Phase 0 once the plan itself is approved.

## 19. Implementation notes (2026-08-07)

Built on branch `phase-0-enterprise-platform`. Deviations from the plan, all
minor:

- **Consolidated URLs** into `aegis/urls.py` (no separate `aegis/core/urls.py`) —
  simpler for a single view; namespace `platform` unchanged.
- **`created_by`/`updated_by`** implemented as nullable `UUIDField`s (not FKs) on
  the shared `TimeStampedModel`, as the plan described; the authoritative "who did
  what" record is `AuditEvent`, not these columns.
- **`PlatformUser`, `ProviderIdentity`, `Permission` are global** (not tenant-
  scoped): a consultant/auditor may span tenants; access is via tenant-scoped
  `Membership`. `Role` and `Membership` are tenant-scoped.
- **No `admin.py`** for `aegis` (Django admin's `LogEntry` writes `ContentType`
  rows to `default` — would cross the boundary). The platform will get its own UI.
- **`STATICFILES_STOREAGE` typo left untouched** (owner decision 3) and recorded
  as separate Beacon tech debt.
- Local dev Postgres provisioned as role/db `beacon_platform` (independent creds).

## Revision History

| Version | Date | Description |
|---|---|---|
| 0.1 | 2026-08-07 | Initial Phase 0 implementation plan for review. No implementation. |
| 1.0 | 2026-08-07 | Implemented on branch `phase-0-enterprise-platform`; 27 platform tests pass on PostgreSQL; Beacon behavior unchanged. Pending review; Phase 1 not authorized. |
