# ==============================================================================
# File: urls.py
# Project: Beacon Innovations - WLJ Financial Dashboard
# Owner: Danny Jenkins (dannyjenkins71@gmail.com)
# Created: 2025-12-28
# ==============================================================================

from django.urls import path
from . import views

app_name = 'wlj'

urlpatterns = [
    path('login/', views.wlj_login, name='login'),
    path('logout/', views.wlj_logout, name='logout'),
    path('', views.dashboard, name='dashboard'),
    path('financials/', views.financials, name='financials'),
    path('costs/', views.service_costs_view, name='service_costs'),
    path('metrics/', views.codebase_metrics, name='codebase_metrics'),
    path('data-room/', views.data_room, name='data_room'),
    path('download/<int:pk>/', views.download_document, name='download'),
    path('api/projections/', views.api_projections, name='api_projections'),
]
