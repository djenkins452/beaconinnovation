"""URL configuration for the staff-only Operations module."""
from django.urls import path

from . import views

app_name = 'operations'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),

    # Suppliers / locations
    path('suppliers/', views.supplier_list, name='supplier_list'),
    path('suppliers/new/', views.supplier_create, name='supplier_create'),
    path('locations/', views.location_list, name='location_list'),
    path('locations/new/', views.location_create, name='location_create'),

    # Materials
    path('materials/', views.material_list, name='material_list'),
    path('materials/new/', views.material_create, name='material_create'),
    path('materials/<uuid:material_id>/', views.material_detail, name='material_detail'),

    # Spools + weigh-in / reconcile
    path('spools/', views.spool_list, name='spool_list'),
    path('spools/<uuid:spool_id>/', views.spool_detail, name='spool_detail'),
    path('spools/<uuid:spool_id>/weigh/', views.spool_weigh, name='spool_weigh'),
    path('measurements/<uuid:measurement_id>/reconcile/', views.measurement_reconcile, name='measurement_reconcile'),

    # Stock + equipment
    path('stock/', views.stock_list, name='stock_list'),
    path('equipment/', views.equipment_list, name='equipment_list'),
    path('equipment/new/', views.equipment_create, name='equipment_create'),

    # Opening inventory
    path('opening/', views.opening_index, name='opening_index'),
    path('opening/spool/', views.opening_spool, name='opening_spool'),
    path('opening/stock/', views.opening_stock, name='opening_stock'),

    # Purchases
    path('purchases/', views.purchase_list, name='purchase_list'),
    path('purchases/new/', views.purchase_create, name='purchase_create'),
    path('purchases/<uuid:purchase_id>/', views.purchase_detail, name='purchase_detail'),
    path('purchases/<uuid:purchase_id>/lines/add/', views.purchase_add_line, name='purchase_add_line'),
    path('purchases/<uuid:purchase_id>/link-payment/', views.purchase_link_payment, name='purchase_link_payment'),
    path('purchases/<uuid:purchase_id>/create-expense/', views.purchase_create_expense, name='purchase_create_expense'),
    path('purchases/<uuid:purchase_id>/documents/upload/', views.purchase_upload_document, name='purchase_upload_document'),
    path('lines/<uuid:line_id>/receive/', views.line_receive, name='line_receive'),
    path('documents/<uuid:document_id>/view/', views.document_view, name='document_view'),
    path('documents/<uuid:document_id>/download/', views.document_download, name='document_download'),

    # Printing
    path('prints/', views.print_list, name='print_list'),
    path('prints/new/', views.print_create, name='print_create'),
    path('prints/<uuid:print_id>/', views.print_detail, name='print_detail'),

    # Inventory history + corrections
    path('history/', views.movement_list, name='movement_list'),
    path('movements/<uuid:movement_id>/reverse/', views.movement_reverse, name='movement_reverse'),
]
