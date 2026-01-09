"""
Views for the finance app.
"""
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse, FileResponse, Http404
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST, require_GET

from .models import Receipt, Transaction, Category
from .forms import validate_receipt_file, TransactionForm, TransactionFilterForm
from .ocr import process_receipt_image, is_tesseract_available, OCRError

logger = logging.getLogger(__name__)


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
