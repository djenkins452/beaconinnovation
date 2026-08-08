---
title: Enterprise Platform — Discovery & Architecture Proposal
document_id: ENTERPRISE_PLATFORM_ARCHITECTURE_PROPOSAL
version: 1.0
status: Decisions Approved (2026-08-07) — Phase 0 planning; application implementation NOT yet authorized
owner: Beacon Innovation, LLC
authoritative: true
classification: Internal
layer: Architecture (Level 4)
audience:
  - Architects
  - Engineers
  - Product Managers
  - AI Assistants
last_updated: 2026-08-07
---

# Enterprise Platform — Discovery & Architecture Proposal

> **Working codename:** the product has no permanent name. This document uses
> **"Enterprise Platform"** for the product and **`aegis`** as the working
> code-package name (see [§B](#b-recommended-application-boundary) — the package
> **must not** be named `platform`, which shadows Python's stdlib, nor `beacon_*`,
> which couples it to the incubator). Final naming is an owner decision.
>
> **Owner decision (2026-08-07):** `aegis` is approved as a **temporary internal
> package name only** — it is **not** the product name. User-facing terminology
> stays neutral (**"Enterprise Platform"** / **"Identity & Credential
> Management"**) until a product name is deliberately selected. `/platform/` is
> approved as the incubation route. See [§K](#k-approved-architecture-decisions-2026-08-07).

This was a discovery and architecture proposal for review. The blocking decisions
in [§J](#j-risks--decisions) were **reviewed and approved with refinements on
2026-08-07** — see [§K](#k-approved-architecture-decisions-2026-08-07). Application
functionality is **still not authorized**: the next gate is approval of the
separate **Phase 0 Implementation Plan** (`docs/architecture/PHASE_0_IMPLEMENTATION_PLAN.md`).

---

## Executive Summary

The Enterprise Platform is a new, commercial, **multi-tenant SaaS** for identity,
credentialing, and badging — starting with a clean Employee/organization data
model and growing toward smart-card/PIV issuance, PKI certificate lifecycle, and
badge printing, and eventually a broader HCM. It will be **incubated inside the
existing Beacon Django application** but is explicitly designed to be **extracted**
later to its own name, domain, database, and deployment. Beacon Innovation LLC is
**Tenant #1**, not the platform's owner-in-code.

Discovery of the actual repository produced one finding that reframes the whole
initiative and three that govern the design:

1. **Beacon has no durable database today.** Despite CLAUDE.md and the deploy
   docs describing PostgreSQL via `DATABASE_URL`, `settings.py` wires **only
   SQLite**, with no `dj-database-url` and no `psycopg`. The committed
   `db.sqlite3` runs on Railway's **ephemeral** filesystem. So the requirement
   for "a separate PostgreSQL database" is not "a second Postgres beside Beacon's
   Postgres" — it is **the project's first managed Postgres**. This *lowers* the
   cost of the requested separation and *raises* its value.

2. **A separate database means no cross-database foreign keys.** Django does not
   support FKs spanning databases. This single fact is the enforcement mechanism
   for three of the owner's requirements at once: *Users are not Employees*,
   *tenant isolation*, and the *extraction test*. The platform therefore **owns
   its own identity** — it holds no DB-level FK to Beacon's `auth.User`; Beacon is
   only an authentication *provider* mapped at the application layer.

3. **The cloud app cannot touch the hardware.** The web tier runs on Railway
   (Linux, cloud). It cannot reach a USB smart-card reader, a PIV card, or an
   Evolis printer plugged into a MacBook. Badging/PIV therefore **requires a local
   issuance-client agent** on the workstation that performs hardware operations
   and syncs metadata to the platform over an authenticated API. This is a
   first-class architectural boundary, not an afterthought.

4. **The house patterns already point the right way.** `finance` and
   `admin_console` already use **UUID primary keys** and an **immutable,
   ContentType-free `AuditLog`** (keyed by `model_name` + `object_id` strings).
   Both patterns are cross-database-safe and are reused here. What is missing —
   tenancy, RBAC, wired-up auditing, Postgres — is exactly what the platform adds.

**Recommendation:** a **modular monolith** — a cluster of cohesive Django apps
under one code package (`aegis`), routed at `/platform/`, backed by its **own
managed PostgreSQL database** via Django multi-database routing, **multi-tenant
(shared-schema, mandatory `tenant_id`) from day one**, with its own identity,
RBAC, audit, templates, and configuration. Do **not** build microservices; do
**not** generalize Person/Employment/Identity/Credential yet; do **not** store
SSNs, private keys, CA material, or PINs in the application database.

---

## A. Current Beacon Architecture (what exists that matters)

| Concern | Reality in the repo |
|---|---|
| Framework / runtime | Django **5.1.4**, Python **3.13.1**, single WSGI monolith, Gunicorn + WhiteNoise, hosted on **Railway** (push-to-`main` auto-deploy; **no CI**). |
| Apps | `website` (marketing, 0 models), `finance` (flagship, 8 models), `admin_console` (Claude task API, `AdminTask`), `products` (download portal + OTA), `wlj` (legacy investor dashboard — **off-limits**), `distribution` (middleware/views, filesystem-backed, 0 models). |
| **Database** | **SQLite only.** `settings.py` hardcodes `sqlite3`; **no `DATABASE_URL`/`dj-database-url`, no `psycopg`.** `db.sqlite3` is git-tracked and on Railway's **ephemeral** disk (writes lost on redeploy). Docs claim Postgres; code does not. |
| Identity | Django default **`auth.User`** (no `AUTH_USER_MODEL` override). Session auth, `ModelBackend`, no custom backend. |
| Login | **Four independent hand-rolled login views** (`wlj`, `finance`, `products`, and the default `LOGIN_URL='wlj:login'`). No shared login. |
| Authorization | **Authentication-only.** Universal `@login_required`; no `permission_required`/`staff_member_required`/mixins. The only real role logic is in `products`: Django **Groups as flags** (`portal_must_change_password`) and an M2M `Product.authorized_users`; **404-not-403** to hide existence; **signed-token** (`django.core.signing`, 20-min TTL) for cookieless iOS OTA. |
| PK strategy | `finance` + `admin_console`: **UUIDv4** PKs. `wlj` + `products`: `BigAutoField`. |
| Audit | `finance.AuditLog`: **immutable** (save/delete blocked), keyed by `model_name`+`object_id` strings (**no ContentType FK** → cross-DB safe). `AuditLogMixin` exists but is **not wired** into any view (dormant). No `LOGGING` config. |
| Tenancy | **None anywhere.** No org/tenant concept. |
| Routing | Root `beaconinnovation/urls.py`; each app `include()`d under a prefix with its own `app_name`. `website` is the catch-all at `''` (must stay last). |
| Templates / UI | **App-local** templates (`APP_DIRS=True`, global `DIRS=[]`); **no shared base template**; each app ships its own `base.html` and a *different* CSS approach (finance: inline; wlj: Tailwind CDN; admin_console: Bootstrap CDN; products/website: bundled Bootstrap). No design system. |
| Deploy/migrations | `Procfile`: `migrate` → `create_wlj_superuser` → `bootstrap_portal` → gunicorn. **Migrations run on every deploy** (default DB only). Idempotent bootstrap commands work around Railway's ephemeral disk. |
| Secrets | Railway env vars; local `.env` (gitignored). `CLAUDE_API_KEY` default is a committed placeholder. |
| Latent bugs | `STATICFILES_STOREAGE` misspelled (manifest storage silently inactive); SQLite-vs-documented-Postgres mismatch. |

**Reusable assets for the platform:** the UUID-PK convention, the immutable
ContentType-free AuditLog design, the signed-token pattern for stateless/edge
auth, the idempotent management-command bootstrap discipline, the per-app
self-contained template model, and the phase-gated, changelog-backed delivery
process. **Anti-patterns to *not* inherit:** authentication-only authorization,
dormant auditing, single-tenant assumptions, and SQLite-on-ephemeral-disk.

---

## B. Recommended Application Boundary

**Where it lives:** a single code package — **`aegis/`** (working name) — at the
repository root, containing a small cluster of Django apps with strong domain
boundaries:

```
aegis/
  core/        # Tenant, PlatformUser, Role, Permission, Membership, AuditEvent,
               #   base models/managers, tenant middleware, DB router, auth seam
  people/      # Employee, Company, Department, Job, Location
  identity/    # Credential, CredentialType, Certificate, credential lifecycle/events
  badging/     # BadgeTemplate, BadgePrintEvent, photo handling
  hardware/    # provider abstractions (reader/card/printer/CA) + issuance-client API
  urls.py      # app_name='platform', mounted once
  templates/aegis/  base.html (own theme, NOT Beacon-branded)
  static/aegis/
```

**Why a package of apps, not one app and not microservices:** the domains
(org/people, credential/PKI, badging) evolve on different clocks and deserve
module boundaries, but a **modular monolith** keeps one deploy, one database
connection pool, and simple transactions — matching Beacon's operational reality
and the owner's "no microservice maze" directive. A clean package is also the
unit of extraction (§H).

**Routing:** add `path('platform/', include('aegis.urls'))` to
`beaconinnovation/urls.py` **before** the `''` website catch-all. One namespace
(`platform:...`). The platform serves its own `base.html` and static assets — it
must **not** inherit any Beacon app's chrome or branding.

**Naming (decision, non-blocking but do early):** the package name must be stable
and neutral. **Do not** use `platform` (shadows the stdlib module and collides
with the already-approved *Beacon Platform* shared-infra strategy) or `beacon_*`
(couples to the incubator). `aegis` is a placeholder; the owner picks the real one.

**Relationship to the existing "Beacon Platform" strategy:** that document
(`BEACON_PLATFORM_MASTER_STRATEGY`) defines *shared infrastructure* (identity,
deployment, audit, notifications) for Beacon's product portfolio. The Enterprise
Platform is a **Level-3 product**, not that shared infra. During incubation it may
*consume* a couple of Beacon services (authentication, hosting); it must not
*become* part of Beacon's shared-services layer, or extraction breaks. The name
collision between "Enterprise Platform" and "Beacon Platform" is itself a reason
to choose a distinct product name early.

---

## C. Database Architecture

### C.1 Configuration — a second, managed PostgreSQL database

Introduce PostgreSQL as a **named** Django database dedicated to the platform,
alongside Beacon's `default`:

```python
# conceptual — settings.py
DATABASES = {
    'default':  <Beacon's existing DB>,               # unchanged
    'platform': dj_database_url.parse(os.environ['PLATFORM_DATABASE_URL']),
}
DATABASE_ROUTERS = ['aegis.core.routers.PlatformRouter']
```

Add `psycopg[binary]` and `dj-database-url` to requirements. Provision a
**separate Railway Postgres instance** and expose it as `PLATFORM_DATABASE_URL`.
Beacon's own `default` can remain SQLite for now (out of scope), but see the
data-loss risk in §J.

### C.2 The router is the boundary

`PlatformRouter` sends every read/write for `aegis.*` apps to `platform` and
everything else to `default`, and — critically — **isolates migrations**:

- `allow_migrate` returns `True` for `aegis.*` **only** on `platform`, and for
  Django's own apps (`auth`, `admin`, `contenttypes`, `sessions`) and Beacon apps
  **only** on `default`.
- `allow_relation` denies relations across the two databases (belt-and-suspenders
  against accidental cross-DB FKs).

Deploy runs migrations per database:
`python manage.py migrate` (default) **and** `python manage.py migrate --database=platform`.
The `Procfile` must be updated to run both. This is a **blocking** operational item.

### C.3 Consequences of separation (embrace them)

- **No cross-database FKs.** The platform holds **no FK to `auth.User`**. It links
  to Beacon identities (when needed) by storing a stable external subject id as a
  plain `UUIDField`/`CharField` with **no** DB constraint (§F).
- **No ContentType framework in platform models.** Django's `ContentType` lives in
  `default`; a generic FK would cross databases. The audit/event tables therefore
  use the finance pattern (string `model_name` + `object_id`), which is already
  proven in-repo.
- **Do not register platform models in Django's shared admin.** Admin's `LogEntry`
  writes `ContentType` rows to `default`. Build the platform's **own** admin/console
  UI (the product wants a real enterprise UI anyway).
- **Transactions do not span databases.** No workflow legitimately needs an atomic
  write across Beacon and the platform; if one ever seems to, that is a design
  smell pulling toward coupling.

### C.4 Tenancy, identifiers, backup (summary; detail in D/F)

- **Tenancy:** shared-schema, mandatory non-null `tenant_id` on every tenant-owned
  row; app-layer enforcement now, Postgres **Row-Level Security** as defense-in-depth
  in the hardening phase.
- **Identifiers:** **UUIDv7** internal PKs (time-ordered, index-friendly) +
  human-facing **business keys** unique *per tenant*.
- **Backup:** one logical unit — `pg_dump` of the `platform` database is a complete,
  portable snapshot with no dependency on Beacon's DB. That portability *is* the
  extraction guarantee.

---

## D. Initial Domain Model (first-pass relational foundation)

Conventions for all platform tables: PK `id UUID` (v7); `tenant_id UUID NOT NULL`
FK → `Tenant` (except `Tenant` itself); audit columns `created_at`, `updated_at`,
`created_by` / `updated_by` (a `UUID` referencing `PlatformUser`, same DB);
soft-lifecycle via status/`is_active` + append-only events rather than hard delete.
"Business key" = the human-facing code, **unique per tenant**.

### Tenant  *(core)*
| Field | Notes |
|---|---|
| `id` (PK) | UUIDv7 |
| `tenant_code` (**business key**) | globally unique (e.g. `BEACON`) |
| `name`, `status` | active/suspended |
| audit cols | |

Beacon Innovation LLC is seeded as Tenant #1 via an **idempotent management
command** (not a migration), mirroring `bootstrap_portal`.

### Company  *(people)* — legal entity within a tenant
`id` · `tenant_id` · `company_code` (**bkey**, unique per tenant) · `name` ·
`is_active` · audit. Unique: `(tenant_id, company_code)`.

### Location  *(people)*
`id` · `tenant_id` · `location_code` (**bkey**) · `name` · address fields ·
`is_active`. Unique: `(tenant_id, location_code)`.

### Department  *(people)*
`id` · `tenant_id` · `department_code` (**bkey**) · `name` ·
`parent_department_id` (self-FK, nullable) · `is_active`.
Unique: `(tenant_id, department_code)`.

### Job  *(people)* — job/classification reference
`id` · `tenant_id` · `job_code` (**bkey**) · `title` · `job_family` ·
`exempt_status` · `is_active`. Unique: `(tenant_id, job_code)`.

### Employee  *(people)* — first core business entity
| Field | Notes |
|---|---|
| `id` (PK) | UUIDv7 (never exposed in UI) |
| `tenant_id` | NOT NULL |
| `employee_number` (**bkey**) | unique per tenant (e.g. `EMP000001`) |
| `first_name`, `middle_name`, `last_name`, `preferred_name` | |
| `company_id` → Company | FK (surrogate, not the code) |
| `department_id` → Department | FK |
| `job_id` → Job | FK |
| `location_id` → Location | FK |
| `manager_id` → Employee | self-FK, nullable |
| `employment_status` | active/on-leave/terminated |
| `employee_type` | full-time/part-time/contractor |
| `hire_date`, `original_hire_date`, `termination_date` | |
| audit cols | |

**Deliberately excluded from v1:** SSN and other sensitive PII (no demonstrated
requirement — data minimization). Person/Employment/Identity generalization is
**deferred**; `Employee` stays concrete and understandable.

**Relational discipline (as the owner requires):** `Employee` stores **FKs to the
surrogate keys** of Job/Department/Company/Location — it does **not** duplicate
`JobTitle`/`DepartmentName`. FKs are on internal UUIDs (not on the business code
strings) for integrity and rename-safety; the business code is exposed in the UI.
This is proper enterprise normalization without exploding into micro-tables.

### PlatformUser & the User↔Employee link  *(core)* — see §F
`PlatformUser` is an **application access identity** in the platform DB.
`Employee.user_id` (nullable, `UUID` → `PlatformUser`) links a person to an
account **when** one exists — enforcing "an employee may have no login; a
consultant may have a login but be no employee."

**ER sketch:**
```
Tenant 1──∞ Company, Department, Location, Job, Employee, PlatformUser, Role, ...
Employee ∞──1 Company / Department / Job / Location
Employee 0..1──1 Employee (manager)     Employee 0..1──1 PlatformUser
```

---

## E. Credential Domain Model (future-ready, built incrementally)

Design now, implement in Phases 3–6. All tables are tenant-scoped.

### CredentialType  *(identity)* — reference/config
`id` · `tenant_id` · `type_code` (**bkey**) · `name` · `card_technology`
(vendor-neutral descriptor) · `default_validity_months` · `is_active`.

### Credential  *(identity)* — the issued badge/card (never deleted)
| Field | Notes |
|---|---|
| `id` (PK) · `tenant_id` | |
| `credential_number` (**bkey**) | unique per tenant (e.g. `BCN-000014`) |
| `employee_id` → Employee | |
| `credential_type_id` → CredentialType | |
| `card_serial_number` | physical card serial |
| `status` | requested→enrollment→personalization→printed→activated→active→suspended/revoked/expired/replaced |
| `issue_date`, `activation_date`, `expiration_date`, `revocation_date`, `revocation_reason` | |
| `replaces_id` / `replaced_by_id` → Credential | self-FKs for lifecycle chain |
| audit cols | |

### Certificate  *(identity)* — **metadata only, never private keys**
`id` · `tenant_id` · `credential_id` → Credential · `certificate_type`
(auth/signing/keymgmt) · `piv_slot` (9A/9C/9D) · `serial_number` · `thumbprint` ·
`issuer_dn` · `subject_dn` · `valid_from` · `valid_to` · `revocation_status` ·
`revoked_at`. **No key material.** Private keys are generated **on the card** and
never leave it; CA private keys live offline/HSM (§F, §G).

### BadgeTemplate  *(badging)* — tenant-specific visual layout
`id` · `tenant_id` · `template_code` (**bkey**) · `name` · `layout` (JSON: fields,
front/back, branding, photo box) · `is_active`. **Not** coupled to Beacon branding.

### BadgePrintEvent  *(badging)* — append-only print history
`id` · `tenant_id` · `credential_id` · `badge_template_id` · `printed_by` ·
`printed_at` · `printer_identifier` · `outcome` · `issuance_client_id`.

### CredentialEvent  *(identity)* — append-only lifecycle history
`id` · `tenant_id` · `credential_id` · `event_type` (requested/printed/activated/
suspended/revoked/replaced/…) · `actor` (PlatformUser) · `occurred_at` ·
`reason` · `detail` (JSON). **Immutable** (reuse finance AuditLog immutability).

This satisfies the traceability test: BCN-000014 is never deleted — its certs are
marked revoked, its status becomes `replaced`, `replaced_by` points to BCN-000015,
and every transition is a `CredentialEvent`. The employee record is untouched.

---

## F. Security Architecture

**Authentication (incubation):** the platform defines its own `PlatformUser` and
session; Beacon's `auth.User` is treated as an **external identity provider**
behind an `AuthenticationProvider` seam. On first authenticated arrival, a Beacon
user is mapped/provisioned to a `PlatformUser` via a stable external subject id
(stored as a plain UUID/string — **no cross-DB FK**). This keeps the door open for
the providers the Beacon Platform strategy already names (Entra, Google, Apple,
CAC) without reworking authorization. *Whether to reuse Beacon's session or run a
platform-owned session is a **blocking** decision (§J-B2); the seam makes either
choice reversible.*

**Authorization — real RBAC, tenant-scoped (do not repeat Beacon's
authentication-only gap):**
- `Role`, `Permission`, and `Membership(PlatformUser, Tenant, Role)` in `core`.
- A dedicated **Credential Administrator** role, separate from tenant admin,
  gates issuance/revocation/printing under **least privilege**.
- Enforced via decorators/mixins on every view — never UI-only.

**Tenant isolation (defense in depth):**
1. `tenant_id NOT NULL` on every tenant-owned table.
2. A `TenantScopedManager` whose default queryset filters by the **request-scoped
   tenant** (a `contextvar` set by tenant middleware) — no un-scoped `.objects`
   access to tenant data.
3. All uniqueness scoped `(tenant_id, business_key)`.
4. **Postgres Row-Level Security** policies keyed on a session `SET
   app.current_tenant` — enabled in the hardening phase as the last line of
   defense so an app-layer bug cannot leak across tenants.

Tenant data leakage is treated as a catastrophic defect; isolation is layered, not
single-point.

**Secrets & cryptographic material (hard boundary):** **no** CA private keys, card
management keys, PINs, or platform secrets in application tables. Card keys stay on
the card; CA keys live in an **offline Root / HSM-backed Issuing CA** (§G); app
secrets come from Railway env / a secrets manager. The DB stores only lifecycle
**metadata**.

**Auditability (foundational, and actually wired — unlike finance today):**
- Immutable `AuditEvent` (core) for administrative/security actions +
  domain-specific `CredentialEvent` for the credential lifecycle.
- Written via signals or an explicit service on every create/update/delete/issue/
  print/activate/revoke — closing the "mixin exists but is never called" gap.
- Answers who/what/when/why and the replacement chain by construction.

**Transport/API/session:** HTTPS end-to-end (honor Railway's forwarded proto,
already configured); secure + `HttpOnly` cookies; CSRF on browser forms; the
issuance-client API authenticated by **per-device credentials** (not a shared
static key like `CLAUDE_API_KEY`) with rate limiting on issuance endpoints.

---

## G. Hardware Integration Boundary

**The governing constraint:** the Railway web tier **cannot** access a USB reader,
a PIV card, or an Evolis printer. Hardware operations must run **where the hardware
is** — the MacBook issuance workstation.

**Two-tier model:**

```
 Cloud (Railway)                         Workstation (MacBook)
 ┌──────────────────────────┐   HTTPS    ┌──────────────────────────────┐
 │ Enterprise Platform      │  (per-     │ Local Issuance Client (agent) │
 │  - business domain       │  device    │  - talks to reader/card/printer│
 │  - metadata + lifecycle  │◄─auth API─►│  - CryptoTokenKit / vendor SDK │
 │  - orchestration/state   │            │  - generates keys ON CARD, CSR │
 └──────────────────────────┘            └──────────────────────────────┘
```

- The **platform** owns state, metadata, orchestration, and audit. It never
  speaks a vendor protocol.
- The **local issuance client** performs card personalization, on-card key
  generation, CSR creation, certificate install, and printing, then reports
  metadata back. Private keys never leave the card; the client never uploads keys.

**Provider abstractions (the domain speaks `Credential`, never
`HIDCrescendoC2300`):** define narrow interfaces — `SmartCardReaderProvider`,
`CredentialPersonalizationProvider`, `BadgePrinterProvider`,
`CertificateAuthorityProvider` — with the first concrete adapters being
Identiv/CryptoTokenKit, HID Crescendo Manager/SDK, Evolis, and the lab's Issuing
CA. Swapping vendors = a new adapter, no domain change. **Confirming this
issuance-client model is blocking** (§J-B3): without it, cloud-hosted badging/PIV
is not physically possible.

**PKI shape:** Offline **Root CA** → **Issuing CA** (HSM-backed) → certificate
issuance → on-card personalization → auth/sign/encrypt (PIV 9A/9C/9D). The
platform records issuance/revocation **metadata** and drives the workflow; it is
not itself the CA and holds no CA keys.

---

## H. Future SaaS Extraction

The extraction test — *"move to enterpriseplatform.com tomorrow"* — is satisfied
by construction:

| What extraction needs | Why it's already easy |
|---|---|
| Move the data | The platform is **one Postgres database**; `pg_dump`/restore is complete and self-contained — no records to extract from Beacon's DB. |
| Move the code | Everything lives in the `aegis/` package with its own urls/templates/static; lift the package + its apps into a standalone Django project. |
| Keep the model intact | Multi-tenancy, UUIDs, and the Employee model are built in from day one — no retrofit, no redesign. |
| Untangle identity | There are **no cross-DB FKs to `auth.User`**; swap the `AuthenticationProvider` from "Beacon SSO" to a native/enterprise IdP. |
| Config | Platform config uses its own env prefix (`PLATFORM_DATABASE_URL`, `PLATFORM_*`); nothing reads Beacon's finance/OTA settings. |

**Extraction blockers to actively prevent** (review gates during build): any
`aegis` model importing a Beacon model; any FK to `auth.User`/`ContentType`; any
platform template extending a Beacon base; any Beacon view importing `aegis`; the
platform reusing Beacon business keys/routes. A lightweight import-linting rule
(`aegis.*` may not import `finance/wlj/products/website`) makes this enforceable.

---

## I. Initial Development Phases

| Phase | Focus | Key deliverables |
|---|---|---|
| **0 — Foundation** | Make the boundary real | Managed Postgres + `dj-database-url` + `psycopg`; multi-DB router + per-DB migrations in `Procfile`; base abstractions (UUIDv7 PK, `TenantScopedModel`/manager, immutable `AuditEvent`, RBAC scaffold, `AuthenticationProvider` seam); `/platform/` route + own `base.html`. **No business features.** |
| **1 — Tenant & reference data** | Org backbone | `Tenant`, `Company`, `Department`, `Job`, `Location`; RBAC roles; console shell + nav; seed **Beacon = Tenant #1** (idempotent command). |
| **2 — Employee foundation** | First business entity | `Employee` (+ manager self-FK, org FKs); `PlatformUser` + nullable Employee↔User link; CRUD + audit wired. |
| **3 — Credential inventory** | Own the credential record | `CredentialType`, `Credential`, `CredentialEvent`; status lifecycle + replacement chain; inventory views. |
| **4 — Basic badge printing** | First physical output | `BadgeTemplate`, `BadgePrintEvent`, photo handling; **local issuance client MVP (print path)** + per-device API auth. |
| **5 — PIV / PKI integration** | Smart cards | `Certificate` metadata; `CertificateAuthorityProvider` + card personalization via the client (on-card keygen, CSR, install). **No keys in DB.** |
| **6 — Credential lifecycle** | Full traceability | Revocation/suspension/expiration jobs; end-to-end replace flow; complete audit/history. |
| **7 — SaaS hardening** | Ready to leave home | Postgres RLS on; secrets manager/HSM; rate limiting; external IdP/SSO providers; **extraction rehearsal**; observability/logging. |

Phase 0 is non-negotiable groundwork — it converts every downstream requirement
(tenancy, isolation, extraction, audit) from "remember to do it" into "the
scaffolding won't let you not do it."

---

## J. Risks & Decisions

### BLOCKING (need owner decision before Phase 0)

- **B1 — Introduce managed Postgres + per-DB deploy migrations.** The project has
  no durable DB today. Approve provisioning a **second Railway Postgres** as
  `PLATFORM_DATABASE_URL` and updating the `Procfile` to run
  `migrate --database=platform`. *Recommendation: yes — it is also the project's
  first non-ephemeral datastore.*
- **B2 — Authentication model during incubation.** Reuse Beacon's session (map to
  `PlatformUser`) **or** run a platform-owned login? Both sit behind the
  `AuthenticationProvider` seam. *Recommendation: platform-owned session with a
  Beacon-SSO provider option — cleaner extraction, small extra cost.*
- **B3 — The issuance-client model.** Cloud badging/PIV is impossible without a
  **local agent** on the MacBook. Approve building it (Phase 4+) as in-scope.
  *Recommendation: yes — there is no alternative that keeps the app cloud-hosted.*
- **B4 — Platform owns identity (no cross-DB FK to `auth.User`).** This changes how
  "link employee to user" works (external subject id, not a Django FK). It is the
  linchpin of isolation and extraction and needs explicit sign-off.
  *Recommendation: yes.*

### NON-BLOCKING (recommendations; proceed on defaults unless overridden)

- **Codename / package name** — pick a stable, neutral name (not `platform`, not
  `beacon_*`); `aegis` is a placeholder.
- **UUIDv7 over UUIDv4** — time-ordered PKs for index locality (via Postgres 18
  `uuidv7()` or a small maintained lib); business keys stay separate/per-tenant.
- **RLS timing** — schema is RLS-ready from Phase 0; enable policies in Phase 7.
- **Badge rendering tech** — server-side PDF/SVG composition vs. printer SDK
  templates; decide at Phase 4.
- **Beacon core → Postgres** — *separate initiative,* but flag the **active
  data-loss risk**: Beacon currently runs SQLite on Railway's ephemeral disk;
  finance/portal writes can be lost on redeploy. Worth its own task.
- **Fix latent bugs** — `STATICFILES_STOREAGE` typo (manifest storage inactive);
  reconcile the SQLite-vs-Postgres docs. Small, unrelated to the platform, but
  cheap to clear while touching settings.

### Where this proposal pushes back on the brief (per the "challenge it" rule)

1. **"Separate Postgres from Beacon's Postgres"** — accepted, but the premise is
   off: **Beacon has no Postgres.** The separation is even more worthwhile, and
   cheaper, than assumed.
2. **The separate DB is not free** — it forbids cross-DB FKs and cross-DB
   transactions. That is a *feature* here (it enforces the boundaries you want),
   but it must be a conscious, signed-off constraint (B4), not a surprise.
3. **Hardware in a cloud app** — the brief's PIV/printer direction cannot run on
   Railway. The **local issuance client** is mandatory architecture, surfaced now
   rather than discovered in Phase 5.
4. **Naming** — "Enterprise Platform" collides with the approved "Beacon Platform";
   `platform` collides with the stdlib. Choose a distinct name early.
5. **Scope discipline** — endorse *not* building the Person/Employment/Identity
   generalization, *not* storing SSN, and *not* going microservices. Start with the
   smallest durable foundation; the multi-tenant + UUID + separate-DB + audit
   spine is what must be right on day one, and everything else can be added without
   redesign.

---

## K. Approved Architecture Decisions (2026-08-07)

The owner reviewed §J and the B1–B4 analysis and **approved all four blocking
decisions with the refinements below**, plus a set of standing architectural
decisions. These are now **binding constraints** on Phase 0 and beyond.
Application functionality remains **unauthorized** pending Phase 0 plan approval.

### K.1 Blocking decisions — resolutions

- **B1 — Dedicated PostgreSQL: APPROVED.** The Enterprise Platform gets its **own
  managed PostgreSQL database**, separate from Beacon's, via the proposed Django
  multi-database/router architecture. Hard rules: **no cross-database FKs**;
  platform migrations **explicitly target** the platform DB; **independently
  managed DB credentials**; the platform DB must stay **independently backupable,
  restorable, and portable**; the architecture must support **eventual extraction
  without restructuring the database**. Beacon Innovation LLC = **Tenant #1**. The
  existing Beacon SQLite-on-ephemeral-disk problem is recorded as a **separate
  technical risk** (see [§J non-blocking](#j-risks--decisions)); this project does
  **not** expand into migrating Beacon's own DB unless separately authorized.

- **B2 — Platform-owned identity/auth boundary: APPROVED WITH REFINEMENT.** The
  platform owns `PlatformUser`, tenant `Membership`, authorization, RBAC,
  session/security policy, and access provisioning/revocation. **Authentication
  itself is provider-based** behind the `AuthenticationProvider` seam. Chain:
  `AuthenticationProvider → authenticated external subject → PlatformUser →
  Membership → Roles/Permissions`. A successfully authenticated external user
  **MUST NOT** automatically receive platform access — `PlatformUser` + `Membership`
  must explicitly authorize it. Do **not** casually build another permanent
  username/password system. Future providers: Entra ID/OIDC, Google, enterprise
  OIDC/SAML, CAC/PIV/certificate auth. Any **minimal temporary local auth** for
  dev/bootstrap must be **clearly separated** from the long-term architecture and
  must not require replacing PlatformUser/RBAC/session on extraction.

- **B3 — Local issuance client: APPROVED IN PRINCIPLE.** Recognized now, **not
  built in Phase 0**; implemented when the credential/badging workflow is mature
  enough to consume it. The local client is a **security boundary** with:
  per-device/workstation identity; strong agent↔platform authentication; tenant
  binding; explicit operator authorization; short-lived issuance jobs/tokens;
  replay protection/idempotency; full audit trail. Prohibited: shared static API
  key; uploading private smart-card keys; storing PINs in the SaaS DB; storing CA
  private keys in normal application storage. Vendor-neutral provider interfaces;
  secure update/version strategy eventually. **SaaS orchestrates; the agent
  performs hardware operations** — responsibilities stay separate.

- **B4 — Platform owns its identity: APPROVED.** `PlatformUser` is the
  authoritative application principal. **No cross-database FK to Beacon
  `auth.User`.** No architectural assumption that `User == Employee`: an Employee
  may exist without access; a PlatformUser (consultant, auditor, admin, support)
  may exist without being an Employee. `Employee ↔ PlatformUser` is an **optional**
  application-layer link. Provider mappings use **stable external subject
  identifiers**. Platform identity is **not** coupled to Beacon's `auth.User` schema.

### K.2 Standing architectural decisions (approved)

1. **Modular monolith** — approved; no microservices merely because the end state
   is SaaS; strong domain boundaries that can be extracted later if justified.
2. **Employee first** — keep `Employee` as the initial workforce entity; no
   premature Person/Employment abstraction, but design `Employee` so introducing
   `Person` + `Employment` later is **evolutionary, not destructive**.
3. **Relational reference data** — `Employee` references durable entities (Job,
   Department, Company, Location, Employment Status, Employee Type) by key/FK; do
   not duplicate descriptions onto `Employee`; do not over-normalize trivial data.
4. **Multi-tenancy foundational Day 1** — every tenant-owned row has enforceable
   tenant ownership; app-layer filtering alone is **not** sufficient long-term.
   Defense-in-depth: tenant FKs + tenant-aware managers/services + tenant-aware
   uniqueness + authorization + **PostgreSQL RLS during SaaS hardening**.
5. **Identifiers** — UUID primary keys unless a compelling constraint says
   otherwise; business identifiers stay separate (Employee Number, Credential
   Number, Tenant Code, Job Code, Department Code); internal UUIDs are not exposed
   in the UX unnecessarily.
6. **Sensitive data** — no SSN in v1; collect sensitive data only with a real
   business requirement.
7. **Audit** — created/modified metadata is insufficient for credential/security
   operations; credential lifecycle (issuance, printing, activation, suspension,
   revocation, replacement), certificate lifecycle, and security-sensitive admin
   operations require **durable event/audit history**.
8. **Hardware vendor independence** — HID Crescendo, Identiv, Evolis, macOS are
   *implementations*, not domain concepts. The core understands `Credential`,
   `Reader`, `Printer`, `CertificateAuthority`, `PersonalizationProvider`;
   vendor specifics live behind adapters/providers.

### K.3 Naming (approved)

`aegis` = temporary **internal package name only**, not the product name.
User-facing terminology stays neutral ("Enterprise Platform" / "Identity &
Credential Management"). `/platform/` approved as the incubation route.

---

## Relationship to Other Documentation

Governed by: `BEACON_DOCUMENTATION_STANDARD`, `BEACON_COMPANY_MASTER_STRATEGY`,
`BEACON_PLATFORM_MASTER_STRATEGY`. This is a **Level-4 Architecture** document; it
does not define product strategy (a future Enterprise Platform Master Strategy) or
engineering implementation standards. Grounded in repository discovery on
2026-08-07 (see `docs/ProductStrategyDiscoveryReport.md` for the prior factual map).

## Revision History

| Version | Date | Description |
|---|---|---|
| 0.1 | 2026-08-07 | Initial discovery & architecture proposal for review. No implementation. |
| 1.0 | 2026-08-07 | B1–B4 reviewed and **approved with refinements**; standing decisions and naming recorded in §K. Status → Decisions Approved. Application implementation still not authorized; next gate is the Phase 0 Implementation Plan. |
