# Beacon Innovations - Claude Code Changelog

This file tracks all changes made by Claude Code during development.

---

## 2026-01-08

### Phase 2: Core Finance Models
- Created: `finance/` app with all financial tracking models
- Files created:
  - `finance/models.py` - 8 models: Account, Category, Transaction, Receipt, RecurringTransaction, TaxAlert, AuditLog, CSVImport
  - `finance/mixins.py` - AuditLogMixin for automatic audit logging
  - `finance/admin.py` - Django admin registration for all models
  - `finance/tests/test_models.py` - 29 model tests
- Migrations:
  - `finance/migrations/0001_initial.py` - Create all models
  - `finance/migrations/0002_seed_default_categories.py` - Seed 15 default categories
- Modified: `beaconinnovation/settings.py` (added finance app)
- Models:
  - **Account**: Bank/credit card accounts with balance calculation
  - **Category**: Expense/income categories (10 expense, 5 income seeded)
  - **Transaction**: Income, expense, transfer, owner's draw with validation
  - **Receipt**: File attachments with OCR fields
  - **RecurringTransaction**: Templates for auto-generated transactions
  - **TaxAlert**: Quarterly tax payment alerts
  - **AuditLog**: Immutable audit trail (cannot modify/delete)
  - **CSVImport**: Track CSV import history
- Tests: 29 tests passing
- Notes: Phase 2 complete. Models visible in Django admin.

### Phase 1: Admin Console & Task API
- Created: `admin_console/` app with full task management functionality
- Files created:
  - `admin_console/models.py` - AdminTask model with JSON description validation
  - `admin_console/api_views.py` - API endpoints for Claude Code integration
  - `admin_console/views.py` - Admin UI views (dashboard, CRUD, import)
  - `admin_console/forms.py` - Task forms with JSON validation
  - `admin_console/admin.py` - Django admin registration
  - `admin_console/urls.py` - URL routing for UI and API
  - `admin_console/templates/admin_console/*.html` - 6 templates (base, dashboard, list, detail, form, import, delete)
  - `admin_console/tests/test_models.py` - 15 model tests
  - `admin_console/tests/test_api.py` - 21 API tests
- Migrations: `admin_console/migrations/0001_initial.py`
- Modified: `beaconinnovation/settings.py` (added app, CLAUDE_API_KEY)
- Modified: `beaconinnovation/urls.py` (added admin-console routes)
- API Endpoints:
  - `GET /admin-console/api/claude/ready-tasks/` - Fetch ready tasks with auto_start
  - `POST /admin-console/api/claude/tasks/<id>/status/` - Update task status
  - `GET /admin-console/api/claude/tasks/<id>/` - Get task details
  - `POST /admin-console/api/claude/tasks/import/` - Bulk import tasks
- Tests: 36 tests passing
- Notes: Phase 1 complete. Admin console accessible at `/admin-console/`

### Initial Setup
- Created: `CLAUDE.md` (project context file)
- Created: `docs/BeaconInnovationFinance.md` (financial tracker design spec)
- Created: `docs/.claude/commands/README.md` (slash commands documentation)
- Created: `docs/beacon_claude_changelog.md` (this file)
- Created: `docs/beacon_claude_troubleshoot.md` (troubleshooting guide)
- Created: `docs/beacon_claude_deploy.md` (deployment guide)
- Notes: Initial documentation setup, ready for Phase 1 development

---

<!-- 
TEMPLATE FOR NEW ENTRIES:

## YYYY-MM-DD

### [Brief Description]
- Files: [list of files created/modified]
- Migrations: [migration names if any]
- Tests: [test files added/modified]
- Notes: [additional context]

-->
