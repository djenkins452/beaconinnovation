# Beacon Innovations Financial Tracker

## Design Specification & Implementation Guide

**Version:** 1.0  
**Created:** January 8, 2026  
**Author:** Claude (CFO + Software Engineer perspective)  
**For:** Danny Jenkins, Founder - Beacon Innovations LLC

---

## Executive Summary

The Beacon Innovations Financial Tracker is a Django-based internal accounting system designed specifically for a single-member LLC. It provides complete financial visibility, receipt management with OCR, and tax compliance alerts — all within your existing Beacon Innovations website.

### What This System Does

| Capability | Description |
|------------|-------------|
| **Transaction Ledger** | Track all income and expenses across multiple accounts with full categorization |
| **Multi-Account Support** | Amex Business Checking, Amex Blue Business Cash credit card, Personal Amex (backup) |
| **Receipt Management** | Upload, store, and organize receipts (PDF, JPG, PNG) tied to transactions |
| **OCR Extraction** | Automatically read receipts and suggest vendor, amount, and date |
| **CSV Import** | Bulk import transactions from Amex bank statements |
| **Recurring Transactions** | Auto-generate monthly subscription expenses |
| **Real-Time Balance** | Always-current view of account balances and cash position |
| **Owner's Draws** | Track money moved from business to personal separately |
| **Quarterly Tax Alerts** | Automatic warnings when net profit exceeds $1,000/quarter |
| **Category Reports** | Spending summaries by category for tax preparation |
| **Audit Log** | Complete history of all changes (who, what, when) |
| **Accountant Access** | Future-ready read-only access for tax professionals |

### Design Philosophy

- **Cash Basis Accounting** — Record when money moves, not when invoiced
- **Receipt Required** — All expenses must have documentation attached
- **Single User** — Built for you, with optional read-only sharing later
- **Private & Secure** — All data on your server, OCR runs locally via Tesseract
- **Configurable** — Add/edit/delete categories anytime

---

## Account Structure

### Accounts to Track

| Account | Type | Starting Balance | Purpose |
|---------|------|------------------|---------|
| Amex Business Checking | Checking | $1,000.00 | Operating account, revenue deposits |
| Amex Blue Business Cash | Credit Card | $0.00 | Primary expense card |
| Personal Amex | Credit Card | $0.00 | Backup only (flagged separately) |

### Category Configuration

**Expense Categories (Configurable):**
- Software & Subscriptions
- Equipment
- Professional Services
- Advertising & Marketing
- Office Supplies
- Education & Training
- Travel
- Meals & Entertainment
- Bank Fees & Interest
- Miscellaneous

**Income Categories (Configurable):**
- Service Revenue
- Product Revenue
- Refunds
- Owner Contributions
- Other Income

**Special Transaction Types:**
- Owner's Draw (money to personal)
- Transfer (between business accounts)

---

## Data Model Design

### Core Models

#### 1. Account
```
Account
├── id (UUID, primary key)
├── name (string, max 100)
├── account_type (enum: checking, credit_card, savings)
├── institution (string, max 100) — e.g., "American Express"
├── last_four (string, max 4) — last 4 digits for identification
├── is_personal (boolean) — True for personal cards used for business
├── is_active (boolean)
├── opening_balance (decimal, 2 places)
├── opening_balance_date (date)
├── notes (text, optional)
├── created_at (datetime)
├── updated_at (datetime)
└── created_by (FK to User)
```

#### 2. Category
```
Category
├── id (UUID, primary key)
├── name (string, max 100)
├── category_type (enum: expense, income)
├── description (text, optional)
├── is_system (boolean) — True for default categories, prevents deletion
├── is_active (boolean)
├── display_order (integer)
├── created_at (datetime)
└── updated_at (datetime)
```

#### 3. Transaction
```
Transaction
├── id (UUID, primary key)
├── account (FK to Account)
├── transaction_type (enum: expense, income, transfer, owners_draw)
├── category (FK to Category, nullable for transfers)
├── amount (decimal, 2 places) — always positive
├── transaction_date (date)
├── description (string, max 500)
├── vendor (string, max 200, optional)
├── reference_number (string, max 100, optional) — check number, confirmation
├── is_recurring (boolean)
├── recurring_source (FK to RecurringTransaction, nullable)
├── transfer_to_account (FK to Account, nullable) — for transfers only
├── notes (text, optional)
├── is_reconciled (boolean)
├── reconciled_at (datetime, nullable)
├── created_at (datetime)
├── updated_at (datetime)
└── created_by (FK to User)
```

#### 4. Receipt
```
Receipt
├── id (UUID, primary key)
├── transaction (FK to Transaction)
├── file (CloudinaryField) — stored in Cloudinary
├── original_filename (string, max 255)
├── file_type (enum: pdf, jpg, png)
├── file_size (integer) — bytes
├── ocr_processed (boolean)
├── ocr_vendor (string, max 200, nullable)
├── ocr_amount (decimal, nullable)
├── ocr_date (date, nullable)
├── ocr_raw_text (text, nullable) — full OCR output for debugging
├── ocr_confidence (decimal, nullable) — 0.0 to 1.0
├── uploaded_at (datetime)
└── uploaded_by (FK to User)
```

#### 5. RecurringTransaction
```
RecurringTransaction
├── id (UUID, primary key)
├── account (FK to Account)
├── category (FK to Category)
├── amount (decimal, 2 places)
├── description (string, max 500)
├── vendor (string, max 200)
├── frequency (enum: monthly, quarterly, annually)
├── day_of_month (integer, 1-31) — when to generate
├── start_date (date)
├── end_date (date, nullable) — null = ongoing
├── is_active (boolean)
├── last_generated (date, nullable)
├── next_due (date)
├── created_at (datetime)
├── updated_at (datetime)
└── created_by (FK to User)
```

#### 6. TaxAlert
```
TaxAlert
├── id (UUID, primary key)
├── quarter (integer, 1-4)
├── year (integer)
├── threshold_amount (decimal) — $1,000 default
├── actual_net_profit (decimal)
├── alert_triggered (boolean)
├── alert_date (datetime, nullable)
├── acknowledged (boolean)
├── acknowledged_at (datetime, nullable)
├── notes (text, optional)
├── created_at (datetime)
└── updated_at (datetime)
```

#### 7. AuditLog
```
AuditLog
├── id (UUID, primary key)
├── user (FK to User)
├── action (enum: create, update, delete)
├── model_name (string, max 100) — e.g., "Transaction"
├── object_id (UUID)
├── object_repr (string, max 500) — human-readable description
├── changes (JSON) — before/after values
├── ip_address (GenericIPAddress, nullable)
├── user_agent (string, max 500, nullable)
├── created_at (datetime)
```

#### 8. CSVImport
```
CSVImport
├── id (UUID, primary key)
├── account (FK to Account)
├── file (FileField) — temporary storage
├── original_filename (string, max 255)
├── row_count (integer)
├── imported_count (integer)
├── skipped_count (integer)
├── error_count (integer)
├── status (enum: pending, processing, completed, failed)
├── errors (JSON, nullable) — list of row errors
├── imported_at (datetime)
└── imported_by (FK to User)
```

### Model Relationships Diagram

```
User (Django auth.User)
  │
  ├── Account (one-to-many)
  │     │
  │     ├── Transaction (one-to-many)
  │     │     │
  │     │     └── Receipt (one-to-many)
  │     │
  │     ├── RecurringTransaction (one-to-many)
  │     │
  │     └── CSVImport (one-to-many)
  │
  └── AuditLog (one-to-many)

Category (standalone, linked to Transaction)
TaxAlert (standalone, calculated from Transactions)
```

---

## Feature Specifications

### 1. Transaction Entry

**Manual Entry Form:**
- Account selector (dropdown)
- Transaction type (expense/income/transfer/draw)
- Category (filtered by type)
- Amount (positive number)
- Date (defaults to today)
- Description (required)
- Vendor (optional, auto-suggest from history)
- Reference number (optional)
- Notes (optional)
- Receipt upload (required for expenses)

**Validation Rules:**
- Amount must be > 0
- Date cannot be in the future
- Expense transactions require at least one receipt
- Transfer requires destination account
- Owner's draw requires checking account as source

### 2. Receipt Upload & OCR

**Upload Process:**
1. User selects file (PDF, JPG, PNG)
2. File uploaded to Cloudinary (beacon-innovations/receipts/ folder)
3. Tesseract OCR extracts text
4. Parser identifies vendor, amount, date
5. Suggestions displayed for user confirmation
6. User accepts or corrects values

**OCR Configuration:**
- Engine: Tesseract (local)
- Languages: English
- Preprocessing: Grayscale, contrast enhancement, deskew
- Parsing: Regex patterns for common receipt formats

### 3. CSV Import

**Supported Format (Amex):**
```csv
Date,Description,Amount,Category
01/05/2026,GITHUB.COM,4.00,Software & Subscriptions
01/07/2026,RAILWAY APP,5.00,Software & Subscriptions
```

**Import Process:**
1. User uploads CSV
2. System parses and validates rows
3. Preview shown with mapped categories
4. User confirms import
5. Transactions created (without receipts — user adds later)
6. Import log saved for audit

**Duplicate Detection:**
- Match on: account + date + amount + description
- Flag potential duplicates for review

### 4. Recurring Transactions

**Setup:**
- Define template (account, category, amount, vendor, description)
- Set frequency (monthly, quarterly, annually)
- Set day of month to generate
- Set start date (and optional end date)

**Generation Process:**
- Daily job checks for due recurring transactions
- Creates transaction with `is_recurring=True` and `recurring_source` link
- Updates `last_generated` and `next_due` dates
- Sends notification (optional)

**Note:** Generated transactions still require receipt upload.

### 5. Balance Calculations

**Account Balance:**
```
Current Balance = Opening Balance
                + Sum(Income to this account)
                - Sum(Expenses from this account)
                + Sum(Transfers into this account)
                - Sum(Transfers out of this account)
                - Sum(Owner's Draws from this account)
```

**Credit Card Balance (owed):**
```
Balance Owed = Sum(Expenses on this card)
             - Sum(Payments to this card)
```

**Net Cash Position:**
```
Net Position = Sum(All Checking Balances)
             - Sum(All Credit Card Balances Owed)
```

### 6. Quarterly Tax Alerts

**Calculation (each quarter):**
```
Net Profit = Total Income - Total Expenses
```

**Quarters:**
- Q1: January 1 - March 31
- Q2: April 1 - June 30
- Q3: July 1 - September 30
- Q4: October 1 - December 31

**Alert Trigger:**
- If Net Profit >= $1,000 for the quarter
- Alert created and displayed on dashboard
- Email notification (optional)

**IRS Estimated Tax Due Dates:**
- Q1: April 15
- Q2: June 15
- Q3: September 15
- Q4: January 15 (next year)

### 7. Reports

**Dashboard Summary:**
- Current balances (all accounts)
- Net cash position
- Month-to-date income/expenses
- Quarter-to-date net profit
- Tax alert status

**Category Spending Report:**
- Date range selector
- Expenses by category (table + chart)
- Comparison to previous period

**Income Statement (P&L):**
- Date range selector
- Total income by category
- Total expenses by category
- Net profit/loss

**Transaction History:**
- Filterable by account, category, date range, type
- Exportable to CSV
- Includes receipt links

### 8. Audit Log

**Tracked Actions:**
- Create, update, delete on all financial models
- User who made the change
- Timestamp
- Before/after values (JSON diff)
- IP address and user agent

**Viewing:**
- Admin-only access
- Filterable by model, user, date range
- Cannot be modified or deleted

### 9. Security & Access

**Current User (Danny):**
- Full access to all features
- Can create, edit, delete all records

**Future Accountant Access:**
- Read-only flag on user account
- Can view all transactions, reports, receipts
- Cannot create, edit, or delete anything
- Separate login credentials

**Data Protection:**
- All receipts stored in Cloudinary with private access
- Database encrypted at rest (Railway PostgreSQL)
- HTTPS enforced
- Session timeout after inactivity

---

## URL Structure

```
/finance/                           # Dashboard
/finance/accounts/                  # Account list
/finance/accounts/new/              # Create account
/finance/accounts/<id>/             # Account detail
/finance/accounts/<id>/edit/        # Edit account

/finance/transactions/              # Transaction list (filterable)
/finance/transactions/new/          # Create transaction
/finance/transactions/<id>/         # Transaction detail
/finance/transactions/<id>/edit/    # Edit transaction

/finance/receipts/upload/           # Upload receipt (AJAX)
/finance/receipts/<id>/             # View receipt
/finance/receipts/<id>/ocr/         # Re-run OCR

/finance/categories/                # Category management
/finance/categories/new/            # Create category
/finance/categories/<id>/edit/      # Edit category

/finance/recurring/                 # Recurring transaction list
/finance/recurring/new/             # Create recurring
/finance/recurring/<id>/edit/       # Edit recurring

/finance/import/                    # CSV import
/finance/import/<id>/               # Import detail/results

/finance/reports/                   # Reports index
/finance/reports/spending/          # Category spending
/finance/reports/income-statement/  # P&L report
/finance/reports/export/            # Export to CSV

/finance/alerts/                    # Tax alerts
/finance/alerts/<id>/acknowledge/   # Acknowledge alert

/finance/audit-log/                 # Audit log (admin only)

/finance/api/vendor-suggest/        # AJAX vendor autocomplete
/finance/api/balance/<account_id>/  # AJAX balance check
```

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| Framework | Django 5.x |
| Database | PostgreSQL (prod), SQLite (dev) |
| File Storage | Cloudinary |
| OCR Engine | Tesseract (pytesseract) |
| Image Processing | Pillow |
| CSV Parsing | Python csv module |
| Charts | Chart.js |
| Frontend | Django templates + HTMX |
| Hosting | Railway |

---

## Implementation Phases

Each phase is designed to be copy/pasted into Claude Code as a single task. Complete each phase fully before moving to the next.

---

### Phase 1: Foundation — Admin Console & Task API

**Objective:** Build the admin console with task management API (clone from WLJ) so Claude Code can work from tasks.

**Deliverables:**
1. Create `admin_console` Django app
2. AdminTask model with JSON description field
3. Task status management (ready, in_progress, done, blocked)
4. API endpoints:
   - `GET /admin-console/api/claude/ready-tasks/`
   - `POST /admin-console/api/claude/tasks/<id>/status/`
5. Claude API key validation
6. JSON file upload for bulk task import
7. Admin UI for task management
8. Tests for all API endpoints

**Files to Create:**
- `admin_console/__init__.py`
- `admin_console/models.py`
- `admin_console/views.py`
- `admin_console/api_views.py`
- `admin_console/urls.py`
- `admin_console/admin.py`
- `admin_console/forms.py`
- `admin_console/templates/admin_console/`
- `admin_console/tests/`

**Task JSON Format:**
```json
{
    "objective": "What the task should accomplish",
    "inputs": ["Required context"],
    "actions": ["Step 1", "Step 2"],
    "output": "Expected deliverable"
}
```

**Acceptance Criteria:**
- [ ] Admin console accessible at `/admin-console/`
- [ ] Tasks can be created, edited, deleted via UI
- [ ] JSON upload creates multiple tasks
- [ ] API returns ready tasks with `auto_start=true` parameter
- [ ] API updates task status correctly
- [ ] API validates Claude API key header
- [ ] All tests pass

---

### Phase 2: Foundation — Core Finance Models

**Objective:** Create the core data models for the financial tracker.

**Deliverables:**
1. Create `finance` Django app
2. Account model
3. Category model with default categories
4. Transaction model
5. Receipt model (Cloudinary integration)
6. AuditLog model with auto-logging mixin
7. Database migrations
8. Admin registration for all models
9. Model tests

**Files to Create:**
- `finance/__init__.py`
- `finance/models.py`
- `finance/managers.py`
- `finance/admin.py`
- `finance/mixins.py` (audit logging)
- `finance/migrations/`
- `finance/tests/test_models.py`

**Default Categories to Seed:**

Expenses:
- Software & Subscriptions
- Equipment
- Professional Services
- Advertising & Marketing
- Office Supplies
- Education & Training
- Travel
- Meals & Entertainment
- Bank Fees & Interest
- Miscellaneous

Income:
- Service Revenue
- Product Revenue
- Refunds
- Owner Contributions
- Other Income

**Acceptance Criteria:**
- [ ] All models created with proper fields
- [ ] Migrations run without errors
- [ ] Default categories seeded via data migration
- [ ] Audit logging works on create/update/delete
- [ ] Models visible in Django admin
- [ ] All tests pass

---

### Phase 3: Foundation — Recurring Transactions & Tax Alerts

**Objective:** Add recurring transaction and tax alert models.

**Deliverables:**
1. RecurringTransaction model
2. TaxAlert model
3. CSVImport model
4. Management command for recurring transaction generation
5. Management command for tax alert calculation
6. Admin registration
7. Model tests

**Files to Create/Update:**
- `finance/models.py` (add models)
- `finance/management/commands/generate_recurring.py`
- `finance/management/commands/calculate_tax_alerts.py`
- `finance/tests/test_recurring.py`
- `finance/tests/test_tax_alerts.py`

**Acceptance Criteria:**
- [ ] RecurringTransaction generates transactions correctly
- [ ] TaxAlert calculates quarterly net profit
- [ ] Alert triggers at $1,000 threshold
- [ ] Management commands work standalone
- [ ] All tests pass

---

### Phase 4: Receipt Management — Upload & Storage

**Objective:** Implement receipt upload with Cloudinary storage.

**Deliverables:**
1. Cloudinary configuration for beacon-innovations folder
2. Receipt upload view (AJAX)
3. Receipt model file handling
4. File type validation (PDF, JPG, PNG)
5. File size limits (10MB max)
6. Receipt viewing/download
7. Tests for upload functionality

**Files to Create/Update:**
- `finance/views.py`
- `finance/forms.py`
- `finance/templates/finance/receipt_upload.html`
- `finance/tests/test_receipts.py`
- `beaconinnovation/settings.py` (Cloudinary config)

**Cloudinary Folder Structure:**
```
beacon-innovations/
└── receipts/
    └── {year}/
        └── {month}/
            └── {uuid}_{original_filename}
```

**Acceptance Criteria:**
- [ ] Files upload to Cloudinary successfully
- [ ] Invalid file types rejected
- [ ] Oversized files rejected
- [ ] Receipts viewable in browser
- [ ] Receipts downloadable
- [ ] All tests pass

---

### Phase 5: Receipt Management — OCR Processing

**Objective:** Implement Tesseract OCR for receipt text extraction.

**Deliverables:**
1. Tesseract installation verification
2. Image preprocessing (grayscale, contrast, deskew)
3. OCR text extraction
4. Parser for vendor, amount, date
5. Confidence scoring
6. OCR results stored on Receipt model
7. Re-run OCR endpoint
8. Tests for OCR functionality

**Files to Create/Update:**
- `finance/ocr.py`
- `finance/parsers.py`
- `finance/views.py` (OCR endpoints)
- `finance/tests/test_ocr.py`
- `requirements.txt` (pytesseract, Pillow)

**OCR Parser Patterns:**
- Amount: `$X.XX`, `X.XX USD`, `Total: X.XX`
- Date: `MM/DD/YYYY`, `YYYY-MM-DD`, `Month DD, YYYY`
- Vendor: First line of text, or after "Merchant:"

**Acceptance Criteria:**
- [ ] Tesseract extracts text from images
- [ ] Parser identifies amount with 80%+ accuracy on clear receipts
- [ ] Parser identifies date with 80%+ accuracy
- [ ] Parser suggests vendor name
- [ ] Confidence score reflects extraction quality
- [ ] All tests pass

---

### Phase 6: Transaction Entry — Manual Entry

**Objective:** Build the transaction entry form with receipt requirement.

**Deliverables:**
1. Transaction create view
2. Transaction edit view
3. Transaction detail view
4. Transaction list view (with filters)
5. Form validation (receipt required for expenses)
6. Vendor auto-suggest (AJAX)
7. Category filtering by transaction type
8. Tests for all views

**Files to Create/Update:**
- `finance/views.py`
- `finance/forms.py`
- `finance/templates/finance/transaction_form.html`
- `finance/templates/finance/transaction_list.html`
- `finance/templates/finance/transaction_detail.html`
- `finance/tests/test_transaction_views.py`

**Acceptance Criteria:**
- [ ] Transactions can be created with all fields
- [ ] Expenses require receipt attachment
- [ ] Categories filter based on transaction type
- [ ] Vendor suggestions appear after 2 characters
- [ ] Transaction list filters work correctly
- [ ] All tests pass

---

### Phase 7: Transaction Entry — CSV Import

**Objective:** Implement CSV import from Amex statements.

**Deliverables:**
1. CSV upload view
2. CSV parsing with validation
3. Preview screen showing mapped data
4. Duplicate detection
5. Batch transaction creation
6. Import log with success/error counts
7. Tests for import functionality

**Files to Create/Update:**
- `finance/importers.py`
- `finance/views.py` (import views)
- `finance/templates/finance/csv_import.html`
- `finance/templates/finance/csv_preview.html`
- `finance/templates/finance/csv_results.html`
- `finance/tests/test_csv_import.py`

**Amex CSV Format:**
```csv
Date,Description,Amount,Extended Details,Appears On Your Statement As,Address,City/State,Zip Code,Country,Reference,Category
```

**Acceptance Criteria:**
- [ ] CSV uploads and parses correctly
- [ ] Preview shows all rows with category mapping
- [ ] User can adjust categories before import
- [ ] Duplicates flagged for review
- [ ] Import creates transactions correctly
- [ ] Import log shows results
- [ ] All tests pass

---

### Phase 8: Account Management

**Objective:** Build account CRUD and balance calculations.

**Deliverables:**
1. Account list view
2. Account create view
3. Account edit view
4. Account detail view with transaction history
5. Balance calculation methods
6. Initial account setup (seed 3 accounts)
7. Tests for account functionality

**Files to Create/Update:**
- `finance/views.py` (account views)
- `finance/templates/finance/account_list.html`
- `finance/templates/finance/account_form.html`
- `finance/templates/finance/account_detail.html`
- `finance/tests/test_accounts.py`

**Initial Accounts to Seed:**
1. Amex Business Checking — $1,000 opening balance
2. Amex Blue Business Cash — $0 opening balance
3. Personal Amex (backup) — $0 opening balance, `is_personal=True`

**Acceptance Criteria:**
- [ ] Accounts can be created, edited, viewed
- [ ] Balance calculations are accurate
- [ ] Account detail shows transaction history
- [ ] Initial accounts seeded via data migration
- [ ] All tests pass

---

### Phase 9: Category Management

**Objective:** Build category CRUD with protection for system categories.

**Deliverables:**
1. Category list view
2. Category create view
3. Category edit view
4. Delete protection for system categories
5. Display order management
6. Tests for category functionality

**Files to Create/Update:**
- `finance/views.py` (category views)
- `finance/templates/finance/category_list.html`
- `finance/templates/finance/category_form.html`
- `finance/tests/test_categories.py`

**Acceptance Criteria:**
- [ ] Categories can be created, edited
- [ ] System categories cannot be deleted
- [ ] Display order affects list ordering
- [ ] All tests pass

---

### Phase 10: Dashboard & Reporting

**Objective:** Build the main dashboard and reports.

**Deliverables:**
1. Dashboard view with:
   - Account balances
   - Net cash position
   - Month-to-date summary
   - Quarter-to-date net profit
   - Active tax alerts
   - Recent transactions
2. Category spending report
3. Income statement (P&L) report
4. Chart.js integration for visualizations
5. Tests for dashboard calculations

**Files to Create/Update:**
- `finance/views.py` (dashboard, reports)
- `finance/templates/finance/dashboard.html`
- `finance/templates/finance/reports/spending.html`
- `finance/templates/finance/reports/income_statement.html`
- `finance/static/finance/js/charts.js`
- `finance/tests/test_dashboard.py`
- `finance/tests/test_reports.py`

**Acceptance Criteria:**
- [ ] Dashboard displays accurate balances
- [ ] MTD and QTD calculations correct
- [ ] Tax alerts display prominently
- [ ] Charts render correctly
- [ ] Reports filterable by date range
- [ ] All tests pass

---

### Phase 11: Recurring Transactions UI

**Objective:** Build UI for managing recurring transactions.

**Deliverables:**
1. Recurring transaction list view
2. Recurring transaction create view
3. Recurring transaction edit view
4. Toggle active/inactive
5. Manual generation trigger
6. Tests for recurring UI

**Files to Create/Update:**
- `finance/views.py` (recurring views)
- `finance/templates/finance/recurring_list.html`
- `finance/templates/finance/recurring_form.html`
- `finance/tests/test_recurring_views.py`

**Acceptance Criteria:**
- [ ] Recurring templates can be created, edited
- [ ] Active toggle works
- [ ] Manual generation creates transaction
- [ ] All tests pass

---

### Phase 12: Tax Alerts UI

**Objective:** Build UI for viewing and acknowledging tax alerts.

**Deliverables:**
1. Tax alert list view
2. Alert detail view
3. Acknowledge action
4. Alert calculation trigger (manual)
5. Tests for alert UI

**Files to Create/Update:**
- `finance/views.py` (alert views)
- `finance/templates/finance/alert_list.html`
- `finance/templates/finance/alert_detail.html`
- `finance/tests/test_alert_views.py`

**Acceptance Criteria:**
- [ ] Alerts display with status
- [ ] Acknowledge marks alert as reviewed
- [ ] Manual calculation works
- [ ] All tests pass

---

### Phase 13: Audit Log & Security

**Objective:** Build audit log viewer and implement security controls.

**Deliverables:**
1. Audit log list view (admin only)
2. Audit log filtering
3. Read-only user support (future accountant)
4. Permission checks on all views
5. Tests for security

**Files to Create/Update:**
- `finance/views.py` (audit views)
- `finance/templates/finance/audit_log.html`
- `finance/decorators.py` (permission checks)
- `finance/tests/test_security.py`

**Acceptance Criteria:**
- [ ] Audit log viewable by admin only
- [ ] Filters work correctly
- [ ] Read-only users blocked from create/edit/delete
- [ ] All permission checks enforced
- [ ] All tests pass

---

### Phase 14: Export & Polish

**Objective:** Add export functionality and polish the UI.

**Deliverables:**
1. Transaction export to CSV
2. Report export to CSV
3. Navigation menu integration
4. Responsive design checks
5. Error handling and user feedback
6. Final test coverage review
7. Documentation

**Files to Create/Update:**
- `finance/views.py` (export views)
- `finance/templates/finance/base.html`
- `finance/templates/finance/includes/nav.html`
- `finance/tests/test_exports.py`
- `docs/finance_user_guide.md`

**Acceptance Criteria:**
- [ ] CSV exports include all relevant data
- [ ] Navigation intuitive
- [ ] Mobile-responsive
- [ ] Error messages helpful
- [ ] All tests pass
- [ ] Test coverage > 90%

---

## Appendix A: Environment Variables

Add to `.env`:

```bash
# Cloudinary (same as WLJ)
CLOUDINARY_CLOUD_NAME=your_cloud_name
CLOUDINARY_API_KEY=your_api_key
CLOUDINARY_API_SECRET=your_api_secret

# Finance-specific
FINANCE_TAX_ALERT_THRESHOLD=1000
FINANCE_RECEIPT_MAX_SIZE_MB=10
```

---

## Appendix B: Dependencies to Add

Add to `requirements.txt`:

```
pytesseract>=0.3.10
Pillow>=10.0.0
cloudinary>=1.36.0
```

System dependency (for OCR):
```bash
# Ubuntu/Debian
apt-get install tesseract-ocr

# macOS
brew install tesseract

# Railway (add to nixpacks.toml or Dockerfile)
```

---

## Appendix C: Cloudinary Folder Setup

Configure Cloudinary to use a subfolder for Beacon Innovations:

```python
# settings.py
CLOUDINARY_STORAGE = {
    'CLOUD_NAME': os.environ.get('CLOUDINARY_CLOUD_NAME'),
    'API_KEY': os.environ.get('CLOUDINARY_API_KEY'),
    'API_SECRET': os.environ.get('CLOUDINARY_API_SECRET'),
}

# Upload preset for receipts
FINANCE_CLOUDINARY_FOLDER = 'beacon-innovations/receipts'
```

---

*End of Design Specification*
