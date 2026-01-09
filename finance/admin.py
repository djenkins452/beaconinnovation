from django.contrib import admin
from .models import (
    Account, Category, Transaction, Receipt,
    RecurringTransaction, TaxAlert, AuditLog, CSVImport
)


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ('name', 'account_type', 'institution', 'last_four', 'is_personal', 'is_active', 'opening_balance')
    list_filter = ('account_type', 'is_personal', 'is_active', 'institution')
    search_fields = ('name', 'institution', 'last_four')
    readonly_fields = ('id', 'created_at', 'updated_at')
    ordering = ('name',)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'category_type', 'is_system', 'is_active', 'display_order')
    list_filter = ('category_type', 'is_system', 'is_active')
    search_fields = ('name', 'description')
    readonly_fields = ('id', 'created_at', 'updated_at')
    ordering = ('category_type', 'display_order', 'name')


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('transaction_date', 'description', 'amount', 'transaction_type', 'account', 'category', 'is_reconciled')
    list_filter = ('transaction_type', 'account', 'category', 'is_reconciled', 'is_recurring')
    search_fields = ('description', 'vendor', 'notes', 'reference_number')
    readonly_fields = ('id', 'created_at', 'updated_at')
    date_hierarchy = 'transaction_date'
    ordering = ('-transaction_date', '-created_at')

    fieldsets = (
        (None, {
            'fields': ('account', 'transaction_type', 'category', 'amount', 'transaction_date', 'description')
        }),
        ('Details', {
            'fields': ('vendor', 'reference_number', 'notes'),
            'classes': ('collapse',)
        }),
        ('Transfer', {
            'fields': ('transfer_to_account',),
            'classes': ('collapse',)
        }),
        ('Recurring', {
            'fields': ('is_recurring', 'recurring_source'),
            'classes': ('collapse',)
        }),
        ('Reconciliation', {
            'fields': ('is_reconciled', 'reconciled_at'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('id', 'created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = ('original_filename', 'transaction', 'file_type', 'file_size', 'ocr_processed', 'uploaded_at')
    list_filter = ('file_type', 'ocr_processed')
    search_fields = ('original_filename', 'ocr_vendor', 'ocr_raw_text')
    readonly_fields = ('id', 'uploaded_at')
    ordering = ('-uploaded_at',)


@admin.register(RecurringTransaction)
class RecurringTransactionAdmin(admin.ModelAdmin):
    list_display = ('vendor', 'amount', 'frequency', 'account', 'category', 'next_due', 'is_active')
    list_filter = ('frequency', 'is_active', 'account', 'category')
    search_fields = ('vendor', 'description')
    readonly_fields = ('id', 'created_at', 'updated_at', 'last_generated')
    ordering = ('next_due',)


@admin.register(TaxAlert)
class TaxAlertAdmin(admin.ModelAdmin):
    list_display = ('quarter', 'year', 'actual_net_profit', 'threshold_amount', 'alert_triggered', 'acknowledged')
    list_filter = ('year', 'quarter', 'alert_triggered', 'acknowledged')
    readonly_fields = ('id', 'created_at', 'updated_at')
    ordering = ('-year', '-quarter')


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'user', 'action', 'model_name', 'object_repr')
    list_filter = ('action', 'model_name', 'user')
    search_fields = ('object_repr', 'user__username')
    readonly_fields = ('id', 'user', 'action', 'model_name', 'object_id', 'object_repr', 'changes', 'ip_address', 'user_agent', 'created_at')
    ordering = ('-created_at',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CSVImport)
class CSVImportAdmin(admin.ModelAdmin):
    list_display = ('original_filename', 'account', 'status', 'row_count', 'imported_count', 'error_count', 'imported_at')
    list_filter = ('status', 'account')
    search_fields = ('original_filename',)
    readonly_fields = ('id', 'imported_at')
    ordering = ('-imported_at',)
