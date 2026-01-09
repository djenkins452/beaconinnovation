# Beacon Innovations - Claude Code Changelog

This file tracks all changes made by Claude Code during development.

---

## 2026-01-09

### Phase 10: Dashboard & Reporting
- Implemented financial dashboard with metrics and Chart.js visualizations
- Files created:
  - `finance/templates/finance/dashboard.html` - Main dashboard with account balances, MTD/QTD summaries
  - `finance/templates/finance/reports/spending.html` - Spending report with category breakdown
  - `finance/templates/finance/reports/income_statement.html` - P&L report with retained earnings
  - `finance/tests/test_dashboard.py` - 32 tests for dashboard and reports
- Files modified:
  - `finance/views.py` - Added dashboard, spending_report, income_statement, dashboard_data_api views
  - `finance/urls.py` - Added dashboard and report routes
- Views:
  - `dashboard` - Main dashboard with account balances, MTD/QTD summaries, tax alerts, recent transactions
  - `spending_report` - Category spending breakdown with percentages
  - `income_statement` - P&L report with income, expenses, net profit, owner's draws, retained earnings
  - `dashboard_data_api` - JSON API for chart data (spending_by_category, income_vs_expense, monthly_trend)
- Features:
  - Account balances: cash available, credit balance, net position
  - Period summaries: MTD, QTD with income/expense/net profit
  - Tax alerts display (unacknowledged alerts)
  - Chart.js integration: doughnut, pie, bar charts
  - Period selector: MTD, QTD, YTD, last month, last quarter, custom range
  - Income statement with retained earnings calculation
- Helper Functions:
  - `_get_date_range_for_period()` - Calculate start/end dates for periods
  - `_calculate_period_summary()` - Calculate income, expenses, net profit
  - `_get_spending_by_category()` - Aggregate expenses by category
  - `_get_income_by_category()` - Aggregate income by category
- Tests: 32 new tests (327 total now passing)
- Notes: Phase 10 complete.

### Phase 9: Category Management
- Implemented category CRUD with protection for system categories
- Files created:
  - `finance/templates/finance/category_list.html` - Split view for expense/income categories
  - `finance/templates/finance/category_form.html` - Create/edit form with system category warning
  - `finance/templates/finance/category_detail.html` - Detail view with transaction count
  - `finance/tests/test_categories.py` - 35 tests for category functionality
- Files modified:
  - `finance/forms.py` - Added CategoryForm with unique name validation per type
  - `finance/views.py` - Added category CRUD views
  - `finance/urls.py` - Added category routes
- Views:
  - `category_list` - Split view with expense and income categories
  - `category_create` - Create new categories with type preselection
  - `category_edit` - Edit categories (system categories limited)
  - `category_detail` - View with transaction count and recent transactions
  - `category_delete` - Delete with protection for system and used categories
  - `category_toggle_active` - Activate/deactivate categories
- Protections:
  - System categories cannot be deleted (raises ValidationError)
  - Categories with transactions cannot be deleted
  - System categories cannot change type (disabled field)
  - Duplicate name check is case-insensitive within same type
- Tests: 35 new tests (295 total now passing)
- Notes: Phase 9 complete.

### Phase 8: Account Management
- Implemented account CRUD with balance tracking
- Files created:
  - `finance/templates/finance/account_list.html` - List view with balance totals
  - `finance/templates/finance/account_form.html` - Create/edit form
  - `finance/templates/finance/account_detail.html` - Detail with transaction history
  - `finance/migrations/0003_seed_default_accounts.py` - Seed 3 default accounts
  - `finance/tests/test_accounts.py` - 30 tests for account functionality
- Files modified:
  - `finance/forms.py` - Added AccountForm with validation
  - `finance/views.py` - Added account CRUD views
  - `finance/urls.py` - Added account routes
- Views:
  - `account_list` - List with balance totals by type
  - `account_create` - Create new accounts
  - `account_edit` - Edit existing accounts
  - `account_detail` - View with transaction history
  - `account_toggle_active` - Activate/deactivate accounts
- Default Accounts Seeded:
  - Amex Business Checking ($1,000 opening balance)
  - Amex Blue Business Cash ($0 opening balance)
  - Personal Amex ($0, is_personal=True)
- Balance Calculations:
  - Checking/Savings: opening + income - expenses - draws - transfers out + transfers in
  - Credit Card: opening + expenses - payments
- Tests: 30 new tests (260 total now passing)
- Notes: Phase 8 complete.

### Phase 7: CSV Import — American Express
- Implemented CSV import for American Express statement format
- Files created:
  - `finance/importers.py` - AmexCSVParser and CSVImporter classes
  - `finance/templates/finance/csv_import.html` - Upload form
  - `finance/templates/finance/csv_preview.html` - Preview with category mapping
  - `finance/templates/finance/csv_results.html` - Import results display
  - `finance/templates/finance/csv_import_list.html` - Import history list
  - `finance/tests/test_csv_import.py` - 39 tests for import functionality
- Files modified:
  - `finance/views.py` - Added csv_import_upload, csv_import_preview, csv_import_results, csv_import_list
  - `finance/urls.py` - Added CSV import routes
- Views:
  - `csv_import_upload` - Upload form with account selection
  - `csv_import_preview` - Preview parsed rows, adjust categories
  - `csv_import_results` - Show import summary and errors
  - `csv_import_list` - List all imports with status
- Features:
  - Amex CSV format parsing with header detection
  - Date parsing: MM/DD/YYYY, M/D/YYYY, ISO format
  - Amount parsing with dollar signs and commas
  - Automatic category mapping (Amex to local)
  - Duplicate detection by date/amount/description
  - Per-row category override in preview
  - Refunds (negative amounts) imported as income
  - Import history tracking
- Tests: 39 new tests (230 total now passing)
- Notes: Phase 7 complete.

### Phase 6: Transaction Entry — Manual Entry
- Implemented full transaction CRUD with forms, views, and templates
- Files created:
  - `finance/templates/finance/base.html` - Base template with styling
  - `finance/templates/finance/transaction_list.html` - List view with filters, pagination
  - `finance/templates/finance/transaction_form.html` - Create/edit form with JS enhancements
  - `finance/templates/finance/transaction_detail.html` - Detail view with receipt management
  - `finance/tests/test_transaction_views.py` - 45 tests for transaction views
- Files modified:
  - `finance/forms.py` - Added TransactionForm, TransactionFilterForm
  - `finance/views.py` - Added transaction CRUD views, API endpoints
  - `finance/urls.py` - Added transaction and API routes
  - `finance/models.py` - Fixed owner's draw validation guard
- Views:
  - `transaction_list` - List with filtering (account, type, category, date range, search)
  - `transaction_create` - Create new transactions
  - `transaction_edit` - Edit existing transactions
  - `transaction_detail` - View details with receipt upload
  - `transaction_delete` - Delete with receipt cleanup
- API Endpoints:
  - `GET /finance/api/vendor-suggest/?q=` - Vendor auto-suggest (min 2 chars)
  - `GET /finance/api/categories/?type=expense|income` - Categories by type
- Form Validation:
  - Category required for income/expense, must match transaction type
  - Transfer requires destination account, cannot transfer to same account
  - Owner's draw must come from checking account
  - Transaction date cannot be in the future
- Features:
  - Pagination (25 per page)
  - Dynamic category filtering based on transaction type (JavaScript)
  - Vendor auto-suggest with debouncing
  - Receipt upload integration from detail view
- Tests: 45 new tests (191 total now passing)
- Notes: Phase 6 complete.

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
