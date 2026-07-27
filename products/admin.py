from django.contrib import admin

from .models import Product


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    """Simple admin: create products, assign users, upload/replace the build,
    and enable/disable downloads. That's the whole Phase 1 admin surface."""

    list_display = ('name', 'current_version', 'current_build', 'download_enabled', 'has_download', 'user_count', 'updated_at')
    list_filter = ('download_enabled',)
    search_fields = ('name', 'description', 'current_version', 'current_build')
    prepopulated_fields = {'slug': ('name',)}
    filter_horizontal = ('authorized_users',)
    readonly_fields = ('created_at', 'updated_at', 'filename')

    fieldsets = (
        (None, {
            'fields': ('name', 'slug', 'description', 'current_version', 'current_build', 'icon'),
        }),
        ('Download', {
            'fields': ('download_file', 'filename', 'download_enabled'),
            'description': "Uploading a new file replaces the current build. "
                           "Uncheck 'download enabled' to pause downloads without deleting the file.",
        }),
        ('Access', {
            'fields': ('authorized_users',),
            'description': "Only the selected users can see and download this product.",
        }),
        ('Tracking', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    @admin.display(boolean=True, description='Has build')
    def has_download(self, obj):
        return obj.has_download

    @admin.display(description='Users')
    def user_count(self, obj):
        return obj.authorized_users.count()
