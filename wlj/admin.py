# ==============================================================================
# File: admin.py
# Project: Beacon Innovations - WLJ Financial Dashboard
# Description: Django admin configuration for WLJ models
# Owner: Danny Jenkins (dannyjenkins71@gmail.com)
# Created: 2025-12-28
# ==============================================================================

from django.contrib import admin
from .models import ServiceCost, FinancialProjection, CodebaseMetric, Document, DocumentDownload


@admin.register(ServiceCost)
class ServiceCostAdmin(admin.ModelAdmin):
    list_display = ('provider', 'product', 'category', 'cost_1k_low', 'cost_1k_high')
    list_filter = ('category',)
    search_fields = ('provider', 'product')
    ordering = ('category', 'provider')


@admin.register(FinancialProjection)
class FinancialProjectionAdmin(admin.ModelAdmin):
    list_display = ('scenario', 'year', 'paying_users', 'annual_revenue', 'net_profit')
    list_filter = ('scenario', 'year')
    ordering = ('scenario', 'year')


@admin.register(CodebaseMetric)
class CodebaseMetricAdmin(admin.ModelAdmin):
    list_display = ('captured_at', 'total_tests', 'total_apps', 'third_party_services')
    ordering = ('-captured_at',)


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ('title', 'document_type', 'version', 'is_current', 'download_count', 'created_at')
    list_filter = ('document_type', 'is_current')
    search_fields = ('title', 'description')
    ordering = ('-created_at',)
    readonly_fields = ('download_count', 'created_at', 'updated_at')


@admin.register(DocumentDownload)
class DocumentDownloadAdmin(admin.ModelAdmin):
    list_display = ('document', 'user', 'downloaded_at', 'ip_address')
    list_filter = ('downloaded_at',)
    search_fields = ('document__title', 'user__username')
    ordering = ('-downloaded_at',)
    readonly_fields = ('document', 'user', 'downloaded_at', 'ip_address')
