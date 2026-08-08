---
title: Phase 1 — Core HR (Employee Foundation) Design — FINAL
document_id: ENTERPRISE_PLATFORM_PHASE_1_CORE_HR_DESIGN
version: 1.0
status: Approved with refinements (2026-08-08) — final design; implementation plan pending approval; DO NOT IMPLEMENT
owner: Beacon Innovation, LLC
authoritative: true
classification: Internal
layer: Architecture (Level 4)
audience:
  - Architects
  - Engineers
  - HRIS reviewers
  - AI Assistants
last_updated: 2026-08-08
---

# Phase 1 — Core HR (Employee Foundation) Design — FINAL

> **Gate:** design is approved with refinements. No models/migrations/code until
> the accompanying **Phase 1 Implementation Plan**
> (`docs/architecture/PHASE_1_IMPLEMENTATION_PLAN.md`) is approved. Builds on
> Phase 0 (`aegis` package, dedicated platform PostgreSQL, tenant scoping,
> `PlatformUser`, RBAC, immutable `AuditEvent`).

## Design creed
The smallest clean HCM workforce model that solves today's needs while giving
future modules stable entities to attach to. An HRIS professional should read it
and immediately recognize Employee, Job, Department, Company, Location, Manager,
Status, Type — no unnecessary abstraction, no JSON employee blob, no temporal
engine, no credential logic on Employee.

**Approved scope (B1):** Company, Department, Job, Location, Employment Status,
Employee Type, Employee — all tenant-aware. **Approved history strategy (B2):**
current-state now; effective-dated history added later, additively, without
replacing Employee.

---

## 1. Objective & scope
Establish a clean relational **Employee + organizational reference-data**
foundation, immediately useful for basic workforce administration and relational
reporting, durable enough for future modules to attach without redesign.

**New Django app:** `aegis.core_hr` — a **platform app** (router sends it to the
platform PostgreSQL DB and isolates its migrations; its label joins
`PlatformRouter.PLATFORM_APP_LABELS`). All models inherit the Phase 0
`TenantScopedModel` (UUID PK via `new_uuid()`, mandatory `tenant`, fail-closed
`objects`, `all_objects` escape hatch, `created_at/updated_at/created_by/updated_by`).
Every FK is same-database (no cross-DB FK).

---

## 2. Final relational model

```
Tenant (aegis_core)
  1─* Company          (company_code)                     is_active
  1─* Location         (location_code) + minimal address  is_active
  1─* Department       (department_code) ── parent (self, nullable)  is_active
  1─* Job              (job_code, title)                   is_active
  1─* EmploymentStatus (status_code, label, system_category ∈ {ACTIVE,LEAVE,TERMINATED})  is_active
  1─* EmployeeType     (type_code, label, classification ∈ {EMPLOYEE,CONTINGENT})         is_active
  1─* Employee         (employee_number)

Employee → Company            (required, PROTECT)
Employee → Department         (nullable, PROTECT)
Employee → Job                (nullable, PROTECT)
Employee → Location           (nullable, PROTECT)
Employee → EmploymentStatus   (required, PROTECT, default = ACTIVE-category)
Employee → EmployeeType        (required, PROTECT)
Employee → Employee (manager, self, nullable, SET_NULL)
```

**No `Employee.platform_user` FK** (see §4) and **no `Employee.is_active`** (see
§ Active employee). "Active" is derived from `employment_status.system_category`.

---

## 3. Entity fields (final)

### Company *(tenant-owned legal entity)*
`id` UUID PK · `tenant` (req) · `company_code` **bkey**, unique (tenant, code) ·
`name` · `is_active`. **Tenant ≠ Company** (a tenant may hold several legal
entities). Not collapsed into Tenant.

### Location *(tenant-owned, independent dimension)*
`id` · `tenant` · `location_code` **bkey**, unique (tenant, code) · `name` ·
`is_active` · minimal inline address (`address_line1/2`, `city`, `region_state`,
`postal_code`, `country`, all nullable). No generalized Address framework.

### Department *(tenant-owned, self-hierarchy)*
`id` · `tenant` · `department_code` **bkey**, unique (tenant, code) · `name` ·
`parent_department` FK → self (nullable, PROTECT) · `is_active`. **No Department
manager** in Phase 1 (avoids Employee↔Department circularity; `Employee.manager`
suffices). **Not** required to belong to a Company; tenant-wide. Parent must be
same-tenant; cycles rejected (validation).

### Job *(tenant-owned classification — deliberately small)*
`id` · `tenant` · `job_code` **bkey**, unique (tenant, code) · `title` ·
`is_active`. No salary grade / pay structure / job family / FLSA / EEO / ranges /
market data — those attach later without redesigning Job.

### EmploymentStatus *(tenant-configurable reference + canonical category)*
`id` · `tenant` · `status_code` **bkey**, unique (tenant, code) · `label`
(tenant-facing) · `system_category` (**small canonical enum: `ACTIVE`, `LEAVE`,
`TERMINATED`**) · `is_active`. Tenants own codes/labels ("A/Active",
"LOA/Leave of Absence", "TERM/Terminated"); the platform keys behavior/reporting
off `system_category`. No workflow engine around status.

### EmployeeType *(tenant-configurable reference + minimal classification)*
`id` · `tenant` · `type_code` **bkey**, unique (tenant, code) · `label` ·
`classification` (**minimal canonical enum: `EMPLOYEE`, `CONTINGENT`**) ·
`is_active`. Tenants define granular values (Regular Full-Time, PRN, Contractor…);
the coarse classification gives stable downstream behavior. No large system-owned
enumeration forced on customers.

### Employee *(core workforce record)*
| Field | Type | Req | Notes |
|---|---|---|---|
| `id` PK | UUID | | internal only |
| `tenant` | FK Tenant | ✔ | |
| `employee_number` **bkey** | varchar | ✔ | **unique (tenant, employee_number)** — the authoritative business id |
| `first_name` | varchar | ✔ | |
| `middle_name` | varchar | | nullable; **full middle name** (not restricted to an initial) |
| `last_name` | varchar | ✔ | |
| `preferred_name` | varchar | | nullable |
| `company` | FK Company | ✔ | PROTECT |
| `department` | FK Department | | nullable, PROTECT |
| `job` | FK Job | | nullable, PROTECT |
| `location` | FK Location | | nullable, PROTECT |
| `manager` | FK Employee (self) | | nullable, SET_NULL |
| `employment_status` | FK EmploymentStatus | ✔ | default = ACTIVE-category, PROTECT |
| `employee_type` | FK EmployeeType | ✔ | PROTECT |
| `hire_date` | date | ✔ | current/most-recent hire |
| `original_hire_date` | date | | nullable (rehires); defaults to hire_date |
| `termination_date` | date | | nullable (see § Termination) |
| `email` | email/varchar | | nullable; **NOT unique**; business contact only, not the login |
| audit cols | | | created/updated at/by |

- **`display_name` derived**, never stored (`preferred_name` else
  `first_name last_name`); UI derives the middle initial when it wants one.
- **Names:** full `middle_name` preserved if supplied.
- **`email` is a plain optional attribute — no uniqueness** (legacy/imported data,
  contractors, shared addresses, rehires, no-email workers, future personal/work
  split). A formal work-contact/identity model may come later.
- **Excluded (data minimization):** SSN, DOB, banking, tax, medical, beneficiary,
  and `phone` (no Phase 1 need).

---

## Active employee (single source of truth)
**No independent `Employee.is_active`.** Workforce-active is derived from
`employment_status.system_category` (`ACTIVE` vs `LEAVE`/`TERMINATED`), avoiding
the `status=TERMINATED, is_active=TRUE` ambiguity. Provide a queryset helper
(`.active()`) and a model property. (Reference entities keep their own `is_active`
for enable/disable of a *code* — a distinct concept. If a record-level
admin enable/disable is ever needed for an Employee, it will be a separate,
clearly-named field — not employment status. None is added now.)

## Termination date (canonical-driven validation)
`termination_date` nullable. Not every non-active status implies termination
(`LEAVE` ≠ `TERMINATED`). Validation driven by canonical category: if
`employment_status.system_category == TERMINATED`, require `termination_date`
(and `termination_date >= hire_date`); otherwise it may be null. No workflow.

## Reference-data lifecycle (deactivate, never orphan employees)
Company/Location/Department/Job/EmploymentStatus/EmployeeType are **deactivated**
(`is_active=False`), not physically deleted, once referenced. `on_delete=PROTECT`
on every Employee→reference FK guarantees **removing a Job/Department can never
cascade-delete Employees**. Deactivating a code keeps existing references valid
while preventing new assignments (enforced by scoping active choices in pickers).

---

## 4. PlatformUser ↔ Employee mapping (final recommendation)
**Hard rule preserved: `PlatformUser` ≠ `Employee`.** `PlatformUser` is a global
principal scoped to tenants via `Membership`; an Employee belongs to exactly one
tenant.

**Evaluation.** A direct nullable `Employee.platform_user` FK conflates the
workforce record with identity and structurally permits the ambiguity you flagged
(a Tenant-A employee linked to a user authorized only for Tenant B). The clean
model is a **tenant-scoped mapping entity** whose own `tenant` makes the scope
explicit and which validates *"the PlatformUser has an active `Membership` in this
tenant."*

**Final recommendation:** adopt the mapping-entity *design* now, but **defer
building it** — Phase 1 has no consumer (no employee login, self-service, or
credentials). This keeps Phase 1 to the approved 7 entities and avoids
consumerless code, while settling the architecture so it isn't re-litigated:

```
EmployeeIdentityLink  (aegis.core_hr, tenant-scoped)   — DEFERRED, design-settled
  id · tenant · employee FK (unique per tenant) · platform_user FK (unique per tenant)
  is_active · linked_at · linked_by · audit
  RULE: platform_user MUST have an active Membership in `tenant`.
```
Built in the first phase that needs it (self-service or the Identity & Credential
module). Employee never becomes the auth principal. *(Alternative if you want the
link available in Phase 1: build this minimal entity now — decision D-1 in §14b.)*

---

## 5. Tenant-consistency enforcement (final engineering judgment)

**Invariant:** a Tenant-A Employee must never reference a Tenant-B Company,
Department, Job, Location, Employee Type, Employment Status, or Manager.

**Composite `(tenant_id, id)` FK — evaluated and NOT recommended for Phase 1.**
Django 5.1's ORM does not model multi-column FKs. Implementing them means keeping
the normal single-column FK *and* adding a parallel composite FK via hand-written
`RunSQL` for every tenant-scoped relationship (8+ now, growing each phase), with
matching reverse SQL, all invisible to `makemigrations`. That is a durable
maintenance burden and exactly the "constraints Django doesn't understand, so
developers break them by accident" trap. Rejected on maintainability grounds.

**Recommended enforcement stack (maintainable, Django-native, layered):**
1. **Tenant-scoped fail-closed managers (Phase 0):** `objects` returns only the
   current tenant, so in normal ORM flow a cross-tenant parent **cannot even be
   loaded** to assign. This is the strongest *practical* prevention.
2. **Reusable domain validation** — a small `TenantConsistencyMixin.clean()` that
   asserts every FK's `.tenant_id == self.tenant_id` (one place, applied
   uniformly; called by the service layer and `full_clean`).
3. **Form/serializer validation** — choice querysets scoped to the tenant (pickers
   only offer same-tenant, active options).
4. **Service layer** — all writes go through services that set/verify tenant.
5. **Clean DB `CheckConstraint`s Django *does* understand** — `manager_id != id`
   (no self-management); `termination_date >= hire_date` when both set. (These are
   single-table checks, fully ORM-managed — unlike composite FKs.)
6. **Strong cross-tenant negative tests** — prove A cannot reference B by any
   path, **including raw `*_id` injection and `all_objects`**. This is the real
   safety net.
7. **PostgreSQL RLS later (Phase 7 hardening)** — one uniform policy per table
   (maintainable, generated), the DB-level defense-in-depth. If a DB-level
   guarantee is wanted sooner, RLS — not composite FKs — is the clean path.

Manager rules: same-tenant, no self-management (CHECK), no cycles (validation —
basic reasonable detection, not a graph engine). Department parent: same-tenant,
no cycles.

---

## 6. Constraints & indexes
- **Uniqueness (all per-tenant):** `(tenant, company_code)`, `(tenant, location_code)`,
  `(tenant, department_code)`, `(tenant, job_code)`, `(tenant, status_code)`,
  `(tenant, type_code)`, `(tenant, employee_number)`. **No email uniqueness.**
- **CheckConstraints:** `manager_id <> id`; `termination_date >= hire_date` (when
  both present).
- **Indexes:** FK columns (Django indexes FKs by default) cover headcount-by-X
  reporting; add `(tenant, hire_date)` and `(tenant, termination_date)` for
  date-range reporting; `employee_number` is unique-indexed. No JSON columns.

---

## 7. Audit strategy
Reuse Phase 0 immutable `AuditEvent` via `record_event(...)` (no workflow engine).
Service-layer events, attributed to the acting `PlatformUser` + tenant:
`employee.created`, `.updated` (changed fields in `detail`), `.status_changed`,
`.terminated`, `.reactivated`, `.job_changed`, `.department_changed`,
`.company_changed`, `.location_changed`, `.manager_changed`, `.type_changed`;
reference entities: `created/updated/deactivated`. **AuditEvent = who changed
what/when (action history); the relational tables = current state; future
effective-dated tables = business-effective history — three distinct concerns.**

## 8. Seed / bootstrap strategy
Idempotent, **tenant-parameterized**, no Beacon assumptions baked into the schema:
- `seed_core_hr_defaults <tenant>` — generic default `EmploymentStatus`
  (A/Active→ACTIVE, LOA/Leave→LEAVE, TERM/Terminated→TERMINATED) and
  `EmployeeType` (a small sensible default set) for any tenant.
- Beacon Tenant #1's own `Company` and any Beacon-specific reference values are
  created via the seed *with Beacon parameters* (or the console) — **Beacon is the
  first tenant, not the schema definition.**

## 9. UI scope (small)
Server-rendered `aegis` console, gated by Phase 0 access control + tenant scoping:
- **Employee:** list, search/filter (dept/job/location/status/type/manager), view,
  add, edit.
- **Reference entities** (Company/Location/Department/Job/EmploymentStatus/
  EmployeeType): list, add, edit, activate/deactivate.
- **Not built:** dashboards, KPI/reporting designer, org visualization, self-service,
  workflow, badging/credential UI.

## 10. Tests
Tenant isolation (every entity); **cross-tenant reference rejection incl. raw
`*_id` injection**; `employee_number` unique per-tenant & reusable across tenants;
reference-code uniqueness; manager (same-tenant, no self, cycle rejected);
department parent (same-tenant, cycle rejected); status/type canonical behavior
with tenant labels; termination-date validation by canonical category;
reference-deactivation does **not** delete Employees; audit events emitted with
attribution; reportability queries (headcount by dept/job/company/location, type &
status distribution, by-manager, hire/termination-date) correct incl. NULL
"Unassigned"; derived `display_name` and derived "active"; fail-closed scoping
holds for Core HR.

## 11–12. Migration & deployment
- Add `aegis.core_hr` to `INSTALLED_APPS` and `PLATFORM_APP_LABELS`; migrations
  target the **platform DB only**; Beacon's default DB untouched.
- Constraints via ORM (`UniqueConstraint`, `CheckConstraint`) — **no hand-SQL
  composite FKs.**
- `Procfile`: run `seed_core_hr_defaults` after `migrate --database=platform`
  (alongside `seed_platform_tenant`), guarded by `PLATFORM_DATABASE_URL`.
- Platform-DB-absent guard still applies (`/platform/` fails closed; Beacon fine).
- RLS policies drafted, enabled in Phase 7.

## 13. Explicitly deferred
`EmployeeIdentityLink` (design-settled, built when a consumer exists) · Credential/
Certificate/PIV/PKI/HID/Identiv/Evolis/issuance-agent · module registry &
entitlement · Position · Assignment · bitemporal/effective-dated engine ·
Compensation/Payroll/Benefits/Time · Recruiting/Performance · reporting & KPI
engines · workflow engine · custom-field framework · integrations framework ·
generalized Address model · Department manager · phone/contact model ·
job family/level/FLSA/EEO/salary-grade · SSN/DOB/banking/tax/medical/beneficiary.

## 14. Remaining decisions
**Blocking (need a yes before the implementation plan is executed):**
- **B1 — Approve this final Employee + reference schema** (fields, keys, FKs,
  nullability, constraints).
- **B2 — Approve the tenant-consistency stack** in §5 (app-layer + checks + tests
  now; RLS later; **no composite FKs**).

**Decision D-1 (PlatformUser↔Employee):** confirm **defer** `EmployeeIdentityLink`
(recommended) vs build the minimal mapping entity now.

**Non-blocking (proceeding on these unless overridden):** app name `aegis.core_hr`;
nullability (company/status/type required; dept/job/location/manager nullable);
derived display_name; tenant-configurable status/type with canonical enums;
Department independent of Company; minimal inline Location address; email optional
& non-unique.

## Revision History
| Version | Date | Description |
|---|---|---|
| 0.1 | 2026-08-08 | Initial Core HR design for review. |
| 1.0 | 2026-08-08 | Approved with refinements: email non-unique; full middle name; no Employee.is_active (derive from status); canonical-driven termination validation; reference deactivate-not-delete; **composite FKs rejected** for maintainability (app-layer + checks + tests now, RLS later); **PlatformUser↔Employee via deferred mapping entity** (not a direct FK). Final design. |
