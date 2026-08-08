from django.urls import path

from aegis.core_hr import views

app_name = 'core_hr'

urlpatterns = [
    path('employees/', views.employee_list, name='employee_list'),
    path('employees/add/', views.employee_create, name='employee_create'),
    path('employees/<uuid:pk>/', views.employee_detail, name='employee_detail'),
    path('employees/<uuid:pk>/edit/', views.employee_edit, name='employee_edit'),
    path('reference/<slug:slug>/', views.reference_list, name='reference_list'),
    path('reference/<slug:slug>/add/', views.reference_create, name='reference_create'),
    path('reference/<slug:slug>/<uuid:pk>/edit/', views.reference_edit, name='reference_edit'),
    path('reference/<slug:slug>/<uuid:pk>/toggle/', views.reference_toggle_active, name='reference_toggle_active'),
]
