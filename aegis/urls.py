"""URL entry point for the Enterprise Platform, mounted at ``/platform/``.

Uses the ``platform`` namespace. This is only the incubation route; the package
name (``aegis``) and the eventual product name are separate concerns.
"""
from django.urls import include, path

from aegis.core import views

app_name = 'platform'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('hr/', include('aegis.core_hr.urls')),
]
