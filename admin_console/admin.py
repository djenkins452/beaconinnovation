from django.contrib import admin
from .models import AdminTask


@admin.register(AdminTask)
class AdminTaskAdmin(admin.ModelAdmin):
    list_display = ('title', 'status', 'priority', 'phase', 'created_at', 'updated_at')
    list_filter = ('status', 'priority', 'phase')
    search_fields = ('title', 'notes')
    readonly_fields = ('id', 'created_at', 'updated_at', 'started_at', 'completed_at')
    ordering = ('-priority', 'created_at')

    fieldsets = (
        (None, {
            'fields': ('title', 'description', 'status', 'priority', 'phase')
        }),
        ('Dependencies', {
            'fields': ('depends_on', 'notes'),
            'classes': ('collapse',)
        }),
        ('Tracking', {
            'fields': ('id', 'created_by', 'created_at', 'updated_at', 'started_at', 'completed_at'),
            'classes': ('collapse',)
        }),
    )
