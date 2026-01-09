# Beacon Innovations - Claude Code Changelog

This file tracks all changes made by Claude Code during development.

---

## 2026-01-09

### Phase 5: Receipt OCR Processing
- Implemented Tesseract OCR integration for receipt text extraction
- Files created:
  - `finance/ocr.py` - OCR processor with image preprocessing (grayscale, contrast, threshold)
  - `finance/parsers.py` - Receipt parser for vendor, amount, date extraction
  - `finance/tests/test_ocr.py` - 33 tests for OCR functionality
- Files modified:
  - `finance/views.py` - Added OCR processing endpoints
  - `requirements.txt` - Added pytesseract and Pillow dependencies
- API Endpoints:
  - `POST /finance/receipts/<id>/ocr/` - Process OCR on uploaded receipt
  - `POST /finance/receipts/<id>/ocr/rerun/` - Re-run OCR processing
  - `GET /finance/receipts/<id>/ocr/status/` - Get OCR status/results
  - `GET /finance/api/ocr/status/` - Check Tesseract availability
- Features:
  - Image preprocessing: grayscale conversion, contrast enhancement, threshold
  - Amount extraction: Total patterns, dollar signs, USD suffix
  - Date extraction: MM/DD/YYYY, YYYY-MM-DD, month names, abbreviations
  - Vendor extraction: First line fallback, merchant/store labels
  - Confidence scoring: 0.0-1.0 based on Tesseract confidence
- Tests: 33 new tests
- Notes: Phase 5 complete.

### Phase 4: Receipt Upload & Storage
- Implemented receipt upload with file validation and local storage
- Files created:
  - `finance/forms.py` - ReceiptUploadForm with file type/size validation
  - `finance/urls.py` - URL configuration for finance app
  - `finance/tests/test_receipts.py` - 28 tests for receipt functionality
- Files modified:
  - `finance/views.py` - Added upload, view, download, delete endpoints
  - `beaconinnovation/urls.py` - Added finance app URL include
  - `beaconinnovation/settings.py` - Added Cloudinary and finance settings
- API Endpoints:
  - `POST /finance/transactions/<id>/receipts/upload/` - Upload receipt (multipart)
  - `GET /finance/transactions/<id>/receipts/` - List transaction receipts
  - `GET /finance/receipts/<id>/` - Get receipt info
  - `GET /finance/receipts/<id>/view/` - View receipt inline
  - `GET /finance/receipts/<id>/download/` - Download receipt
  - `POST /finance/receipts/<id>/delete/` - Delete receipt
- Features:
  - File type validation (PDF, JPG, PNG)
  - File size validation (10MB max, configurable)
  - Inline viewing and download support
  - Cloudinary configuration ready (env vars)
- Tests: 28 new tests (146 total now passing)
- Notes: Phase 4 complete. Uses local storage; Cloudinary integration requires env vars.

---

## 2026-01-08

### Phase 3: Recurring Transactions & Tax Alerts
- Created management commands for automated financial processing
- Files created:
  - `finance/management/commands/generate_recurring.py` - Generate transactions from recurring templates
  - `finance/management/commands/calculate_tax_alerts.py` - Calculate quarterly tax alerts
  - `finance/tests/test_recurring.py` - 11 tests for recurring generation
  - `finance/tests/test_tax_alerts.py` - 9 tests for tax alert calculation
- Modified: `requirements.txt` (added python-dateutil for date calculations)
- Commands:
  - `python manage.py generate_recurring` - Process due recurring transactions
    - Supports `--dry-run` for preview mode
    - Supports `--date YYYY-MM-DD` for custom processing date
    - Handles monthly, quarterly, and annual frequencies
    - Respects end_date and deactivates expired templates
  - `python manage.py calculate_tax_alerts` - Calculate quarterly net profit
    - Supports `--quarter` and `--year` for specific quarter
    - Supports `--threshold` for custom threshold (default $1000)
    - Supports `--all` to recalculate all quarters with data
    - Shows estimated tax due dates when alert triggered
- Tests: 20 new tests (85 total now passing)
- Notes: Phase 3 complete. Commands can be scheduled via cron for automation.

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
