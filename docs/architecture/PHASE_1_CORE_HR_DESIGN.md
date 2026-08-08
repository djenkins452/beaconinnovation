---
title: Phase 1 — Core HR (Employee Foundation) Design
document_id: ENTERPRISE_PLATFORM_PHASE_1_CORE_HR_DESIGN
version: 0.1
status: Proposed (for review — DO NOT IMPLEMENT until the schema is challenged and approved)
owner: Beacon Innovation, LLC
authoritative: false
classification: Internal
layer: Architecture (Level 4)
audience:
  - Architects
  - Engineers
  - HRIS reviewers
  - AI Assistants
last_updated: 2026-08-08
---

# Phase 1 — Core HR (Employee Foundation) Design

> **Gate:** design only. No migrations, no models, no implementation until this
> schema is challenged and approved. Builds on the approved Phase 0 foundation
> (`aegis` package, dedicated platform PostgreSQL, tenant scoping, `PlatformUser`,
> RBAC, immutable `AuditEvent`). Governed by
> [`ENTERPRISE_PLATFORM_ARCHITECTURE_PROPOSAL`](ENTERPRISE_PLATFORM_ARCHITECTURE_PROPOSAL.md).

## Design creed (the test every entity must pass)
Not "what fields does Workday have?" but **"what is the smallest clean HCM
workforce model that solves our immediate needs while giving future modules
stable entities to attach to?"** An experienced HRIS professional should read the
model and immediately recognize Employee, Job, Department, Company, Location,
Manager, Status, Type — no unnecessary abstraction, no giant JSON employee blob,
no temporal engine, no credential logic leaking into Employee.

---

## 1. Objective & explicit scope

**Objective.** Establish the first real HCM business domain — a clean relational
**Employee + organizational reference-data** foundation that is useful immediately
for basic workforce administration and reporting, and durable enough that future
modules (Identity & Credential, Compensation, Payroll, etc.) attach without a
destructive redesign.

**In scope:** `Company`, `Location`, `Department`, `Job`, `EmploymentStatus`,
`EmployeeType`, `Employee` (with manager self-reference and an optional
`PlatformUser` link); tenant-scoped reference data; audit wiring; a minimal
console UI + REST + CSV import; reportability validation.

**Out of scope (deferred, see §22):** bitemporal/effective-dated history engine,
module registry/entitlement, reporting/KPI engine, custom-field framework,
workflow engine, integrations framework, positions/position-management,
compensation/benefits/payroll/time, the credential domain, department manager,
address framework, and all high-risk PII (SSN/DOB/banking/tax/medical/beneficiary).

**New Django app:** `aegis.core_hr` (registered as a **platform app** so the
router sends it to the platform PostgreSQL database and isolates its migrations).
Its label is added to `PlatformRouter.PLATFORM_APP_LABELS`. *(Naming decision in
§23 — `core_hr` vs `people`.)*

---

## 2. Proposed relational model (overview)

```
Tenant (aegis_core, exists)
  1─* Company            (company_code)
  1─* Location           (location_code)      [+ minimal inline address]
  1─* Department         (department_code)    ── parent_department (self, nullable)
  1─* Job                (job_code)
  1─* EmploymentStatus   (status_code, system_category)   [tenant-configurable ref]
  1─* EmployeeType       (type_code, classification)       [tenant-configurable ref]
  1─* Employee           (employee_number)

Employee ─* → Company            (required)
Employee ─* → Department         (nullable)
Employee ─* → Job                (nullable)
Employee ─* → Location           (nullable)
Employee ─* → EmploymentStatus   (required, default = ACTIVE)
Employee ─* → EmployeeType       (required)
Employee 0..1 → Employee (manager, self, nullable)
Employee 0..1 → PlatformUser (aegis_core, nullable; unique per tenant)
```

All entities inherit the Phase 0 `TenantScopedModel` (UUID PK via `new_uuid()`,
mandatory `tenant` FK, fail-closed `objects` manager, `all_objects` escape hatch,
`created_at/updated_at/created_by/updated_by`). Everything lives in the **platform
database**; every FK here is same-database (no cross-DB FK).

---

## 3–8. Entity-by-entity design (fields, keys, FKs, uniqueness)

Convention: **PK** = internal UUID (never user-facing); **bkey** = human/business
key, unique per tenant; audit columns implied on every table.

### Company *(tenant-owned legal entity)*
| Field | Type | Notes |
|---|---|---|
| `id` PK | UUID | |
| `tenant` FK | → Tenant | NOT NULL |
| `company_code` **bkey** | citext/varchar | unique **(tenant, company_code)** |
| `name` | varchar | legal entity name |
| `is_active` | bool | reference enable/disable |

**Tenant ≠ Company.** A tenant may operate several legal companies (Acme Mfg LLC,
Acme Services LLC…). Company is tenant-owned; do **not** collapse the two because
Beacon starts with one company.

### Location *(tenant-owned)*
`id` · `tenant` · `location_code` **bkey** unique (tenant, code) · `name` ·
`is_active` · **minimal inline address**: `address_line1/2`, `city`,
`region_state`, `postal_code`, `country` (all nullable). Rationale: a location has
exactly one address; a normalized Address entity/global-address framework is
premature (§22). Address fields are plain columns → reportable (headcount by
state/country). Location is an **independent dimension** (not under Company) in
Phase 1.

### Department *(tenant-owned, self-hierarchy)*
`id` · `tenant` · `department_code` **bkey** unique (tenant, code) · `name` ·
`parent_department` FK → Department (self, **nullable**) · `is_active`.
- Hierarchy via `parent_department`; **same-tenant** enforced; **cycle prevention**
  at the validation/service layer.
- **Department Manager: deferred.** `Employee → Department` plus
  `Department → manager Employee` creates a circular dependency and bootstrap/
  import ordering pain for no Phase 1 value — `Employee.manager` already answers
  "who reports to whom." Add `Department.manager` later (org-management phase).
- Department is an **independent dimension** (not nested under Company) in Phase 1;
  an optional `Department.company` FK can be added later without disruption.

### Job *(tenant-owned job classification — NOT an assignment)*
`id` · `tenant` · `job_code` **bkey** unique (tenant, code) · `title` · `is_active`.
Future concepts (job family, level, FLSA/exempt status, salary grade, EEO class)
are **deferred** — Job is designed so they attach later as columns or related
tables. Job describes a classification; who holds it is `Employee.job`.

### EmploymentStatus *(tenant-configurable reference + canonical behavior)*
`id` · `tenant` · `status_code` **bkey** unique (tenant, code) · `label`
(tenant-facing) · `system_category` (**constrained enum**: `ACTIVE | LEAVE |
TERMINATED` [+ room to grow]) · `is_active`.
**Recommendation: tenant-configurable reference entity, not a hard enum.**
Customers use their own codes/labels ("On Leave", "LOA", "Sabbatical"), but the
system keys behavior and reporting off `system_category` (canonical). Seeded with
sensible defaults per tenant. This is the "canonical behavior + tenant labels"
pattern.

### EmployeeType *(tenant-configurable reference + coarse classification)*
`id` · `tenant` · `type_code` **bkey** unique (tenant, code) · `label` ·
`classification` (**constrained enum**: `EMPLOYEE | CONTINGENT` — coarse, for
downstream behavior like future credential/benefit eligibility) · `is_active`.
Tenants define values (Regular Full-Time, Part-Time, PRN, Temporary, Contractor,
Intern…); the coarse `classification` gives the system stable behavior. Seeded
defaults per tenant. *(Schedule FT/PT vs relationship employee/contingent can be
split later if needed; not now.)*

### Employee *(the core workforce record)*
| Field | Type | Req | Notes |
|---|---|---|---|
| `id` PK | UUID | | internal only |
| `tenant` FK | → Tenant | ✔ | |
| `employee_number` **bkey** | varchar | ✔ | unique **(tenant, employee_number)** |
| `first_name` | varchar | ✔ | |
| `middle_name` | varchar | | nullable |
| `last_name` | varchar | ✔ | |
| `preferred_name` | varchar | | nullable |
| `company` FK | → Company | ✔ | PROTECT |
| `department` FK | → Department | | nullable; PROTECT |
| `job` FK | → Job | | nullable; PROTECT |
| `location` FK | → Location | | nullable; PROTECT |
| `manager` FK | → Employee (self) | | nullable; SET_NULL |
| `employment_status` FK | → EmploymentStatus | ✔ | default = the ACTIVE-category status |
| `employee_type` FK | → EmployeeType | ✔ | |
| `hire_date` | date | ✔ | current/most-recent hire |
| `original_hire_date` | date | | nullable (rehires); defaults to hire_date |
| `termination_date` | date | | nullable |
| `email` | email | | nullable; optional unique-per-tenant when present; **business contact only, not the login** |
| `platform_user` FK | → PlatformUser | | nullable; unique **(tenant, platform_user)** (§14) |
| audit cols | | | created/updated at/by |

- **`display_name` is DERIVED, not stored** (property: `preferred_name` or
  `first_name last_name`). Avoids duplicated/stale data; names are on the row so
  reporting/search are unaffected. (Storable later if custom formats are needed.)
- **"Active" is derived** from `employment_status.system_category == ACTIVE` — a
  single source of truth. No separate `Employee.is_active` boolean to drift.
  (`is_active` on *reference* tables is a different thing: enable/disable a code.)
- **Nullability rationale:** `company`, `employment_status`, `employee_type`
  required (an employee always belongs to a legal entity, has a status, and a
  type). `department/job/location/manager` nullable to ease creation/import;
  reporting treats NULL as an explicit **"Unassigned"** bucket (still visible,
  never dark). *(Confirm in §23.)*
- **Explicitly excluded (data minimization):** SSN, DOB, banking, tax elections,
  medical, beneficiary, and — for now — `phone` (no demonstrated Phase 1 need).

---

## 6. Foreign-key relationships (summary)
Employee → Company/Department/Job/Location/EmploymentStatus/EmployeeType (as
above); Employee → Employee (manager); Employee → PlatformUser (optional);
Department → Department (parent). All FKs are on internal UUIDs (rename-safe), not
on business codes. `on_delete`: PROTECT for reference dimensions (you don't delete
a Job that employees hold — you deactivate it), SET_NULL for `manager`. Employees
are never hard-deleted; they are terminated (status) — so referential deletes are
rare by policy.

## 7. Tenant ownership & tenant-consistency rules (defense in depth)
UUID FKs alone do **not** guarantee same-tenant integrity, so we layer it:
1. **Fail-closed scoping (Phase 0):** `objects` only sees the current tenant, so a
   cross-tenant parent can't even be *loaded* to assign in normal flow.
2. **Validation/service layer:** every write validates that all referenced parents
   share the Employee's `tenant`; e.g. **a Tenant A employee assigned a Tenant B
   department fails validation.**
3. **Database composite-FK constraints (belt-and-suspenders):** parents carry a
   `UNIQUE (tenant_id, id)`; children get a **composite FK `(tenant_id, x_id) →
   parent(tenant_id, id)`** added via `RunSQL` in the migration (Django's ORM
   doesn't emit composite FKs natively). The DB then rejects any cross-tenant
   reference outright.
4. **RLS backstop:** tenant-scoped RLS policies (enabled in the Phase 7 hardening,
   schema is ready now).
Manager-specific rules: same-tenant, **no self-management** (`manager != self`),
and **cycle prevention** in the reporting chain (validation).

## 8. Uniqueness constraints (all per-tenant)
`(tenant, company_code)`, `(tenant, location_code)`, `(tenant, department_code)`,
`(tenant, job_code)`, `(tenant, status_code)`, `(tenant, type_code)`,
`(tenant, employee_number)`, `(tenant, platform_user)`; `email` optional partial
unique `(tenant, email) WHERE email IS NOT NULL`.

---

## 8b. Employee-number strategy (deliverable 8)
`employee_number` is a **business identifier**, never the PK. UUID = internal
identity; `employee_number` = human/import/integration identity. Uniqueness is
**per tenant** — two different customers may both have `EMP000001`. Generation:
Phase 1 accepts an externally supplied number (import/manual) and optionally
offers a simple per-tenant sequence helper (e.g., `EMP` + zero-padded counter) as
a convenience; not enforced globally.

## 9. Reference-code strategy (deliverable 9)
All reference entities carry a tenant-scoped business code (`job_code`,
`department_code`, `location_code`, `company_code`, `status_code`, `type_code`)
plus a UUID PK. The DB relates on UUIDs internally; imports/integrations/users
speak the recognizable **codes**. Codes are unique per tenant, human-meaningful,
and stable; renaming a *name/label* never breaks FKs (they're on the UUID).

## 10. Manager relationship design (deliverable 10)
`Employee.manager` self-FK, nullable (top of tree = NULL), `on_delete=SET_NULL`.
Enforced: same-tenant, no self-management, no cycles. **No effective-dated manager
history in Phase 1** — current manager only; the evolution path (§13) adds an
effective-dated assignment/reporting fact later without changing the Employee
identity.

## 11. EmploymentStatus recommendation (deliverable 11)
**Tenant-configurable reference entity with a canonical `system_category` enum.**
Rationale: customers legitimately differ on codes/labels, but the platform needs
canonical behavior ("active vs terminated" reporting, future eligibility rules).
Storing only a hard enum would force every tenant into Beacon's vocabulary; a pure
free-form table would lose canonical behavior. The hybrid gives both. Seed
defaults; allow tenant additions.

## 12. EmployeeType recommendation (deliverable 12)
Same hybrid: **tenant-configurable reference entity + coarse `classification`
enum** (`EMPLOYEE | CONTINGENT`). Tenants define the granular types; the coarse
classification gives stable downstream behavior (e.g., the future Identity &
Credential module may issue different credential types to employees vs
contingents). Don't build finer configuration until a requirement appears.

## 13. Current-state vs future-history strategy (deliverable 13)
**Phase 1 stores current-state relationships directly on Employee** (single-valued
FKs for company/department/job/location/manager/status/type). This is simple,
understandable, and fully reportable.

Facts that **will** need history later: job changes, department transfers, manager
changes, location changes, employment-status changes, company transfers.

**Evolution path (non-destructive):** Employee keeps a **stable UUID identity** —
it becomes the future *anchor*. When history is required, introduce
effective-dated **assignment/reporting fact** tables (the bitemporal pattern from
the proposal §D/§E discussion), then **backfill one "current" fact row per
employee** from today's `Employee.*` FKs, and switch reads to the facts. Because
we (a) never bury multi-valued/temporal data on Employee now, (b) keep single
current FKs, and (c) preserve the stable identity, the migration is **additive**,
not a redesign. *Explicitly not building the bitemporal engine now (§22).*

## 14. PlatformUser ↔ Employee relationship (deliverable 14)
Optional nullable `Employee.platform_user` FK → `PlatformUser` (same platform DB),
with `UNIQUE (tenant, platform_user)` so a given user maps to at most one employee
*within a tenant*. Rules that must hold:
- An Employee may have **no** login (`platform_user = NULL`).
- A `PlatformUser` may exist with **no** Employee (consultant, auditor, admin).
- A `PlatformUser` is **global/cross-tenant**; the link is per-tenant.
- **Employee is never the authentication principal** — auth stays on
  `PlatformUser` via the Phase 0 provider seam. The link is an association only.
*(Alternative: a separate `EmployeeUserLink` mapping entity — recommended only if
we later need link metadata/history; the FK is sufficient for Phase 1.)*

## 15. Audit-event strategy (deliverable 15)
Reuse the Phase 0 immutable `AuditEvent` via the `record_event(...)` service —
**no new workflow engine.** Significant workforce changes are attributable
(actor = current `PlatformUser` from context; tenant preserved). Events wired at
the service layer: `employee.created`, `employee.updated` (changed fields in the
`detail` JSON), `employee.terminated`, `employee.reactivated`,
`employee.job_changed`, `.department_changed`, `.manager_changed`,
`.company_changed`, `.location_changed`, `.status_changed`; reference entities:
`created/updated/deactivated`. Writes that carry audit go through the service, not
raw `.save()`.

## 16. Reportability assessment (deliverable 16)
The model answers the required questions with straightforward relational
queries — **no dark data, no JSON employee blob, every field reachable:**
| Question | How |
|---|---|
| Headcount by department / job / location / company | `GROUP BY` the FK (NULL → "Unassigned") |
| Active vs terminated | `employment_status.system_category` |
| Employees by manager | `GROUP BY manager_id` |
| Hire-date trends | `hire_date` (date column) |
| Employee-type distribution | `GROUP BY employee_type` |
Reference tables carry names/codes → joins are trivial and labels are report-ready.
Derived `display_name` doesn't hurt (names are columns). **Reportability gate:** if
any proposed field can't be reached by a basic relational query, redesign before
implementing. *(No reporting/KPI engine is built now — this is a schema-shape
check only.)*

## 17. Initial UI surfaces required (deliverable 17)
Minimal, all gated by Phase 0 access control + tenant scoping, served from the
`aegis` console (own templates) plus REST:
- Employee **list** (filter by dept/job/location/status/manager/type) + **detail/edit**.
- Reference-data **admin** (CRUD) for Company/Location/Department/Job/
  EmploymentStatus/EmployeeType.
- **"My team"** view (manager → direct reports) and a simple **headcount** panel
  (counts by dimension) — proves reportability end to end.

## 18. Initial import / data-entry considerations (deliverable 18)
- **CSV import** for reference data first, then employees; rows reference **business
  codes**, resolved to UUID FKs on import (never raw UUIDs).
- Validation on import: tenant consistency, code resolution, required fields,
  manager resolution (by employee_number), status/type resolution.
- **Idempotent seed** of default `EmploymentStatus`/`EmployeeType` per tenant
  (mirrors `seed_platform_tenant`), so a new tenant is immediately usable.

## 19. Tests required (deliverable 19)
- **Tenant isolation** for every new entity (A cannot see/query B).
- **Cross-tenant FK rejection**: Tenant A employee + Tenant B department fails at
  validation **and** at the DB composite FK.
- **Uniqueness**: `employee_number` unique per tenant, reusable across tenants;
  each reference code unique per tenant.
- **Manager**: same-tenant, no self-management, cycle rejected.
- **Department**: parent same-tenant, cycle rejected.
- **Status/Type**: canonical `system_category`/`classification` behavior with
  tenant-specific labels.
- **Audit**: correct `AuditEvent` emitted on create/update/terminate/reactivate
  and each relationship change, with actor + tenant attribution.
- **Reportability**: headcount-by-dimension queries return correct results
  (including NULL "Unassigned").
- **PlatformUser↔Employee**: employee without user; user without employee; one
  user ↔ one employee per tenant enforced.
- **Derivation**: `display_name`, derived "active".
- **Fail-closed scoping** still holds for Core HR models (no-tenant-context raises).

## 20. Migration / deployment implications (deliverable 20)
- New app `aegis.core_hr` added to `INSTALLED_APPS` and to
  `PlatformRouter.PLATFORM_APP_LABELS` → migrations target the **platform DB only**;
  Beacon's default DB is untouched.
- Composite-FK same-tenant constraints added via `RunSQL` in the migration.
- Reference-default seeding via an idempotent command, run after
  `migrate --database=platform` in the `Procfile` (alongside `seed_platform_tenant`).
- No change to Beacon behavior; the platform-DB-absent guard still applies
  (`/platform/` fails closed without `PLATFORM_DATABASE_URL`).
- RLS policies for the new tables are drafted now, enabled in Phase 7 hardening.

## 21. Future evolution path (deliverable 21)
- **Identity & Credential (next module):** `Credential` references `Employee`
  (FK, same DB) — **never the reverse**; Employee is fully usable for tenants that
  never license credentials.
- **Compensation / Payroll / Benefits / Time:** attach to Employee (and to the
  future effective-dated assignment facts); comp becomes bitemporal facts later.
- **Positions / Org management:** add `Position` + `Department.manager` +
  effective-dated reporting when needed; Employee anchor unaffected.
- **Recruiting → Onboarding:** candidate → Employee conversion.
- **Reporting / analytics:** governed read model/views over Core HR; KPI layer
  later. The Phase 1 schema is already report-friendly by construction.
- **Person/Employment generalization:** the Employee anchor can split into
  Person + Employment + Assignment later — evolutionary, not destructive.

## 22. Explicitly deferred (deliverable 22)
Bitemporal/effective-dated engine · module registry & entitlement · reporting/KPI
engine · custom-field (flexfield/MDF) framework · workflow/business-process engine
· integrations framework · positions/position-management · department manager ·
address framework (beyond minimal inline Location address) · phone/contact-info
model · job family/level/FLSA/salary-grade/EEO · compensation/benefits/payroll/time
· the credential domain · SSN/DOB/banking/tax/medical/beneficiary PII.

## 23. Risks / open decisions requiring owner approval

**Non-blocking (recommendation given; will proceed on these unless overridden):**
1. **App name:** `aegis.core_hr` (recommended, matches "Core HR" terminology) vs
   `aegis.people`.
2. **Nullability:** `company/employment_status/employee_type` required;
   `department/job/location/manager` nullable (recommended).
3. **`display_name` derived** (recommended) vs stored.
4. **`EmploymentStatus` / `EmployeeType` as tenant-configurable reference + canonical
   enum** (recommended) vs hard enums.
5. **Department independent of Company** in Phase 1 (recommended) vs nested under
   Company.
6. **Location address:** minimal inline fields (recommended) vs deferred entirely.
7. **`email`:** optional, partial-unique per tenant when present (recommended).
8. **Department manager deferred** (recommended).

**Worth an explicit decision (small added complexity):**
9. **Composite-FK same-tenant enforcement via `RunSQL`** (recommended, strongest
   guarantee) vs validation-layer + RLS only. Adds a little migration hand-SQL.

**Blocking (need a yes before the first migration):**
- **B1 — Approve the Employee schema itself** (fields, keys, relationships,
  nullability, exclusions) as the durable foundation.
- **B2 — Confirm current-state-now / effective-dated-later strategy (§13)** as the
  history approach, accepting that the first temporal fact table is a future phase.

---

## Revision History
| Version | Date | Description |
|---|---|---|
| 0.1 | 2026-08-08 | Initial Phase 1 Core HR design for review. No implementation. |
