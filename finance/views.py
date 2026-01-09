"""
Views for the finance app.
"""
import logging
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.http import JsonResponse, FileResponse, Http404
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST, require_GET

from .models import Receipt, Transaction, Category, Account, CSVImport, TaxAlert, RecurringTransaction
from .forms import validate_receipt_file, TransactionForm, TransactionFilterForm, AccountForm, CategoryForm, RecurringTransactionForm
from .ocr import process_receipt_image, is_tesseract_available, OCRError
from .importers import AmexCSVParser, CSVImporter, validate_csv_file

logger = logging.getLogger(__name__)


# =============================================================================
# Dashboard & Reporting Views (Phase 10)
# =============================================================================

def _get_date_range_for_period(period):
    """Get start and end dates for a reporting period."""
    today = date.today()

    if period == 'mtd':
        # Month to date
        start_date = today.replace(day=1)
        end_date = today
    elif period == 'qtd':
        # Quarter to date
        quarter = (today.month - 1) // 3
        start_month = quarter * 3 + 1
        start_date = today.replace(month=start_month, day=1)
        end_date = today
    elif period == 'ytd':
        # Year to date
        start_date = today.replace(month=1, day=1)
        end_date = today
    elif period == 'last_month':
        # Last full month
        first_of_month = today.replace(day=1)
        end_date = first_of_month - timedelta(days=1)
        start_date = end_date.replace(day=1)
    elif period == 'last_quarter':
        # Last full quarter
        quarter = (today.month - 1) // 3
        if quarter == 0:
            # Q1 -> last year Q4
            start_date = date(today.year - 1, 10, 1)
            end_date = date(today.year - 1, 12, 31)
        else:
            start_month = (quarter - 1) * 3 + 1
            end_month = quarter * 3
            start_date = today.replace(month=start_month, day=1)
            # End of quarter
            if end_month == 3:
                end_date = date(today.year, 3, 31)
            elif end_month == 6:
                end_date = date(today.year, 6, 30)
            elif end_month == 9:
                end_date = date(today.year, 9, 30)
            else:
                end_date = date(today.year, 12, 31)
    else:
        # Default to MTD
        start_date = today.replace(day=1)
        end_date = today

    return start_date, end_date


def _calculate_period_summary(start_date, end_date):
    """Calculate income, expenses, and net profit for a period."""
    transactions = Transaction.objects.filter(
        transaction_date__gte=start_date,
        transaction_date__lte=end_date
    )

    income = transactions.filter(
        transaction_type='income'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    expenses = transactions.filter(
        transaction_type='expense'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    owners_draw = transactions.filter(
        transaction_type='owners_draw'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    net_profit = income - expenses

    return {
        'income': income,
        'expenses': expenses,
        'owners_draw': owners_draw,
        'net_profit': net_profit,
        'start_date': start_date,
        'end_date': end_date,
    }


def _get_spending_by_category(start_date, end_date):
    """Get spending breakdown by category for a period."""
    spending = Transaction.objects.filter(
        transaction_type='expense',
        transaction_date__gte=start_date,
        transaction_date__lte=end_date,
        category__isnull=False
    ).values(
        'category__id',
        'category__name'
    ).annotate(
        total=Sum('amount')
    ).order_by('-total')

    return list(spending)


def _get_income_by_category(start_date, end_date):
    """Get income breakdown by category for a period."""
    income = Transaction.objects.filter(
        transaction_type='income',
        transaction_date__gte=start_date,
        transaction_date__lte=end_date,
        category__isnull=False
    ).values(
        'category__id',
        'category__name'
    ).annotate(
        total=Sum('amount')
    ).order_by('-total')

    return list(income)


@login_required
def dashboard(request):
    """
    Main financial dashboard.

    GET /finance/

    Shows:
    - Account balances and net position
    - Month-to-date summary
    - Quarter-to-date net profit
    - Active tax alerts
    - Recent transactions
    - Spending by category (MTD)
    """
    today = date.today()

    # Account balances
    accounts = Account.objects.filter(is_active=True)
    total_checking = sum(
        a.current_balance for a in accounts if a.account_type in ('checking', 'savings')
    )
    total_credit = sum(
        a.current_balance for a in accounts if a.account_type == 'credit_card'
    )
    net_position = total_checking - total_credit

    # Month-to-date summary
    mtd_start, mtd_end = _get_date_range_for_period('mtd')
    mtd_summary = _calculate_period_summary(mtd_start, mtd_end)

    # Quarter-to-date summary
    qtd_start, qtd_end = _get_date_range_for_period('qtd')
    qtd_summary = _calculate_period_summary(qtd_start, qtd_end)

    # Current quarter info
    current_quarter = (today.month - 1) // 3 + 1

    # Active tax alerts (unacknowledged)
    tax_alerts = TaxAlert.objects.filter(
        alert_triggered=True,
        acknowledged=False
    ).order_by('-year', '-quarter')[:5]

    # Recent transactions
    recent_transactions = Transaction.objects.select_related(
        'account', 'category'
    ).order_by('-transaction_date', '-created_at')[:10]

    # Spending by category (MTD) for chart
    mtd_spending = _get_spending_by_category(mtd_start, mtd_end)

    # Top 5 spending categories for display
    top_spending = mtd_spending[:5]

    return render(request, 'finance/dashboard.html', {
        'accounts': accounts,
        'total_checking': total_checking,
        'total_credit': total_credit,
        'net_position': net_position,
        'mtd_summary': mtd_summary,
        'qtd_summary': qtd_summary,
        'current_quarter': current_quarter,
        'current_year': today.year,
        'tax_alerts': tax_alerts,
        'recent_transactions': recent_transactions,
        'mtd_spending': mtd_spending,
        'top_spending': top_spending,
    })


@login_required
def spending_report(request):
    """
    Category spending report.

    GET /finance/reports/spending/

    Query params:
    - period: mtd, qtd, ytd, last_month, last_quarter (default: mtd)
    - start_date: YYYY-MM-DD (custom date range)
    - end_date: YYYY-MM-DD (custom date range)
    """
    # Get date range
    period = request.GET.get('period', 'mtd')
    custom_start = request.GET.get('start_date')
    custom_end = request.GET.get('end_date')

    if custom_start and custom_end:
        try:
            start_date = date.fromisoformat(custom_start)
            end_date = date.fromisoformat(custom_end)
            period = 'custom'
        except ValueError:
            start_date, end_date = _get_date_range_for_period(period)
    else:
        start_date, end_date = _get_date_range_for_period(period)

    # Get spending by category
    spending = _get_spending_by_category(start_date, end_date)
    total_spending = sum(s['total'] for s in spending)

    # Add percentage to each category
    for item in spending:
        if total_spending > 0:
            item['percentage'] = (item['total'] / total_spending * 100)
        else:
            item['percentage'] = Decimal('0')

    # Get period summary
    summary = _calculate_period_summary(start_date, end_date)

    return render(request, 'finance/reports/spending.html', {
        'spending': spending,
        'total_spending': total_spending,
        'summary': summary,
        'period': period,
        'start_date': start_date,
        'end_date': end_date,
    })


@login_required
def income_statement(request):
    """
    Income statement (P&L) report.

    GET /finance/reports/income-statement/

    Query params:
    - period: mtd, qtd, ytd, last_month, last_quarter (default: mtd)
    - start_date: YYYY-MM-DD (custom date range)
    - end_date: YYYY-MM-DD (custom date range)
    """
    # Get date range
    period = request.GET.get('period', 'mtd')
    custom_start = request.GET.get('start_date')
    custom_end = request.GET.get('end_date')

    if custom_start and custom_end:
        try:
            start_date = date.fromisoformat(custom_start)
            end_date = date.fromisoformat(custom_end)
            period = 'custom'
        except ValueError:
            start_date, end_date = _get_date_range_for_period(period)
    else:
        start_date, end_date = _get_date_range_for_period(period)

    # Income by category
    income_by_category = _get_income_by_category(start_date, end_date)
    total_income = sum(i['total'] for i in income_by_category)

    # Expenses by category
    expenses_by_category = _get_spending_by_category(start_date, end_date)
    total_expenses = sum(e['total'] for e in expenses_by_category)

    # Net profit
    net_profit = total_income - total_expenses

    # Owner's draws for the period
    owners_draw = Transaction.objects.filter(
        transaction_type='owners_draw',
        transaction_date__gte=start_date,
        transaction_date__lte=end_date
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    # Retained earnings (net profit - owner's draw)
    retained_earnings = net_profit - owners_draw

    return render(request, 'finance/reports/income_statement.html', {
        'income_by_category': income_by_category,
        'total_income': total_income,
        'expenses_by_category': expenses_by_category,
        'total_expenses': total_expenses,
        'net_profit': net_profit,
        'owners_draw': owners_draw,
        'retained_earnings': retained_earnings,
        'period': period,
        'start_date': start_date,
        'end_date': end_date,
    })


@login_required
def dashboard_data_api(request):
    """
    API endpoint for dashboard chart data.

    GET /finance/api/dashboard/data/

    Query params:
    - chart: spending_by_category, income_vs_expense, monthly_trend
    - period: mtd, qtd, ytd (default: mtd)
    """
    chart_type = request.GET.get('chart', 'spending_by_category')
    period = request.GET.get('period', 'mtd')

    start_date, end_date = _get_date_range_for_period(period)

    if chart_type == 'spending_by_category':
        spending = _get_spending_by_category(start_date, end_date)
        return JsonResponse({
            'labels': [s['category__name'] for s in spending],
            'data': [float(s['total']) for s in spending],
        })

    elif chart_type == 'income_vs_expense':
        summary = _calculate_period_summary(start_date, end_date)
        return JsonResponse({
            'labels': ['Income', 'Expenses'],
            'data': [float(summary['income']), float(summary['expenses'])],
        })

    elif chart_type == 'monthly_trend':
        # Get last 6 months of data
        today = date.today()
        months = []
        income_data = []
        expense_data = []

        for i in range(5, -1, -1):
            # Calculate month start/end
            month_date = today.replace(day=1) - timedelta(days=i * 30)
            month_start = month_date.replace(day=1)
            if month_start.month == 12:
                month_end = month_start.replace(year=month_start.year + 1, month=1, day=1) - timedelta(days=1)
            else:
                month_end = month_start.replace(month=month_start.month + 1, day=1) - timedelta(days=1)

            summary = _calculate_period_summary(month_start, month_end)
            months.append(month_start.strftime('%b %Y'))
            income_data.append(float(summary['income']))
            expense_data.append(float(summary['expenses']))

        return JsonResponse({
            'labels': months,
            'income': income_data,
            'expenses': expense_data,
        })

    return JsonResponse({'error': 'Invalid chart type'}, status=400)


@login_required
@require_POST
def process_receipt_ocr(request, receipt_id):
    """
    Process OCR on an uploaded receipt.

    POST /finance/receipts/<id>/ocr/

    Returns JSON with:
    - success: bool
    - data: {vendor, amount, date, confidence, raw_text} on success
    - error: string on failure
    """
    receipt = get_object_or_404(Receipt, pk=receipt_id)

    # Check if Tesseract is available
    if not is_tesseract_available():
        return JsonResponse({
            'success': False,
            'error': 'OCR is not available. Tesseract is not installed on the server.'
        }, status=503)

    # Only process image files (not PDFs yet)
    if receipt.file_type not in ('jpg', 'png'):
        return JsonResponse({
            'success': False,
            'error': f'OCR is only supported for JPG and PNG files. Got: {receipt.file_type}'
        }, status=400)

    try:
        # Process the receipt image
        receipt.file.seek(0)  # Reset file pointer
        result = process_receipt_image(receipt.file)

        # Update receipt with OCR results
        receipt.ocr_processed = True
        receipt.ocr_raw_text = result['raw_text'] or ''
        receipt.ocr_vendor = result['vendor'] or ''
        receipt.ocr_amount = result['amount']
        receipt.ocr_date = result['date']
        receipt.ocr_confidence = result['confidence']
        receipt.save()

        # Format response
        response_data = {
            'vendor': result['vendor'],
            'amount': str(result['amount']) if result['amount'] else None,
            'date': result['date'].isoformat() if result['date'] else None,
            'confidence': float(result['confidence']) if result['confidence'] else 0.0,
            'raw_text': result['raw_text'],
        }

        return JsonResponse({
            'success': True,
            'data': response_data
        })

    except OCRError as e:
        logger.error(f"OCR processing failed for receipt {receipt_id}: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

    except Exception as e:
        logger.exception(f"Unexpected error processing receipt {receipt_id}")
        return JsonResponse({
            'success': False,
            'error': 'An unexpected error occurred during OCR processing.'
        }, status=500)


@login_required
@require_POST
def rerun_receipt_ocr(request, receipt_id):
    """
    Re-run OCR on a previously processed receipt.

    POST /finance/receipts/<id>/ocr/rerun/

    This allows re-processing if OCR results were poor or if
    the OCR engine has been updated.
    """
    receipt = get_object_or_404(Receipt, pk=receipt_id)

    # Clear existing OCR data
    receipt.ocr_processed = False
    receipt.ocr_raw_text = ''
    receipt.ocr_vendor = ''
    receipt.ocr_amount = None
    receipt.ocr_date = None
    receipt.ocr_confidence = None
    receipt.save()

    # Re-process
    return process_receipt_ocr(request, receipt_id)


@login_required
@require_GET
def get_receipt_ocr_status(request, receipt_id):
    """
    Get the OCR status and results for a receipt.

    GET /finance/receipts/<id>/ocr/status/

    Returns JSON with OCR data if processed, or status if not.
    """
    receipt = get_object_or_404(Receipt, pk=receipt_id)

    if receipt.ocr_processed:
        return JsonResponse({
            'processed': True,
            'data': {
                'vendor': receipt.ocr_vendor or None,
                'amount': str(receipt.ocr_amount) if receipt.ocr_amount else None,
                'date': receipt.ocr_date.isoformat() if receipt.ocr_date else None,
                'confidence': float(receipt.ocr_confidence) if receipt.ocr_confidence else 0.0,
                'raw_text': receipt.ocr_raw_text,
            }
        })
    else:
        return JsonResponse({
            'processed': False,
            'data': None
        })


@login_required
@require_GET
def check_tesseract_status(request):
    """
    Check if Tesseract OCR is available.

    GET /finance/api/ocr/status/

    Returns JSON with availability status.
    """
    available = is_tesseract_available()
    return JsonResponse({
        'available': available,
        'message': 'Tesseract OCR is available' if available else 'Tesseract OCR is not installed'
    })


# =============================================================================
# Receipt Upload Views (Phase 4)
# =============================================================================

@login_required
@require_POST
def upload_receipt(request, transaction_id):
    """
    Upload a receipt file for a transaction.

    POST /finance/transactions/<id>/receipts/upload/

    Expects multipart form data with 'file' field.

    Returns JSON with:
    - success: bool
    - receipt: {id, filename, file_type, file_size, url} on success
    - error: string on failure
    """
    transaction = get_object_or_404(Transaction, pk=transaction_id)

    # Check if file was uploaded
    if 'file' not in request.FILES:
        return JsonResponse({
            'success': False,
            'error': 'No file was uploaded.'
        }, status=400)

    uploaded_file = request.FILES['file']

    # Validate the file
    validation = validate_receipt_file(uploaded_file)
    if not validation['valid']:
        return JsonResponse({
            'success': False,
            'error': validation['error']
        }, status=400)

    try:
        # Create the receipt record
        receipt = Receipt.objects.create(
            transaction=transaction,
            file=uploaded_file,
            original_filename=validation['original_filename'],
            file_type=validation['file_type'],
            file_size=validation['file_size'],
            uploaded_by=request.user
        )

        return JsonResponse({
            'success': True,
            'receipt': {
                'id': str(receipt.id),
                'filename': receipt.original_filename,
                'file_type': receipt.file_type,
                'file_size': receipt.file_size,
                'url': receipt.file.url,
            }
        }, status=201)

    except Exception as e:
        logger.exception(f"Failed to upload receipt for transaction {transaction_id}")
        return JsonResponse({
            'success': False,
            'error': 'Failed to save receipt. Please try again.'
        }, status=500)


@login_required
@require_GET
def view_receipt(request, receipt_id):
    """
    View a receipt file in the browser.

    GET /finance/receipts/<id>/view/

    Returns the file with appropriate content type for browser display.
    """
    receipt = get_object_or_404(Receipt, pk=receipt_id)

    try:
        # Determine content type
        content_type_map = {
            'pdf': 'application/pdf',
            'jpg': 'image/jpeg',
            'png': 'image/png',
        }
        content_type = content_type_map.get(receipt.file_type, 'application/octet-stream')

        # Return file for viewing (inline)
        response = FileResponse(
            receipt.file.open('rb'),
            content_type=content_type
        )
        response['Content-Disposition'] = f'inline; filename="{receipt.original_filename}"'
        return response

    except FileNotFoundError:
        raise Http404("Receipt file not found")


@login_required
@require_GET
def download_receipt(request, receipt_id):
    """
    Download a receipt file.

    GET /finance/receipts/<id>/download/

    Returns the file as an attachment download.
    """
    receipt = get_object_or_404(Receipt, pk=receipt_id)

    try:
        # Determine content type
        content_type_map = {
            'pdf': 'application/pdf',
            'jpg': 'image/jpeg',
            'png': 'image/png',
        }
        content_type = content_type_map.get(receipt.file_type, 'application/octet-stream')

        # Return file for download (attachment)
        response = FileResponse(
            receipt.file.open('rb'),
            content_type=content_type
        )
        response['Content-Disposition'] = f'attachment; filename="{receipt.original_filename}"'
        return response

    except FileNotFoundError:
        raise Http404("Receipt file not found")


@login_required
@require_POST
def delete_receipt(request, receipt_id):
    """
    Delete a receipt.

    POST /finance/receipts/<id>/delete/

    Returns JSON with success status.
    """
    receipt = get_object_or_404(Receipt, pk=receipt_id)

    try:
        # Delete the file from storage
        if receipt.file:
            receipt.file.delete(save=False)

        # Delete the record
        receipt.delete()

        return JsonResponse({
            'success': True,
            'message': 'Receipt deleted successfully.'
        })

    except Exception as e:
        logger.exception(f"Failed to delete receipt {receipt_id}")
        return JsonResponse({
            'success': False,
            'error': 'Failed to delete receipt. Please try again.'
        }, status=500)


@login_required
@require_GET
def get_receipt_info(request, receipt_id):
    """
    Get information about a receipt.

    GET /finance/receipts/<id>/

    Returns JSON with receipt details.
    """
    receipt = get_object_or_404(Receipt, pk=receipt_id)

    return JsonResponse({
        'id': str(receipt.id),
        'transaction_id': str(receipt.transaction.id),
        'filename': receipt.original_filename,
        'file_type': receipt.file_type,
        'file_size': receipt.file_size,
        'url': receipt.file.url,
        'uploaded_at': receipt.uploaded_at.isoformat(),
        'uploaded_by': receipt.uploaded_by.username if receipt.uploaded_by else None,
        'ocr_processed': receipt.ocr_processed,
        'ocr_data': {
            'vendor': receipt.ocr_vendor or None,
            'amount': str(receipt.ocr_amount) if receipt.ocr_amount else None,
            'date': receipt.ocr_date.isoformat() if receipt.ocr_date else None,
            'confidence': float(receipt.ocr_confidence) if receipt.ocr_confidence else None,
        } if receipt.ocr_processed else None
    })


@login_required
@require_GET
def list_transaction_receipts(request, transaction_id):
    """
    List all receipts for a transaction.

    GET /finance/transactions/<id>/receipts/

    Returns JSON with list of receipts.
    """
    transaction = get_object_or_404(Transaction, pk=transaction_id)
    receipts = transaction.receipts.all()

    return JsonResponse({
        'transaction_id': str(transaction.id),
        'count': receipts.count(),
        'receipts': [
            {
                'id': str(r.id),
                'filename': r.original_filename,
                'file_type': r.file_type,
                'file_size': r.file_size,
                'url': r.file.url,
                'uploaded_at': r.uploaded_at.isoformat(),
                'ocr_processed': r.ocr_processed,
            }
            for r in receipts
        ]
    })


# =============================================================================
# Transaction Views (Phase 6)
# =============================================================================

@login_required
def transaction_list(request):
    """
    List all transactions with filtering and pagination.

    GET /finance/transactions/
    """
    form = TransactionFilterForm(request.GET)
    transactions = Transaction.objects.select_related('account', 'category').all()

    # Apply filters
    if form.is_valid():
        if form.cleaned_data.get('account'):
            transactions = transactions.filter(account=form.cleaned_data['account'])

        if form.cleaned_data.get('transaction_type'):
            transactions = transactions.filter(
                transaction_type=form.cleaned_data['transaction_type']
            )

        if form.cleaned_data.get('category'):
            transactions = transactions.filter(category=form.cleaned_data['category'])

        if form.cleaned_data.get('date_from'):
            transactions = transactions.filter(
                transaction_date__gte=form.cleaned_data['date_from']
            )

        if form.cleaned_data.get('date_to'):
            transactions = transactions.filter(
                transaction_date__lte=form.cleaned_data['date_to']
            )

        if form.cleaned_data.get('search'):
            search = form.cleaned_data['search']
            transactions = transactions.filter(
                Q(description__icontains=search) | Q(vendor__icontains=search)
            )

    # Pagination
    paginator = Paginator(transactions, 25)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    return render(request, 'finance/transaction_list.html', {
        'transactions': page_obj,
        'filter_form': form,
        'total_count': paginator.count,
    })


@login_required
def transaction_create(request):
    """
    Create a new transaction.

    GET/POST /finance/transactions/new/
    """
    if request.method == 'POST':
        form = TransactionForm(request.POST)
        if form.is_valid():
            transaction = form.save(commit=False)
            transaction.created_by = request.user
            transaction.save()
            messages.success(request, 'Transaction created successfully.')
            return redirect('finance:transaction_detail', transaction_id=transaction.id)
    else:
        form = TransactionForm()

    # Get categories for JavaScript filtering
    expense_categories = list(
        Category.objects.filter(is_active=True, category_type='expense')
        .values('id', 'name')
    )
    income_categories = list(
        Category.objects.filter(is_active=True, category_type='income')
        .values('id', 'name')
    )

    return render(request, 'finance/transaction_form.html', {
        'form': form,
        'title': 'New Transaction',
        'expense_categories': expense_categories,
        'income_categories': income_categories,
    })


@login_required
def transaction_edit(request, transaction_id):
    """
    Edit an existing transaction.

    GET/POST /finance/transactions/<id>/edit/
    """
    transaction = get_object_or_404(Transaction, pk=transaction_id)

    if request.method == 'POST':
        form = TransactionForm(request.POST, instance=transaction)
        if form.is_valid():
            form.save()
            messages.success(request, 'Transaction updated successfully.')
            return redirect('finance:transaction_detail', transaction_id=transaction.id)
    else:
        form = TransactionForm(instance=transaction)

    # Get categories for JavaScript filtering
    expense_categories = list(
        Category.objects.filter(is_active=True, category_type='expense')
        .values('id', 'name')
    )
    income_categories = list(
        Category.objects.filter(is_active=True, category_type='income')
        .values('id', 'name')
    )

    return render(request, 'finance/transaction_form.html', {
        'form': form,
        'transaction': transaction,
        'title': 'Edit Transaction',
        'expense_categories': expense_categories,
        'income_categories': income_categories,
    })


@login_required
def transaction_detail(request, transaction_id):
    """
    View transaction details.

    GET /finance/transactions/<id>/
    """
    transaction = get_object_or_404(
        Transaction.objects.select_related('account', 'category', 'transfer_to_account'),
        pk=transaction_id
    )
    receipts = transaction.receipts.all()

    return render(request, 'finance/transaction_detail.html', {
        'transaction': transaction,
        'receipts': receipts,
    })


@login_required
@require_POST
def transaction_delete(request, transaction_id):
    """
    Delete a transaction.

    POST /finance/transactions/<id>/delete/
    """
    transaction = get_object_or_404(Transaction, pk=transaction_id)

    # Delete associated receipts first
    for receipt in transaction.receipts.all():
        if receipt.file:
            receipt.file.delete(save=False)
        receipt.delete()

    transaction.delete()
    messages.success(request, 'Transaction deleted successfully.')
    return redirect('finance:transaction_list')


@login_required
@require_GET
def vendor_suggest(request):
    """
    Auto-suggest vendors based on input.

    GET /finance/api/vendor-suggest/?q=<query>

    Returns JSON list of matching vendor names.
    """
    query = request.GET.get('q', '').strip()

    if len(query) < 2:
        return JsonResponse({'vendors': []})

    # Get distinct vendors matching the query
    vendors = (
        Transaction.objects
        .filter(vendor__icontains=query)
        .exclude(vendor='')
        .values_list('vendor', flat=True)
        .distinct()
        .order_by('vendor')[:10]
    )

    return JsonResponse({'vendors': list(vendors)})


@login_required
@require_GET
def get_categories_by_type(request):
    """
    Get categories filtered by type.

    GET /finance/api/categories/?type=expense|income

    Returns JSON list of categories.
    """
    category_type = request.GET.get('type', '')

    if category_type not in ('expense', 'income'):
        return JsonResponse({'categories': []})

    categories = (
        Category.objects
        .filter(is_active=True, category_type=category_type)
        .values('id', 'name')
        .order_by('display_order', 'name')
    )

    return JsonResponse({'categories': list(categories)})


# =============================================================================
# CSV Import Views (Phase 7)
# =============================================================================

@login_required
def csv_import_upload(request):
    """
    Upload a CSV file for import.

    GET: Show upload form
    POST: Validate and store file, redirect to preview

    GET/POST /finance/import/
    """
    accounts = Account.objects.filter(is_active=True)

    if request.method == 'POST':
        # Get account
        account_id = request.POST.get('account')
        if not account_id:
            messages.error(request, 'Please select an account.')
            return render(request, 'finance/csv_import.html', {
                'accounts': accounts,
            })

        account = get_object_or_404(Account, pk=account_id)

        # Validate file
        if 'file' not in request.FILES:
            messages.error(request, 'Please select a CSV file to upload.')
            return render(request, 'finance/csv_import.html', {
                'accounts': accounts,
            })

        uploaded_file = request.FILES['file']
        validation = validate_csv_file(uploaded_file)

        if not validation['valid']:
            messages.error(request, validation['error'])
            return render(request, 'finance/csv_import.html', {
                'accounts': accounts,
            })

        # Create CSVImport record
        csv_import = CSVImport.objects.create(
            account=account,
            file=uploaded_file,
            original_filename=validation['filename'],
            row_count=validation['row_count'],
            status='pending',
            imported_by=request.user,
        )

        return redirect('finance:csv_import_preview', import_id=csv_import.id)

    return render(request, 'finance/csv_import.html', {
        'accounts': accounts,
    })


@login_required
def csv_import_preview(request, import_id):
    """
    Preview parsed CSV data before import.

    GET: Show preview with category mapping
    POST: Perform import with user selections

    GET/POST /finance/import/<id>/preview/
    """
    csv_import = get_object_or_404(CSVImport, pk=import_id)

    # Only allow preview of pending imports
    if csv_import.status != 'pending':
        messages.error(request, 'This import has already been processed.')
        return redirect('finance:csv_import_results', import_id=csv_import.id)

    # Parse the CSV
    try:
        csv_import.file.seek(0)
        content = csv_import.file.read().decode('utf-8')
    except Exception as e:
        logger.exception(f"Failed to read CSV file for import {import_id}")
        messages.error(request, 'Failed to read CSV file.')
        return redirect('finance:csv_import_upload')

    parser = AmexCSVParser(csv_import.account)
    parsed_rows = parser.parse_csv(content)

    # Get categories for dropdown
    expense_categories = Category.objects.filter(
        is_active=True,
        category_type='expense'
    ).order_by('display_order', 'name')

    income_categories = Category.objects.filter(
        is_active=True,
        category_type='income'
    ).order_by('display_order', 'name')

    if request.method == 'POST':
        # Process import
        csv_import.status = 'processing'
        csv_import.save()

        # Collect category overrides from form
        category_overrides = {}
        for key, value in request.POST.items():
            if key.startswith('category_'):
                row_num = key.replace('category_', '')
                if value:
                    category_overrides[row_num] = value

        # Get skip duplicates setting
        skip_duplicates = request.POST.get('skip_duplicates', 'on') == 'on'

        # Perform import
        importer = CSVImporter(csv_import, request.user)
        results = importer.import_rows(
            parsed_rows,
            category_overrides=category_overrides,
            skip_duplicates=skip_duplicates,
        )

        messages.success(
            request,
            f'Import complete: {results["imported"]} imported, '
            f'{results["skipped"]} skipped, {len(results["errors"])} errors.'
        )
        return redirect('finance:csv_import_results', import_id=csv_import.id)

    # Count stats for display
    valid_count = sum(1 for r in parsed_rows if r.is_valid)
    duplicate_count = sum(1 for r in parsed_rows if r.is_duplicate)
    error_count = sum(1 for r in parsed_rows if not r.is_valid)

    return render(request, 'finance/csv_preview.html', {
        'csv_import': csv_import,
        'parsed_rows': parsed_rows,
        'expense_categories': expense_categories,
        'income_categories': income_categories,
        'valid_count': valid_count,
        'duplicate_count': duplicate_count,
        'error_count': error_count,
    })


@login_required
def csv_import_results(request, import_id):
    """
    Show import results.

    GET /finance/import/<id>/results/
    """
    csv_import = get_object_or_404(CSVImport, pk=import_id)

    return render(request, 'finance/csv_results.html', {
        'csv_import': csv_import,
    })


@login_required
def csv_import_list(request):
    """
    List all CSV imports.

    GET /finance/imports/
    """
    imports = CSVImport.objects.select_related(
        'account', 'imported_by'
    ).order_by('-imported_at')

    return render(request, 'finance/csv_import_list.html', {
        'imports': imports,
    })


# =============================================================================
# Account Management Views (Phase 8)
# =============================================================================

@login_required
def account_list(request):
    """
    List all accounts with balances.

    GET /finance/accounts/
    """
    accounts = Account.objects.all()

    # Calculate totals
    total_checking = sum(
        a.current_balance for a in accounts if a.account_type == 'checking' and a.is_active
    )
    total_credit = sum(
        a.current_balance for a in accounts if a.account_type == 'credit_card' and a.is_active
    )
    total_savings = sum(
        a.current_balance for a in accounts if a.account_type == 'savings' and a.is_active
    )

    return render(request, 'finance/account_list.html', {
        'accounts': accounts,
        'total_checking': total_checking,
        'total_credit': total_credit,
        'total_savings': total_savings,
    })


@login_required
def account_create(request):
    """
    Create a new account.

    GET/POST /finance/accounts/new/
    """
    if request.method == 'POST':
        form = AccountForm(request.POST)
        if form.is_valid():
            account = form.save(commit=False)
            account.created_by = request.user
            account.save()
            messages.success(request, f'Account "{account.name}" created successfully.')
            return redirect('finance:account_detail', account_id=account.id)
    else:
        form = AccountForm()

    return render(request, 'finance/account_form.html', {
        'form': form,
        'title': 'New Account',
    })


@login_required
def account_edit(request, account_id):
    """
    Edit an existing account.

    GET/POST /finance/accounts/<id>/edit/
    """
    account = get_object_or_404(Account, pk=account_id)

    if request.method == 'POST':
        form = AccountForm(request.POST, instance=account)
        if form.is_valid():
            form.save()
            messages.success(request, f'Account "{account.name}" updated successfully.')
            return redirect('finance:account_detail', account_id=account.id)
    else:
        form = AccountForm(instance=account)

    return render(request, 'finance/account_form.html', {
        'form': form,
        'account': account,
        'title': 'Edit Account',
    })


@login_required
def account_detail(request, account_id):
    """
    View account details with transaction history.

    GET /finance/accounts/<id>/
    """
    account = get_object_or_404(Account, pk=account_id)

    # Get transactions for this account
    transactions = Transaction.objects.filter(
        account=account
    ).select_related('category').order_by('-transaction_date', '-created_at')

    # Also get transfers TO this account
    transfers_in = Transaction.objects.filter(
        transfer_to_account=account
    ).select_related('account', 'category').order_by('-transaction_date', '-created_at')

    # Pagination for transactions
    paginator = Paginator(transactions, 25)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    return render(request, 'finance/account_detail.html', {
        'account': account,
        'transactions': page_obj,
        'transfers_in': transfers_in[:10],  # Show recent transfers in
        'transaction_count': paginator.count,
    })


@login_required
@require_POST
def account_toggle_active(request, account_id):
    """
    Toggle account active status.

    POST /finance/accounts/<id>/toggle-active/
    """
    account = get_object_or_404(Account, pk=account_id)
    account.is_active = not account.is_active
    account.save()

    status = 'activated' if account.is_active else 'deactivated'
    messages.success(request, f'Account "{account.name}" {status}.')

    return redirect('finance:account_list')


# =============================================================================
# Category Management Views (Phase 9)
# =============================================================================

@login_required
def category_list(request):
    """
    List all categories grouped by type.

    GET /finance/categories/
    """
    expense_categories = Category.objects.filter(
        category_type='expense'
    ).order_by('display_order', 'name')

    income_categories = Category.objects.filter(
        category_type='income'
    ).order_by('display_order', 'name')

    return render(request, 'finance/category_list.html', {
        'expense_categories': expense_categories,
        'income_categories': income_categories,
    })


@login_required
def category_create(request):
    """
    Create a new category.

    GET/POST /finance/categories/new/
    """
    if request.method == 'POST':
        form = CategoryForm(request.POST)
        if form.is_valid():
            category = form.save()
            messages.success(request, f'Category "{category.name}" created successfully.')
            return redirect('finance:category_list')
    else:
        # Pre-select category type from query param
        initial = {}
        category_type = request.GET.get('type')
        if category_type in ('expense', 'income'):
            initial['category_type'] = category_type
        form = CategoryForm(initial=initial)

    return render(request, 'finance/category_form.html', {
        'form': form,
        'title': 'New Category',
    })


@login_required
def category_edit(request, category_id):
    """
    Edit an existing category.

    GET/POST /finance/categories/<id>/edit/
    """
    category = get_object_or_404(Category, pk=category_id)

    if request.method == 'POST':
        form = CategoryForm(request.POST, instance=category)
        if form.is_valid():
            form.save()
            messages.success(request, f'Category "{category.name}" updated successfully.')
            return redirect('finance:category_list')
    else:
        form = CategoryForm(instance=category)

    return render(request, 'finance/category_form.html', {
        'form': form,
        'category': category,
        'title': 'Edit Category',
    })


@login_required
def category_detail(request, category_id):
    """
    View category details with transaction count.

    GET /finance/categories/<id>/
    """
    category = get_object_or_404(Category, pk=category_id)

    # Get recent transactions for this category
    transactions = Transaction.objects.filter(
        category=category
    ).select_related('account').order_by('-transaction_date', '-created_at')[:10]

    transaction_count = Transaction.objects.filter(category=category).count()

    return render(request, 'finance/category_detail.html', {
        'category': category,
        'transactions': transactions,
        'transaction_count': transaction_count,
    })


@login_required
@require_POST
def category_delete(request, category_id):
    """
    Delete a category.

    POST /finance/categories/<id>/delete/

    System categories cannot be deleted.
    Categories with transactions cannot be deleted.
    """
    category = get_object_or_404(Category, pk=category_id)

    # Check if system category
    if category.is_system:
        messages.error(request, 'System categories cannot be deleted.')
        return redirect('finance:category_list')

    # Check if category has transactions
    transaction_count = Transaction.objects.filter(category=category).count()
    if transaction_count > 0:
        messages.error(
            request,
            f'Cannot delete category "{category.name}". '
            f'It has {transaction_count} transaction(s) associated with it.'
        )
        return redirect('finance:category_list')

    category_name = category.name
    category.delete()
    messages.success(request, f'Category "{category_name}" deleted successfully.')

    return redirect('finance:category_list')


@login_required
@require_POST
def category_toggle_active(request, category_id):
    """
    Toggle category active status.

    POST /finance/categories/<id>/toggle-active/
    """
    category = get_object_or_404(Category, pk=category_id)
    category.is_active = not category.is_active
    category.save()

    status = 'activated' if category.is_active else 'deactivated'
    messages.success(request, f'Category "{category.name}" {status}.')

    return redirect('finance:category_list')


# =============================================================================
# Recurring Transaction Views (Phase 11)
# =============================================================================

@login_required
def recurring_list(request):
    """
    List all recurring transactions.

    GET /finance/recurring/
    """
    recurring = RecurringTransaction.objects.select_related(
        'account', 'category'
    ).all()

    # Separate active and inactive
    active_recurring = recurring.filter(is_active=True)
    inactive_recurring = recurring.filter(is_active=False)

    # Calculate stats
    active_count = active_recurring.count()
    total_monthly = sum(
        r.amount for r in active_recurring if r.frequency == 'monthly'
    )
    total_quarterly = sum(
        r.amount for r in active_recurring if r.frequency == 'quarterly'
    )
    total_annually = sum(
        r.amount for r in active_recurring if r.frequency == 'annually'
    )

    # Calculate estimated monthly expense
    estimated_monthly = (
        total_monthly +
        (total_quarterly / Decimal('3')) +
        (total_annually / Decimal('12'))
    )

    return render(request, 'finance/recurring_list.html', {
        'active_recurring': active_recurring,
        'inactive_recurring': inactive_recurring,
        'active_count': active_count,
        'total_monthly': total_monthly,
        'total_quarterly': total_quarterly,
        'total_annually': total_annually,
        'estimated_monthly': estimated_monthly,
    })


@login_required
def recurring_create(request):
    """
    Create a new recurring transaction template.

    GET/POST /finance/recurring/new/
    """
    if request.method == 'POST':
        form = RecurringTransactionForm(request.POST)
        if form.is_valid():
            recurring = form.save(commit=False)
            recurring.created_by = request.user
            recurring.save()
            messages.success(
                request,
                f'Recurring transaction "{recurring.vendor}" created successfully.'
            )
            return redirect('finance:recurring_list')
    else:
        form = RecurringTransactionForm()

    return render(request, 'finance/recurring_form.html', {
        'form': form,
        'title': 'New Recurring Transaction',
    })


@login_required
def recurring_edit(request, recurring_id):
    """
    Edit an existing recurring transaction template.

    GET/POST /finance/recurring/<id>/edit/
    """
    recurring = get_object_or_404(RecurringTransaction, pk=recurring_id)

    if request.method == 'POST':
        form = RecurringTransactionForm(request.POST, instance=recurring)
        if form.is_valid():
            form.save()
            messages.success(
                request,
                f'Recurring transaction "{recurring.vendor}" updated successfully.'
            )
            return redirect('finance:recurring_list')
    else:
        form = RecurringTransactionForm(instance=recurring)

    return render(request, 'finance/recurring_form.html', {
        'form': form,
        'recurring': recurring,
        'title': 'Edit Recurring Transaction',
    })


@login_required
def recurring_detail(request, recurring_id):
    """
    View recurring transaction details.

    GET /finance/recurring/<id>/
    """
    recurring = get_object_or_404(
        RecurringTransaction.objects.select_related('account', 'category'),
        pk=recurring_id
    )

    # Get generated transactions
    generated_transactions = Transaction.objects.filter(
        recurring_source=recurring
    ).select_related('account', 'category').order_by('-transaction_date')[:20]

    generated_count = Transaction.objects.filter(recurring_source=recurring).count()

    return render(request, 'finance/recurring_detail.html', {
        'recurring': recurring,
        'generated_transactions': generated_transactions,
        'generated_count': generated_count,
    })


@login_required
@require_POST
def recurring_toggle_active(request, recurring_id):
    """
    Toggle recurring transaction active status.

    POST /finance/recurring/<id>/toggle-active/
    """
    recurring = get_object_or_404(RecurringTransaction, pk=recurring_id)
    recurring.is_active = not recurring.is_active
    recurring.save()

    status = 'activated' if recurring.is_active else 'deactivated'
    messages.success(request, f'Recurring transaction "{recurring.vendor}" {status}.')

    return redirect('finance:recurring_list')


@login_required
@require_POST
def recurring_delete(request, recurring_id):
    """
    Delete a recurring transaction template.

    POST /finance/recurring/<id>/delete/

    Note: This does not delete generated transactions.
    """
    recurring = get_object_or_404(RecurringTransaction, pk=recurring_id)
    vendor = recurring.vendor
    recurring.delete()
    messages.success(request, f'Recurring transaction "{vendor}" deleted successfully.')

    return redirect('finance:recurring_list')


@login_required
@require_POST
def recurring_generate(request, recurring_id):
    """
    Manually generate a transaction from recurring template.

    POST /finance/recurring/<id>/generate/

    Creates a transaction immediately, regardless of next_due date.
    """
    recurring = get_object_or_404(RecurringTransaction, pk=recurring_id)

    if not recurring.is_active:
        messages.error(request, 'Cannot generate transaction from inactive recurring template.')
        return redirect('finance:recurring_detail', recurring_id=recurring_id)

    # Create the transaction
    transaction = Transaction.objects.create(
        account=recurring.account,
        transaction_type='expense',
        category=recurring.category,
        amount=recurring.amount,
        transaction_date=date.today(),
        description=recurring.description,
        vendor=recurring.vendor,
        is_recurring=True,
        recurring_source=recurring,
        created_by=request.user,
    )

    # Update last_generated
    recurring.last_generated = date.today()

    # Calculate next_due based on frequency
    import calendar
    today = date.today()

    if recurring.frequency == 'monthly':
        # Next month, same day
        if today.month == 12:
            next_date = today.replace(year=today.year + 1, month=1, day=1)
        else:
            next_date = today.replace(month=today.month + 1, day=1)
        max_day = calendar.monthrange(next_date.year, next_date.month)[1]
        recurring.next_due = next_date.replace(day=min(recurring.day_of_month, max_day))

    elif recurring.frequency == 'quarterly':
        # 3 months from now
        month = today.month + 3
        year = today.year
        if month > 12:
            month -= 12
            year += 1
        next_date = date(year, month, 1)
        max_day = calendar.monthrange(next_date.year, next_date.month)[1]
        recurring.next_due = next_date.replace(day=min(recurring.day_of_month, max_day))

    elif recurring.frequency == 'annually':
        # Next year, same month and day
        next_date = date(today.year + 1, today.month, 1)
        max_day = calendar.monthrange(next_date.year, next_date.month)[1]
        recurring.next_due = next_date.replace(day=min(recurring.day_of_month, max_day))

    recurring.save()

    messages.success(
        request,
        f'Transaction generated: {transaction.description} - ${transaction.amount}'
    )

    return redirect('finance:recurring_detail', recurring_id=recurring_id)
