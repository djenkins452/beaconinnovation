# Beacon Innovations - Claude Code Changelog

This file tracks all changes made by Claude Code during development.

---

## 2026-07-27

### Publish AIMS build 0.3.0 (Build 3) to the Product Download Portal
- Published the newest signed AIMS production export to the portal and OTA static endpoint. No release-framework / `/release` / `distribution` work.
- IPA: `AIMSField.ipa`, 1,137,725 bytes, bundle `com.beaconinnovation.aims.field`, **version 0.3.0**, **build 3** (signed: embedded.mobileprovision + `_CodeSignature`).
- `products/management/commands/bootstrap_portal.py`: added an idempotent step that attaches the committed `static/downloads/AIMSField.ipa` to the existing **AIMS** product's download and sets Current Version / Current Build from the IPA's own `Info.plist`. Runs in the existing deploy chain, stores under a stable name (`product_downloads/AIMSField.ipa`), and re-attaches when the stored file is missing or differs — so it survives Railway's ephemeral filesystem without needing an admin upload. No new product created; replaces the previous file.
- Updated committed static artifacts (served by WhiteNoise from `staticfiles/`, no collectstatic on deploy): `static/downloads/AIMSField.ipa` + `staticfiles/downloads/AIMSField.ipa` (0.2.0/build 2 → 0.3.0/build 3), `install.html` "Build 2" → "Build 3". OTA `manifest.plist` already correct (bundle-identifier `com.beaconinnovation.aims.field`, bundle-version 0.3.0, url `/static/downloads/AIMSField.ipa`).
- The admin account `dannyjenkins71@gmail.com` is granted AIMS access by the same command.
- Verified on dev: Login → My Products → AIMS → Download Latest Version returns HTTP 200, `attachment; filename="AIMSField.ipa"`, 1,137,725 bytes; downloaded bytes decode to bundle/version/build 0.3.0/3. Authorization intact (anonymous → 302 login; unauthorized user → AIMS hidden from My Products and 404 on detail/download). Full suite 478 passing.
- Files: `products/management/commands/bootstrap_portal.py`, `products/tests.py`, `static/downloads/{AIMSField.ipa,install.html}`, `staticfiles/downloads/{AIMSField.ipa,install.html,manifest.plist}`.

### Fix: Django admin crash on Python 3.14 (`'super' object has no attribute 'dicts'`)
- **Symptom:** Opening any Django admin change list in production (reported on Product Download Portal → Products) raised `AttributeError: 'super' object has no attribute 'dicts'` while rendering.
- **Root cause:** Not an admin/ModelAdmin bug. `runtime.txt` pinned production to **Python 3.14.0**, which Django 5.1 does not support (5.1 supports Python 3.10–3.13). On Python 3.14, `copy.copy(super())` in `django.template.context.BaseContext.__copy__` no longer returns a real `Context`, so the subsequent `duplicate.dicts = …` fails. The admin change list copies the template context while rendering result rows, triggering it. Dev never reproduced it because the dev venv runs Python 3.12. The `ProductAdmin` is a standard, unmodified `ModelAdmin` (no custom `changelist_view`/`get_queryset`/`get_changelist`/`ChangeList`/templates).
- **Fix:** Pinned `runtime.txt` to a supported, standard-format version: `python-3.13.1` (was the malformed `python 3.14.0`, whose space instead of hyphen likely caused the builder to fall back to the latest Python, 3.14). This resolves the crash for every admin page, not just Products.
- Files: `runtime.txt`.
- Verified on a supported Python: Products change list opens; AIMS is editable; users can be assigned; an IPA uploads via the admin; and My Products shows AIMS to a newly assigned user with a working download. Full suite 476 passing.

#### Runtime verification (before deploy) + verification tooling
- **Build-config audit:** the repo contains **no** Dockerfile, `nixpacks.toml`, `railway.json/toml`, `.python-version` (before this change), `Pipfile`, or `pyproject.toml` — nothing overrides the Python version except `runtime.txt`. Correct Railway/Heroku format is `python-X.Y.Z` (hyphen).
- **Evidence Railway honors runtime.txt here:** production's `runtime.txt` had read `python 3.14.0` since 2025-12-14 (commit `b468839`) and production exhibited the Python-3.14 bug — i.e. the builder read that file and installed 3.14 even with the malformed space. So the corrected `python-3.13.1` will resolve to Python 3.13.x. (Note: builders pin major.minor and pick the latest available patch, so expect 3.13.x, not necessarily exactly 3.13.1.)
- **Caveat (not verifiable from the repo):** a Railway dashboard environment variable (e.g. `NIXPACKS_PYTHON_VERSION`) or a custom build/start command could still override this. Confirmed empirically after deploy via the health endpoint below.
- Added `.python-version` (`3.13`) as a builder-agnostic, belt-and-suspenders pin (honored by both Nixpacks and Railpack).
- Added an unauthenticated `GET /healthz/` endpoint that reports `python` version and runs `copy.copy(Context(...))` — the exact code path that fails on Python 3.14 — returning `context_copy_ok`. This allows the fix to be verified in production without an authenticated admin session.
- Files: `.python-version` (new), `website/views.py`, `website/urls.py`, `website/tests.py`. Full suite 477 passing.

### Product Download Portal — bootstrap moved to a management command
- **Immutable migrations.** Restored `finance/migrations/0006_create_superuser.py` to its exact original committed content (from commit `90e206d`). Historical/committed migrations are treated as immutable and are no longer edited by this work.
- **Bootstrap is now a management command, not a migration.** Added `products/management/commands/bootstrap_portal.py`. It is idempotent and safe to run on every deploy, and it:
  - Leaves an existing administrator account **completely unchanged**.
  - If the admin (`dannyjenkins71@gmail.com`) does not exist, creates it with a temporary password from `BEACON_ADMIN_PASSWORD` (or a strong random `secrets.token_urlsafe` password), displays it **once**, and flags the account (group `portal_must_change_password`) to force a password change on first login.
  - Ensures the AIMS product exists and grants the admin access.
- **No side effects in migrations.** `products/migrations/0002_bootstrap_portal.py` is now an empty no-op (kept only to preserve the migration chain for `0003`). No secrets or account creation in any migration.
- **Deploy wiring.** `procfile` release step now runs `python manage.py bootstrap_portal` after `migrate`.
- Files: `finance/migrations/0006_create_superuser.py` (restored), `products/management/commands/bootstrap_portal.py` (new), `products/management/__init__.py` + `products/management/commands/__init__.py` (new), `products/migrations/0002_bootstrap_portal.py` (no-op), `products/tests.py` (command tests replace migration-seeding tests), `procfile`.
- Tests: full suite 476 passing (`python manage.py test`).
- Note: On production the admin already exists (created by finance/0006 with `Beacon2026`), so the command leaves it unchanged — log in and change that password. The forced-change flow applies to brand-new deployments where no admin exists yet.

## 2026-07-26

### Secure Product Download Portal (Phase 1)
- New `products` app: authenticated portal for distributing the latest build of each Beacon product to authorized users only. Reuses Django's built-in auth (no custom auth system).
- User workflow: log in → My Products (only authorized products) → product page → Download Latest Version.
- Files created:
  - `products/models.py` - `Product` model (name, slug, description, current_version, icon, download_file, download_enabled) + `authorized_users` M2M to `auth.User`. Any file type (IPA/APK/EXE/DMG/ZIP/…). Uploading a new build replaces the previous file in place.
  - `products/views.py` - login/logout, My Products, product detail, authenticated download (streams via `FileResponse` as attachment; storage URL never exposed; authorization re-checked per request; unauthorized → 404, not 403).
  - `products/urls.py` - routes under `/products/`; wires Django's built-in `PasswordChangeView`/`PasswordChangeDoneView` for changing the temp password after first login.
  - `products/admin.py` - create products, assign users (`filter_horizontal`), upload/replace build, enable/disable download.
  - `products/templates/products/{base,login,my_products,product_detail,password_change,password_change_done}.html` - Bootstrap 5, matches site theme (`#f4623a`).
  - `products/tests.py` - 12 tests (authorization, 404 for unauthorized/anonymous, download streaming, disabled-download, slug autogen, replace-build-deletes-old-file).
- Files modified:
  - `beaconinnovation/settings.py` - added `products` to `INSTALLED_APPS`.
  - `beaconinnovation/urls.py` - added `path('products/', include('products.urls'))`.
  - `website/templates/home.html` - added "Downloads" nav link to `/products/`.
- Migrations:
  - `products/0001_initial` - Product model.
  - `products/0002_bootstrap_portal` - ensures admin `dannyjenkins71@gmail.com` exists (temp password `Beacon!Temp2026`, created only if missing — never resets an existing password), creates the `AIMS` product, and grants the admin access.
- Tests: 12 passing (`python manage.py test products`).
- Notes:
  - Downloads use local media storage (`FileField`) + authenticated view, consistent with finance receipts. On Railway's ephemeral disk, uploaded builds do not survive redeploys; migrating product builds to Cloudinary (as finance receipts already do) is a natural future step.
  - Out of scope by design (future, no redesign needed): release notes, version history, beta channels, organizations, licensing, analytics.
  - Admin must change the temporary password after first login via `/products/password/change/` or the Django admin.

### Product Download Portal — Phase 1 refinements
- Follow-up to the portal above. No scope expansion.
- **No passwords in source control.** Rewrote `products/0002_bootstrap_portal` to remove the hardcoded temporary password. When the admin account is missing, the temp password is either taken from the `BEACON_ADMIN_PASSWORD` env var or randomly generated (`secrets.token_urlsafe`) and printed **once** to the deploy console/log. If the admin already exists, it is left completely untouched.
- **Forced password change on first login (simple).** A newly bootstrapped admin is added to the built-in Django group `portal_must_change_password`; portal views redirect such users to the change-password page until they set a new password (flag cleared on success via `PortalPasswordChangeView`). No MFA, email verification, security questions, or reset workflows — reuses Django's built-in password-change view.
- **Build info on product page.** Added `Product.current_build`; the product page now shows labeled "Current Version" and "Current Build" above the download button (informational during testing, not release management).
- **Navigation label.** Home nav link now reads "My Products" (was "Downloads").
- Files modified: `products/models.py`, `products/views.py`, `products/urls.py`, `products/admin.py`, `products/migrations/0002_bootstrap_portal.py`, `products/templates/products/product_detail.html`, `products/tests.py`, `website/templates/home.html`.
- Migrations: `products/0003_product_current_build_alter_product_current_version` (adds `current_build`).
- Tests: passing (`python manage.py test products`), including new coverage for the forced-change gate and build display.

### Temporary OTA Install Page for AIMS Field
- Temporary solution to get AIMS Field (iOS) installed via over-the-air (OTA) install. Permanent deployment portal intentionally NOT built.
- Files created:
  - `static/downloads/install.html` - OTA install page with single "Install AIMS Field" button (itms-services:// URL)
  - `static/downloads/manifest.plist` - OTA manifest (bundle id `com.beaconinnovation.aims.field`, version 0.2.0, title "AIMS Field", references https://beacon-innovation.com/static/downloads/AIMSField.ipa)
  - `staticfiles/downloads/{AIMSField.ipa,install.html,manifest.plist}` - mirrored into STATIC_ROOT so WhiteNoise serves them in production even without a build-time collectstatic
- Files modified:
  - `beaconinnovation/settings.py` - Added `WHITENOISE_MIMETYPES` to serve `.plist` as `text/xml` (mimetypes does not recognize .plist, which otherwise defaults to application/octet-stream and can break OTA)
- Notes:
  - Static files served by WhiteNoise from STATIC_ROOT (`staticfiles/`, committed to repo). STATIC_URL is `/static/`.
  - Verified under DEBUG=False via WSGI: both /static/downloads/AIMSField.ipa (200, octet-stream) and /static/downloads/manifest.plist (200, text/xml) are served correctly.
  - Install URL to share: https://beacon-innovation.com/static/downloads/install.html (open in Safari on iPhone).

---

## 2026-01-09

### QA Review & Security/Validation Fixes
- Conducted comprehensive QA review and implemented critical fixes
- Files created:
  - `finance/migrations/0005_add_category_unique_constraint.py` - Database constraint for category uniqueness
- Files modified:
  - `finance/views.py` - Added receipt permission check security fix
  - `finance/forms.py` - Added balance validation for transfers and owner's draws
  - `finance/models.py` - Added UniqueConstraint on Category(name, category_type)
  - `finance/templates/finance/transaction_list.html` - Added Export CSV button
  - `finance/tests/` (11 files) - Updated to use get_or_create for category uniqueness
- Security Fixes:
  - **Receipt Permission Check:** Added `_check_receipt_access()` to verify user has permission to view/modify receipts. Previously any logged-in user could access any receipt by URL.
  - Applied to: view_receipt, download_receipt, delete_receipt, get_receipt_info
- Validation Fixes:
  - **Transfer Balance Validation:** Added check in TransactionForm to prevent transfers exceeding available balance
  - **Owner's Draw Balance Validation:** Added check to prevent owner's draws exceeding available balance
  - Both show user-friendly error with available amount
- Data Integrity:
  - **Category Uniqueness Constraint:** Added database-level UniqueConstraint on (name, category_type) to prevent duplicate categories
- UI Improvements:
  - Added "Export CSV" button to transaction list that preserves current filter parameters
- Tests: All 417 tests passing
- Notes: These fixes address critical security and data integrity issues identified during QA review.

### Code Review & Performance Improvements
- Conducted comprehensive code review and implemented performance fixes
- Files created:
  - `finance/migrations/0004_add_auditlog_indexes.py` - Database indexes for AuditLog
- Files modified:
  - `finance/models.py` - Added AccountManager with optimized balance queries, AuditLog indexes
  - `finance/views.py` - Updated dashboard/account_list to use optimized queries, improved recurring_list aggregation
  - `finance/importers.py` - Enhanced CSV validation with header checks and row limits
  - `finance/tests/test_dashboard.py` - Updated tests for string-based JSON responses
- Performance Improvements:
  - **N+1 Query Fix:** Added `AccountManager.with_balances()` method that calculates all account balances in a single query using subqueries and annotations
  - **Database Indexes:** Added indexes to AuditLog on `action`, `model_name`, `object_id`, `created_at` fields plus composite index
  - **Recurring List Optimization:** Replaced Python iteration with database aggregation using `Case/When` for totals calculation
  - **JSON Precision:** Changed chart API to return Decimal values as strings to preserve precision
- Validation Improvements:
  - CSV import now validates required headers (Date, Amount, Description)
  - Added maximum row count limit (10,000) for CSV imports
  - Better error messages for invalid CSV format
- Tests: All 417 tests passing
- Notes: Performance improvements reduce database queries significantly for dashboards with many accounts.

### Phase 14: Export Functionality
- Added CSV export for transactions and reports
- Files created:
  - `finance/tests/test_exports.py` - 22 tests for export functionality
- Files modified:
  - `finance/views.py` - Added export_transactions, export_spending_report, export_income_statement views
  - `finance/urls.py` - Added export routes
- Export Views:
  - `export_transactions` - Export filtered transactions to CSV with all fields
  - `export_spending_report` - Export spending by category with percentages
  - `export_income_statement` - Export P&L report with income, expenses, draws, retained earnings
- Features:
  - Transaction export supports all filters (account, type, category, date range, search)
  - Report exports support period selection (MTD, QTD, YTD, last month, last quarter, custom)
  - CSV includes headers and properly formatted data
  - Automatic filename generation with date
- Routes:
  - `GET /finance/export/transactions/` - Export transactions CSV
  - `GET /finance/export/spending/` - Export spending report CSV
  - `GET /finance/export/income-statement/` - Export income statement CSV
- Tests: 22 new tests (453 total now passing)
- Notes: Phase 14 export functionality complete.

### Phase 14: Navigation and Polish
- Implemented comprehensive navigation menu across all pages
- Files created:
  - `finance/tests/test_navigation.py` - 14 tests for navigation functionality
- Files modified:
  - `finance/templates/finance/base.html` - Updated with full navigation menu
- Navigation Features:
  - Dashboard, Transactions, Accounts, Categories (main sections)
  - Recurring, Imports (data management)
  - Reports, Tax Alerts, Audit Log (analysis/compliance)
  - Visual dividers to group related items
  - Active state highlighting for current page
  - Responsive layout with proper spacing
- Styling:
  - Brand logo links to dashboard
  - Hover states for all links
  - Blue highlight for active page
  - Consistent padding and alignment
- Tests: 14 new tests (431 total now passing)
- Notes: Phase 14 complete. Financial tracker UI is now fully navigable.

### Phase 13: Audit Log Viewer
- Implemented audit log viewing with comprehensive filtering
- Files created:
  - `finance/templates/finance/audit_log_list.html` - List view with filtering and pagination
  - `finance/templates/finance/audit_log_detail.html` - Detail view with field changes
  - `finance/tests/test_audit_views.py` - 22 tests for audit log UI and security
- Files modified:
  - `finance/views.py` - Added audit_log_list and audit_log_detail views
  - `finance/urls.py` - Added audit log routes
- Views:
  - `audit_log_list` - Paginated list with filters for model, action, user, date range, search
  - `audit_log_detail` - Detail view showing before/after field changes
- Filter Features:
  - Filter by model name (Transaction, Account, Category, etc.)
  - Filter by action (create, update, delete)
  - Filter by user
  - Filter by date range
  - Search in object representation
  - All filters can be combined
- UI Features:
  - Stats showing total logs and today's logs
  - Color-coded action badges (green=create, blue=update, red=delete)
  - Pagination (50 per page)
  - Before/after comparison for updates
  - Raw JSON data display
  - IP address and user agent tracking
- Tests: 22 new tests (443 total now passing)
- Notes: Phase 13 complete.

### Phase 12: Tax Alerts UI
- Implemented tax alert viewing and acknowledgment functionality
- Files created:
  - `finance/templates/finance/alert_list.html` - List view with unacknowledged/acknowledged sections
  - `finance/templates/finance/alert_detail.html` - Detail view with quarter transactions
  - `finance/tests/test_alert_views.py` - 33 tests for tax alert UI functionality
- Files modified:
  - `finance/views.py` - Added tax alert views and helper functions
  - `finance/urls.py` - Added tax alert routes
- Views:
  - `alert_list` - List with unacknowledged alerts requiring attention, acknowledged history
  - `alert_detail` - View with net profit breakdown, income/expense transactions, IRS due date
  - `alert_acknowledge` - Mark alert as acknowledged with optional notes
  - `alert_unacknowledge` - Revert acknowledgment status
  - `alert_calculate` - Manual calculation for any quarter/year
- Helper Functions:
  - `_get_quarter_dates(quarter, year)` - Returns start/end dates for a quarter
  - `_get_tax_due_date(quarter, year)` - Returns IRS estimated tax due date
- UI Features:
  - Prominent display of unacknowledged alerts requiring attention
  - Calculate button for current quarter
  - Form to calculate any quarter/year
  - Income and expense transaction breakdown in detail view
  - IRS due date display (Apr 15, Jun 15, Sep 15, Jan 15)
  - Acknowledge with optional notes
- Tests: 33 new tests (395 total now passing)
- Notes: Phase 12 complete.

### Phase 11: Recurring Transactions UI
- Implemented recurring transaction CRUD and manual generation
- Files created:
  - `finance/templates/finance/recurring_list.html` - List view with active/inactive sections, stats
  - `finance/templates/finance/recurring_form.html` - Create/edit form
  - `finance/templates/finance/recurring_detail.html` - Detail view with generated transactions
  - `finance/tests/test_recurring_views.py` - 35 tests for recurring UI functionality
- Files modified:
  - `finance/forms.py` - Added RecurringTransactionForm with validation
  - `finance/views.py` - Added recurring CRUD views, toggle active, manual generate
  - `finance/urls.py` - Added recurring transaction routes
  - `finance/models.py` - Fixed clean() method for day_of_month None check
- Views:
  - `recurring_list` - List with active/inactive sections, monthly totals, estimated monthly cost
  - `recurring_create` - Create new recurring transaction template
  - `recurring_edit` - Edit existing recurring transaction
  - `recurring_detail` - View with details and generated transactions history
  - `recurring_toggle_active` - Activate/deactivate recurring template
  - `recurring_delete` - Delete recurring template (preserves generated transactions)
  - `recurring_generate` - Manually generate transaction from template
- Form Features:
  - Filters accounts to active only
  - Filters categories to active expense categories only
  - Validates day_of_month (1-31)
  - Validates end_date > start_date
  - Auto-calculates next_due on save
- UI Features:
  - Stats cards: active count, monthly total, estimated monthly cost
  - Separate active/inactive tables
  - Frequency badges with color coding
  - Generated transactions list in detail view
- Tests: 35 new tests (362 total now passing)
- Notes: Phase 11 complete.

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

## 2026-07-27

### Publish AIMS Field release 0.3.0 (Build 2)
- Files: `static/downloads/AIMSField.ipa`, `static/downloads/manifest.plist`, `static/downloads/install.html`
- Synced from IPA (source of truth): Version 0.3.0, Build 2, Bundle ID `com.beaconinnovation.aims.field`
- manifest.plist `bundle-version` 0.2.0 → 0.3.0; install.html now shows "Version 0.3.0 (Build 2)"
- Migrations: none
- Tests: none
- Notes: OTA install deployment only, no application code changes

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
