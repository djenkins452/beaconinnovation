# Beacon Innovation Finance Tracker - User Guide

## Quick Summary

The Beacon Finance Tracker is a complete financial management system for your business. It helps you:

- **Track all money** - Income, expenses, transfers, and owner's draws across multiple accounts
- **Manage receipts** - Upload and attach receipts to transactions with OCR text extraction
- **Import statements** - Bulk import transactions from Amex CSV statements
- **Automate recurring bills** - Set up monthly subscriptions that auto-generate transactions
- **Monitor tax obligations** - Get alerts when quarterly profits exceed $1,000
- **Generate reports** - View spending breakdowns, income statements, and export to CSV
- **Maintain audit trail** - Every change is logged for accountability

---

## Getting Started

### Accessing the System

Navigate to `https://beacon-innovation.com/finance/login/` and sign in with your credentials.

After login, you'll see the main dashboard with:
- Account balances at a glance
- Recent transactions
- Spending breakdown chart
- Quick action buttons

### Navigation Menu

The top navigation bar provides access to all features:

| Section | Purpose |
|---------|---------|
| **Dashboard** | Overview of finances, charts, recent activity |
| **Transactions** | View, create, edit, delete transactions |
| **Accounts** | Manage bank accounts and credit cards |
| **Categories** | Organize income and expenses by type |
| **Recurring** | Set up automatic recurring transactions |
| **Imports** | Import transactions from CSV files |
| **Reports** | Spending reports and income statements |
| **Tax Alerts** | Monitor quarterly tax obligations |
| **Audit Log** | View history of all changes |

---

## Core Features

### 1. Accounts

**Location:** Dashboard → Accounts

Accounts represent your bank accounts and credit cards. The system supports:

| Account Type | Balance Calculation |
|--------------|---------------------|
| **Checking** | Opening balance + income - expenses - draws - transfers out + transfers in |
| **Savings** | Same as checking |
| **Credit Card** | Opening balance + expenses - payments |

**To create an account:**
1. Click "Accounts" in the navigation
2. Click "+ New Account"
3. Fill in the details:
   - **Name** - e.g., "Business Checking"
   - **Type** - Checking, Savings, or Credit Card
   - **Institution** - Bank name
   - **Last Four** - Last 4 digits of account number (optional, for identification)
   - **Opening Balance** - Starting balance
   - **Is Personal** - Check if this is a personal account (for tracking purposes)

**Tips:**
- Mark accounts as inactive instead of deleting them to preserve transaction history
- Use the "Last Four" field to distinguish between multiple accounts at the same bank

---

### 2. Categories

**Location:** Dashboard → Categories

Categories help organize your transactions. The system comes with pre-configured categories:

**Expense Categories (10 default):**
- Office Supplies
- Software & Subscriptions
- Professional Services
- Marketing & Advertising
- Travel & Transportation
- Meals & Entertainment
- Utilities & Internet
- Insurance
- Bank Fees & Interest
- Miscellaneous

**Income Categories (5 default):**
- Service Revenue
- Product Sales
- Interest Income
- Refunds
- Other Income

**To create a custom category:**
1. Click "Categories" in navigation
2. Click "+ New Category"
3. Enter name, select type (Income or Expense), add description
4. Set display order (lower numbers appear first)

**Notes:**
- System categories (marked with a badge) cannot be deleted
- Category names must be unique within their type
- Deactivate categories instead of deleting to preserve historical data

---

### 3. Transactions

**Location:** Dashboard → Transactions

Transactions are the core of the system. There are four types:

| Type | Description | Requirements |
|------|-------------|--------------|
| **Income** | Money received | Account + Income Category |
| **Expense** | Money spent | Account + Expense Category |
| **Transfer** | Move money between accounts | Source Account + Destination Account |
| **Owner's Draw** | Personal withdrawal | Checking Account only |

**To create a transaction:**
1. Click "Transactions" → "+ New Transaction"
2. Select transaction type
3. Fill in required fields:
   - **Account** - Which account this affects
   - **Amount** - Transaction amount (positive number)
   - **Date** - When the transaction occurred (cannot be future)
   - **Description** - Brief description
   - **Category** - Required for income/expense
   - **Vendor** - Who you paid or received from (optional)
   - **Reference Number** - Check number, invoice number, etc. (optional)

**For Transfers:**
- Select the source account and destination account
- The system validates you have sufficient balance
- Both accounts are updated automatically

**For Owner's Draws:**
- Must be from a checking account
- System validates sufficient balance
- These reduce your retained earnings

**Filtering Transactions:**
Use the filter bar to narrow down transactions by:
- Account
- Transaction type
- Category
- Date range
- Search text (searches description and vendor)

**Exporting:**
Click "Export CSV" to download filtered transactions as a spreadsheet.

---

### 4. Receipts

**Location:** Transaction Detail → Receipts section

Attach receipts to any transaction for documentation.

**Supported file types:** PDF, JPG, JPEG, PNG
**Maximum file size:** 10MB

**To upload a receipt:**
1. Open a transaction (click on it in the list)
2. Scroll to the Receipts section
3. Click "Upload Receipt" or drag and drop a file
4. The receipt is attached and stored securely

**OCR Feature:**
If Tesseract OCR is installed, the system can extract text from receipt images. This helps with:
- Searching for receipts by content
- Verifying transaction details

**Receipt Actions:**
- **View** - Open the receipt in a new window
- **Download** - Save to your computer
- **Delete** - Remove the receipt (cannot be undone)

**Security:**
Only the person who created the transaction or uploaded the receipt can access it. Administrators can access all receipts.

---

### 5. Recurring Transactions

**Location:** Dashboard → Recurring

Set up transactions that repeat automatically, perfect for:
- Monthly subscriptions (GitHub, Adobe, etc.)
- Regular bills (internet, phone)
- Recurring client invoices

**To create a recurring transaction:**
1. Click "Recurring" → "+ New Recurring"
2. Fill in the template:
   - **Account** - Which account to charge
   - **Category** - Expense category (only expense categories are shown)
   - **Amount** - Monthly amount
   - **Description** - e.g., "Monthly GitHub subscription"
   - **Vendor** - e.g., "GitHub"
   - **Frequency** - Currently supports monthly
   - **Day of Month** - Which day the transaction occurs (1-31)
   - **Start Date** - When to begin generating transactions
   - **End Date** - Optional end date

**How it works:**
- The system calculates when the next transaction is due
- Run the command `python manage.py generate_recurring` daily (via cron)
- Transactions are created automatically when due
- The "next due" date advances to the following month

**Managing Recurring:**
- **Edit** - Change details for future transactions
- **Deactivate** - Stop generating new transactions
- **Delete** - Remove the template entirely

---

### 6. CSV Import (Amex Statements)

**Location:** Dashboard → Imports

Import transactions in bulk from American Express CSV statements.

**To import transactions:**
1. Download your statement from Amex as CSV
2. Click "Imports" → "New Import"
3. Select the CSV file
4. Choose the default account for imported transactions
5. Review the preview
6. Click "Import" to create transactions

**CSV Requirements:**
- Must have columns: Date, Amount, Description (or "Appears On Your Statement As")
- Maximum 10,000 rows per file
- UTF-8 encoding

**After Import:**
- Transactions are created as expenses
- Review and categorize each transaction
- Attach receipts as needed
- System tracks import history for reference

---

### 7. Reports

**Location:** Dashboard → Reports

#### Spending Report
View expenses broken down by category for any time period.

**Periods available:**
- Month to Date (MTD)
- Quarter to Date (QTD)
- Year to Date (YTD)
- Last Month
- Last Quarter
- Custom date range

**Features:**
- Pie chart visualization
- Category-by-category breakdown
- Percentage of total spending
- Export to CSV

#### Income Statement (P&L)
Complete profit & loss report showing:

| Section | Contents |
|---------|----------|
| **Income** | All income by category |
| **Expenses** | All expenses by category |
| **Net Operating Profit** | Income - Expenses |
| **Owner's Draws** | Personal withdrawals |
| **Retained Earnings** | Net Profit - Draws |

**Export:** Click "Export CSV" to download for your accountant or records.

---

### 8. Tax Alerts

**Location:** Dashboard → Tax Alerts

The system monitors quarterly profits and alerts you when estimated tax payments may be due.

**How it works:**
- Calculates net profit (income - expenses) for each quarter
- When profit exceeds the threshold ($1,000 default), an alert is triggered
- Alerts appear on the dashboard and in the Tax Alerts section

**Alert Status:**
- **Triggered** - Profit exceeded threshold, action needed
- **Acknowledged** - You've reviewed and taken action
- **Not Triggered** - Below threshold for the quarter

**To acknowledge an alert:**
1. Click on the alert
2. Add notes about action taken (e.g., "Paid $500 estimated tax")
3. Click "Acknowledge"

**Quarters:**
- Q1: January - March
- Q2: April - June
- Q3: July - September
- Q4: October - December

---

### 9. Audit Log

**Location:** Dashboard → Audit Log

Every change in the system is logged for accountability and troubleshooting.

**Logged actions:**
- **Create** - New records created
- **Update** - Changes to existing records
- **Delete** - Records removed

**Log details include:**
- Who made the change
- When it happened
- What changed (before/after values)
- Which record was affected

**Filtering:**
- By action type (create, update, delete)
- By model (Transaction, Account, Category, etc.)
- By user
- By date range

**Notes:**
- Audit logs cannot be modified or deleted
- Use this to track down issues or verify changes

---

## Quick Reference

### Common Tasks

| Task | Steps |
|------|-------|
| Record an expense | Transactions → + New → Select "Expense" → Fill details |
| Record income | Transactions → + New → Select "Income" → Fill details |
| Transfer between accounts | Transactions → + New → Select "Transfer" → Choose accounts |
| Take owner's draw | Transactions → + New → Select "Owner's Draw" → From checking |
| Upload receipt | Open transaction → Receipts section → Upload |
| View spending | Reports → Spending Report → Select period |
| Check tax status | Tax Alerts → View current quarter |
| Export data | Any list page → Export CSV button |

### URL Quick Access

| Page | URL |
|------|-----|
| Login | `/finance/login/` |
| Dashboard | `/finance/` |
| Transactions | `/finance/transactions/` |
| Accounts | `/finance/accounts/` |
| Categories | `/finance/categories/` |
| Recurring | `/finance/recurring/` |
| Imports | `/finance/imports/` |
| Spending Report | `/finance/reports/spending/` |
| Income Statement | `/finance/reports/income-statement/` |
| Tax Alerts | `/finance/alerts/` |
| Audit Log | `/finance/audit-logs/` |

---

## Best Practices

### Daily
- Record transactions as they occur
- Attach receipts immediately

### Weekly
- Review uncategorized imported transactions
- Verify account balances match bank statements

### Monthly
- Review spending report
- Ensure recurring transactions generated correctly
- Export data for backup

### Quarterly
- Check tax alerts
- Review income statement
- Make estimated tax payments if needed
- Archive/export quarterly reports

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Can't delete category | Check if transactions use it; deactivate instead |
| Transfer fails | Verify sufficient balance in source account |
| Receipt won't upload | Check file size (<10MB) and type (PDF, JPG, PNG) |
| Import fails | Verify CSV has Date, Amount, Description columns |
| Balance seems wrong | Check transaction types and account assignments |

---

## Support

For issues or questions, contact your system administrator.

---

*Beacon Innovations LLC - Finance Tracker User Guide*
*Last Updated: January 2026*
