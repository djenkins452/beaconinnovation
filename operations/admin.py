"""Admin registrations for Operations.

The navigable staff screens (operations/*) are the primary UI; these admin
registrations are a convenience. The append-only ledger and the audit log are
registered READ-ONLY to preserve immutability (corrections go through the app's
reversing/adjusting movements, never an admin edit).
"""
from django.contrib import admin

from operations.models import (
    AuditEvent, Equipment, FilamentSpool, InternalOrder, InternalOrderLine,
    InventoryMovement, Location, Material, PhysicalProduct, PrintLog,
    PrintMaterialUse, PrintProduct, ProductionRecipe, ProductVariant, Purchase,
    PurchaseDocument, PurchaseLine, PurchasePayment, RecipeMaterial,
    ScaleMeasurement, StockItem, Supplier,
)


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'created_at')
    search_fields = ('name',)


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ('name', 'kind', 'is_active')


@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'material_type', 'default_unit', 'reorder_threshold', 'is_active')
    list_filter = ('material_type', 'is_active')
    search_fields = ('name', 'manufacturer', 'sku', 'product_type')


@admin.register(FilamentSpool)
class FilamentSpoolAdmin(admin.ModelAdmin):
    list_display = ('spool_uid', 'material', 'status', 'starting_weight_g', 'location')
    list_filter = ('status', 'material__material_type')
    search_fields = ('spool_uid', 'material__name')


@admin.register(StockItem)
class StockItemAdmin(admin.ModelAdmin):
    list_display = ('material', 'location', 'status', 'unit')
    list_filter = ('status',)


@admin.register(Equipment)
class EquipmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'equipment_type', 'status', 'location')
    list_filter = ('equipment_type', 'status')


class PurchaseLineInline(admin.TabularInline):
    model = PurchaseLine
    extra = 0


class PurchasePaymentInline(admin.TabularInline):
    model = PurchasePayment
    extra = 0
    autocomplete_fields = ()


class PurchaseDocumentInline(admin.TabularInline):
    model = PurchaseDocument
    extra = 0
    readonly_fields = ('original_filename', 'file_type', 'file_size', 'uploaded_at')


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'order_date', 'receipt_status')
    inlines = [PurchaseLineInline, PurchasePaymentInline, PurchaseDocumentInline]
    search_fields = ('order_number', 'supplier__name', 'supplier_name')


class PrintMaterialUseInline(admin.TabularInline):
    model = PrintMaterialUse
    extra = 0


class PrintProductInline(admin.TabularInline):
    model = PrintProduct
    extra = 0


@admin.register(PrintLog)
class PrintLogAdmin(admin.ModelAdmin):
    list_display = ('name', 'printed_on', 'printer', 'purpose', 'outcome', 'is_historical')
    list_filter = ('purpose', 'outcome', 'is_historical')
    inlines = [PrintProductInline, PrintMaterialUseInline]


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 0


@admin.register(PhysicalProduct)
class PhysicalProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'internal_only', 'catalog_eligible', 'is_active')
    list_filter = ('internal_only', 'catalog_eligible', 'is_active')
    search_fields = ('name', 'design_source')
    prepopulated_fields = {'slug': ('name',)}
    inlines = [ProductVariantInline]


class RecipeMaterialInline(admin.TabularInline):
    model = RecipeMaterial
    extra = 0


@admin.register(ProductionRecipe)
class ProductionRecipeAdmin(admin.ModelAdmin):
    list_display = ('variant', 'version', 'is_current', 'created_at')
    list_filter = ('is_current',)
    inlines = [RecipeMaterialInline]


class InternalOrderLineInline(admin.TabularInline):
    model = InternalOrderLine
    extra = 0


@admin.register(InternalOrder)
class InternalOrderAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'purpose', 'status', 'ordered_on', 'fulfilled_at')
    list_filter = ('purpose', 'status')
    inlines = [InternalOrderLineInline]


@admin.register(ScaleMeasurement)
class ScaleMeasurementAdmin(admin.ModelAdmin):
    list_display = ('spool', 'net_g', 'measured_at', 'reconciled')


class ReadOnlyAdmin(admin.ModelAdmin):
    """No add/change/delete — immutable records are viewed here, never edited."""
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(InventoryMovement)
class InventoryMovementAdmin(ReadOnlyAdmin):
    list_display = ('created_at', 'movement_type', 'target', 'quantity', 'unit', 'actor')
    list_filter = ('movement_type',)


@admin.register(AuditEvent)
class AuditEventAdmin(ReadOnlyAdmin):
    list_display = ('created_at', 'action', 'model_name', 'object_repr', 'actor')
    list_filter = ('action', 'model_name')
