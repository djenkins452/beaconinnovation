"""
URL configuration for the finance app.
"""
from django.urls import path

from . import views

app_name = 'finance'

urlpatterns = [
    # Receipt upload/management endpoints (Phase 4)
    path('transactions/<uuid:transaction_id>/receipts/', views.list_transaction_receipts, name='transaction_receipts'),
    path('transactions/<uuid:transaction_id>/receipts/upload/', views.upload_receipt, name='upload_receipt'),
    path('receipts/<uuid:receipt_id>/', views.get_receipt_info, name='receipt_info'),
    path('receipts/<uuid:receipt_id>/view/', views.view_receipt, name='view_receipt'),
    path('receipts/<uuid:receipt_id>/download/', views.download_receipt, name='download_receipt'),
    path('receipts/<uuid:receipt_id>/delete/', views.delete_receipt, name='delete_receipt'),

    # OCR endpoints (Phase 5)
    path('receipts/<uuid:receipt_id>/ocr/', views.process_receipt_ocr, name='process_ocr'),
    path('receipts/<uuid:receipt_id>/ocr/rerun/', views.rerun_receipt_ocr, name='rerun_ocr'),
    path('receipts/<uuid:receipt_id>/ocr/status/', views.get_receipt_ocr_status, name='ocr_status'),

    # API endpoints
    path('api/ocr/status/', views.check_tesseract_status, name='tesseract_status'),
]
