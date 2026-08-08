---
title: Phase 1 — Core HR Implementation Plan
document_id: ENTERPRISE_PLATFORM_PHASE_1_IMPLEMENTATION_PLAN
version: 0.1
status: Proposed (for review — DO NOT IMPLEMENT until approved)
owner: Beacon Innovation, LLC
authoritative: false
classification: Internal
layer: Architecture (Level 4)
audience:
  - Architects
  - Engineers
  - AI Assistants
last_updated: 2026-08-08
---

# Phase 1 — Core HR Implementation Plan

> **Gate:** plan for review. No code until approved. Implements the finalized
> [`PHASE_1_CORE_HR_DESIGN`](PHASE_1_CORE_HR_DESIGN.md) v1.0 on top of Phase 0.
> Scope is the Employee foundation only; everything in that design's §13 stays
> deferred.

## Objective
Deliver the Core HR Employee + organizational reference-data foundation as a new
platform app `aegis.core_hr`: 7 tenant-scoped entities, service-layer writes with
audit, tenant-consistency enforcement (app-layer + checks + tests; **no composite
FKs**), a small console UI, seed defaults, and a full test suite — all in the
platform PostgreSQL database, Beacon untouched.

---

## 1. MUST BUILD  vs  DEFERRED (Phase 1)

| Item | Disposition |
|---|---|
| `aegis.core_hr` app + router registration | **MUST BUILD** |
| Models: Company, Location, Department, Job, EmploymentStatus, EmployeeType, Employee | **MUST BUILD** |
| Canonical enums: `system_category` (ACTIVE/LEAVE/TERMINATED), `classification` (EMPLOYEE/CONTINGENT) | **MUST BUILD** |
| `TenantConsistencyMixin` + manager/parent/termination validation | **MUST BUILD** |
| Service layer (create/update/terminate/reactivate/change-*) with `AuditEvent` wiring | **MUST BUILD** |
| Per-tenant unique constraints + CheckConstraints + reporting indexes | **MUST BUILD** |
| Idempotent `seed_core_hr_defaults <tenant>` (generic statuses/types) | **MUST BUILD** |
| Console UI: Employee (list/search/view/add/edit); reference CRUD + activate/deactivate | **MUST BUILD** |
| Test suite (§ Tests) | **MUST BUILD** |
| Procfile seed step + docs | **MUST BUILD** |
| `EmployeeIdentityLink` (PlatformUser↔Employee) | **DEFERRED — design-settled (§D-1)** |
| Composite `(tenant_id,id)` FKs | **REJECTED — app-layer + RLS-later instead** |
| REST API | **THIN/OPTIONAL — read endpoints only if cheap; else Phase 1.1** |
| RLS policies | **DRAFTED now, ENABLED Phase 7** |
| Everything in design §13 (credentials, positions, comp, bitemporal, module registry, dashboards/KPI, workflow, custom fields, integrations, address model, dept manager, phone) | **DEFERRED** |

---

## 2. Files to CREATE
```
aegis/core_hr/
  __init__.py
  apps.py                      # CoreHrConfig, label='aegis_core_hr'
  models.py                    # 7 entities (TenantScopedModel) + enums + constraints
  validators.py                # TenantConsistencyMixin, manager/parent/termination rules, cycle check
  services.py                  # EmployeeService + reference services; writes + record_event()
  querysets.py                 # e.g. EmployeeQuerySet.active() (derived from status category)
  seed.py                      # default status/type definitions (generic, no Beacon assumptions)
  forms.py                     # tenant-scoped choice querysets; add/edit forms
  views.py                     # console list/search/view/add/edit + reference CRUD (gated)
  urls.py                      # under the platform namespace
  templates/aegis/core_hr/     # list/detail/form templates (extend aegis/base.html)
  management/commands/seed_core_hr_defaults.py
  migrations/0001_initial.py   # (generated at implementation time)
  tests/
    __init__.py
    test_tenant_isolation.py
    test_cross_tenant_refs.py  # incl. raw *_id injection + all_objects attempts
    test_employee.py           # fields, employee_number uniqueness, derived name/active
    test_manager.py            # same-tenant, no self, cycle
    test_department.py         # parent same-tenant, cycle, deactivate-not-delete
    test_reference_data.py     # code uniqueness, status/type canonical behavior, deactivation
    test_termination.py        # canonical-driven validation
    test_audit.py              # events + attribution
    test_reportability.py      # headcount-by-X, distributions, by-manager, date analysis
```

## 3. Files to MODIFY
- `beaconinnovation/settings.py` — add `'aegis.core_hr'` to `INSTALLED_APPS`.
- `aegis/core/routers.py` — add `'aegis_core_hr'` to `PLATFORM_APP_LABELS`.
- `aegis/urls.py` — include `aegis.core_hr.urls` (nav entries for the new console).
- `Procfile` — add `seed_core_hr_defaults` after `migrate --database=platform`
  (guarded by `PLATFORM_DATABASE_URL`).
- Docs: changelog; deploy guide (seed step); mark this plan implemented on completion.

## 4. Model & constraint notes
- All 7 inherit `TenantScopedModel`; reference entities add `is_active`; Employee
  omits `is_active` (derived). `on_delete=PROTECT` on all Employee→reference FKs;
  `SET_NULL` on `manager`; `parent_department` self-FK `PROTECT`.
- Enums via `TextChoices`. Defaults: Employee.`employment_status` resolves to the
  tenant's ACTIVE-category status at creation (service layer, not a DB default).
- Constraints: per-tenant `UniqueConstraint`s (design §6); `CheckConstraint`
  `manager_id <> id`; `CheckConstraint` `termination_date >= hire_date` (both set).
- Indexes: FK columns (auto), `(tenant, hire_date)`, `(tenant, termination_date)`.

## 5. Tenant-consistency implementation (no composite FKs)
1. `TenantConsistencyMixin.clean()` — iterate FK fields; assert each referenced
   object's `tenant_id == self.tenant_id`; raise `ValidationError` otherwise.
2. Services call `full_clean()` before save; forms/serializers scope choice
   querysets to `current_tenant` and `is_active=True`.
3. Fail-closed managers (Phase 0) already prevent loading cross-tenant parents.
4. Negative tests assert rejection even when bypassing via raw `*_id` or
   `all_objects`.
5. RLS policies authored in a migration but left disabled until Phase 7.

## 6. Audit wiring
Every service mutation calls `aegis.core.audit.record_event(...)` with the acting
`PlatformUser` (from context), tenant, action code, and changed-field `detail`.
No `.save()` on Employee outside the service for auditable operations.

## 7. Seed / bootstrap
`seed_core_hr_defaults <tenant-code>` (idempotent): default `EmploymentStatus`
(A→ACTIVE, LOA→LEAVE, TERM→TERMINATED) and a small default `EmployeeType` set for
the given tenant. Beacon's `Company` + any Beacon-specific values created by
running the seed/console **with Beacon parameters** — not embedded in migrations.

## 8. UI
Console pages under `/platform/…` (own `aegis` templates, Phase 0 access-gated):
Employee list/search/view/add/edit; reference-entity list/add/edit/activate-
deactivate. Choice fields show only same-tenant active options. No dashboards/KPI/
self-service/workflow.

## 9. Testing strategy
Run `python manage.py test aegis.core_hr` against **PostgreSQL** (declare
`databases = {'default','platform'}`). Cover every item in design §10. Cross-tenant
negative tests are mandatory and must include raw-id and `all_objects` bypass
attempts. Also re-run `aegis.core` (Phase 0) and Beacon suites to confirm no
regressions.

## 10. Deployment implications
- Provision remains the same single platform Postgres (Phase 0). No new infra.
- `Procfile` gains one guarded seed step. Migrations apply to platform DB only.
- Beacon default DB and behavior unchanged; `/platform/` still fails closed when
  `PLATFORM_DATABASE_URL` is absent.

## 11. Rollback strategy
Additive and isolated: revert the branch (removes the app from `INSTALLED_APPS`,
the router label, urls, Procfile step). The `aegis_core_hr` tables live only in the
platform DB and can be dropped independently; Beacon and Phase 0 are unaffected.
No destructive default-DB migrations.

## 12. Implementation sequence (when approved)
1. App scaffold + router label + settings/urls wiring (no models) → migrate no-op.
2. Reference models (Company/Location/Department/Job/EmploymentStatus/EmployeeType)
   + constraints + migration + `seed_core_hr_defaults` + tests.
3. `TenantConsistencyMixin` + validators + negative tests.
4. Employee model + service layer + audit wiring + migration + tests.
5. Console UI (reference CRUD, then Employee CRUD/search).
6. Reportability tests + full suite green on Postgres; Phase 0 + Beacon regression.
7. Procfile/docs/changelog; open PR.

## 13. Blocking decisions before execution
- **B1** — approve the final schema (design §14 B1).
- **B2** — approve the tenant-consistency stack (design §5 / §14 B2).
- **D-1** — confirm deferring `EmployeeIdentityLink` (recommended) vs build now.

## Revision History
| Version | Date | Description |
|---|---|---|
| 0.1 | 2026-08-08 | Initial Phase 1 Core HR implementation plan for review. No implementation. |
