"""
URL configuration for the finance app.
"""
from django.urls import path

from . import views

app_name = 'finance'

urlpatterns = [
    # Dashboard & Reports (Phase 10)
    path('', views.dashboard, name='dashboard'),
    path('reports/spending/', views.spending_report, name='spending_report'),
    path('reports/income-statement/', views.income_statement, name='income_statement'),

    # Transaction CRUD (Phase 6)
    path('transactions/', views.transaction_list, name='transaction_list'),
    path('transactions/new/', views.transaction_create, name='transaction_create'),
    path('transactions/<uuid:transaction_id>/', views.transaction_detail, name='transaction_detail'),
    path('transactions/<uuid:transaction_id>/edit/', views.transaction_edit, name='transaction_edit'),
    path('transactions/<uuid:transaction_id>/delete/', views.transaction_delete, name='transaction_delete'),

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

    # CSV Import (Phase 7)
    path('import/', views.csv_import_upload, name='csv_import_upload'),
    path('import/<uuid:import_id>/preview/', views.csv_import_preview, name='csv_import_preview'),
    path('import/<uuid:import_id>/results/', views.csv_import_results, name='csv_import_results'),
    path('imports/', views.csv_import_list, name='csv_import_list'),

    # Account Management (Phase 8)
    path('accounts/', views.account_list, name='account_list'),
    path('accounts/new/', views.account_create, name='account_create'),
    path('accounts/<uuid:account_id>/', views.account_detail, name='account_detail'),
    path('accounts/<uuid:account_id>/edit/', views.account_edit, name='account_edit'),
    path('accounts/<uuid:account_id>/toggle-active/', views.account_toggle_active, name='account_toggle_active'),

    # Category Management (Phase 9)
    path('categories/', views.category_list, name='category_list'),
    path('categories/new/', views.category_create, name='category_create'),
    path('categories/<uuid:category_id>/', views.category_detail, name='category_detail'),
    path('categories/<uuid:category_id>/edit/', views.category_edit, name='category_edit'),
    path('categories/<uuid:category_id>/delete/', views.category_delete, name='category_delete'),
    path('categories/<uuid:category_id>/toggle-active/', views.category_toggle_active, name='category_toggle_active'),

    # Recurring Transactions (Phase 11)
    path('recurring/', views.recurring_list, name='recurring_list'),
    path('recurring/new/', views.recurring_create, name='recurring_create'),
    path('recurring/<uuid:recurring_id>/', views.recurring_detail, name='recurring_detail'),
    path('recurring/<uuid:recurring_id>/edit/', views.recurring_edit, name='recurring_edit'),
    path('recurring/<uuid:recurring_id>/delete/', views.recurring_delete, name='recurring_delete'),
    path('recurring/<uuid:recurring_id>/toggle-active/', views.recurring_toggle_active, name='recurring_toggle_active'),
    path('recurring/<uuid:recurring_id>/generate/', views.recurring_generate, name='recurring_generate'),

    # API endpoints
    path('api/ocr/status/', views.check_tesseract_status, name='tesseract_status'),
    path('api/vendor-suggest/', views.vendor_suggest, name='vendor_suggest'),
    path('api/categories/', views.get_categories_by_type, name='categories_by_type'),
    path('api/dashboard/data/', views.dashboard_data_api, name='dashboard_data'),
]
