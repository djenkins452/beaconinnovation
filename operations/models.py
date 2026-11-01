"""Data model for the staff-only Operations module (3D-printing business).

Design spine (see docs/architecture/PRINT_BUSINESS_OS_DISCOVERY.md §4, §7):

* An **append-only inventory movement ledger** (:class:`InventoryMovement`) is the
  single source of truth for how much of anything is on hand. Current quantity is
  ALWAYS ``sum(movements)`` — never a mutable counter. Movements are immutable;
  corrections are new reversing/adjusting movements, never edits.
* ``finance`` stays the authority for money. Operations *references* finance for
  the cash side of a purchase (:class:`PurchasePayment`) and emits inventory
  **receipt** movements for the asset side. Receiving materials never creates an
  expense; opening inventory never creates an expense.
* Estimated weight (from the ledger) is kept strictly separate from measured
  weight (from :class:`ScaleMeasurement`); reconciliation is an explicit
  adjustment movement.

All mutations go through ``operations.services`` so that an immutable
:class:`AuditEvent` is written on every write (the wired-audit discipline the
finance ``AuditLogMixin`` never got). Do not create/alter these rows directly in
views — call the service layer.
"""
import uuid
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import Sum
from django.utils import timezone


# Shared decimal field shapes. Explicit, per the "appropriate decimal precision
# and explicit units" requirement.
WEIGHT_DECIMALS = dict(max_digits=12, decimal_places=2)   # grams
QTY_DECIMALS = dict(max_digits=12, decimal_places=3)      # counts / general quantities
MONEY_DECIMALS = dict(max_digits=12, decimal_places=2)    # dollars

ZERO = Decimal('0')


class UnitChoices(models.TextChoices):
    GRAM = 'g', 'grams (g)'
    KILOGRAM = 'kg', 'kilograms (kg)'
    EACH = 'each', 'each / unit'
    PACK = 'pack', 'pack'
    ROLL = 'roll', 'roll'
    METER = 'm', 'meters (m)'
    MILLILITER = 'ml', 'milliliters (ml)'
    LITER = 'l', 'liters (l)'


# =============================================================================
# Immutable audit (wired from day one)
# =============================================================================

class AuditEvent(models.Model):
    """Append-only audit record written by the service layer on every mutation.

    Mirrors the immutability discipline of ``aegis.core`` / ``finance.AuditLog``:
    rows cannot be updated or deleted once written.
    """

    ACTION_CHOICES = [
        ('create', 'Create'),
        ('update', 'Update'),
        ('delete', 'Delete'),
        ('movement', 'Inventory movement'),
        ('reverse', 'Reversal / correction'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='operations_audit_events',
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES, db_index=True)
    model_name = models.CharField(max_length=100, db_index=True)
    object_id = models.CharField(max_length=64, db_index=True)
    object_repr = models.CharField(max_length=500)
    summary = models.CharField(max_length=500, blank=True, default='')
    changes = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Audit Event'
        indexes = [
            models.Index(fields=['model_name', 'object_id'], name='ops_audit_obj_idx'),
        ]

    def __str__(self):
        return f'{self.action} {self.model_name} by {self.actor} at {self.created_at:%Y-%m-%d %H:%M}'

    def save(self, *args, **kwargs):
        if self.pk and AuditEvent.objects.filter(pk=self.pk).exists():
            raise ValidationError('Audit events are immutable and cannot be modified.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Audit events cannot be deleted.')


# =============================================================================
# Reference data
# =============================================================================

class Supplier(models.Model):
    """A place you buy from. Deliberately lightweight (an upgrade of finance's
    free-text ``vendor``); not required to record a purchase."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, unique=True)
    website = models.URLField(blank=True, default='')
    notes = models.TextField(blank=True, default='')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='operations_suppliers',
    )

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Location(models.Model):
    """A physical place stock lives (shelf, bin, dry-box)."""

    KIND_CHOICES = [
        ('shelf', 'Shelf'),
        ('bin', 'Bin'),
        ('drybox', 'Dry box'),
        ('printer', 'Printer / AMS'),
        ('other', 'Other'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120, unique=True)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default='shelf')
    notes = models.TextField(blank=True, default='')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Material(models.Model):
    """A catalog entry for something you stock. One row per manufacturer+product+
    color; individual physical units are :class:`FilamentSpool` (filament) or
    :class:`StockItem` (hardware/consumables/packaging)."""

    MATERIAL_TYPE_CHOICES = [
        ('filament', 'Filament'),
        ('hardware', 'Hardware'),
        ('consumable', 'Consumable'),
        ('packaging', 'Packaging'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    material_type = models.CharField(max_length=20, choices=MATERIAL_TYPE_CHOICES, db_index=True)
    manufacturer = models.CharField(max_length=120, blank=True, default='')
    # For filament: the material/plastic (PLA, PETG, ...). For others: a short type.
    product_type = models.CharField(
        max_length=120, blank=True, default='',
        help_text='e.g. PLA, PETG, M3 bolt, bubble mailer',
    )
    name = models.CharField(max_length=200, help_text='Product / color name, e.g. "Matte Black"')
    color_code = models.CharField(max_length=40, blank=True, default='', help_text='Optional hex or vendor code')
    sku = models.CharField(max_length=100, blank=True, default='')
    default_unit = models.CharField(max_length=10, choices=UnitChoices.choices, default=UnitChoices.EACH)
    nominal_spool_weight_g = models.DecimalField(
        null=True, blank=True, **WEIGHT_DECIMALS,
        help_text='Filament only: typical net filament weight of a full spool (g).',
    )
    reorder_threshold = models.DecimalField(
        null=True, blank=True, **QTY_DECIMALS,
        help_text='Optional. Flagged as low stock when total on hand falls to or below this (in default unit; grams for filament).',
    )
    notes = models.TextField(blank=True, default='')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='operations_materials',
    )

    class Meta:
        ordering = ['material_type', 'manufacturer', 'name']

    def __str__(self):
        bits = [b for b in (self.manufacturer, self.product_type, self.name) if b]
        return ' '.join(bits) or self.name

    @property
    def is_filament(self):
        return self.material_type == 'filament'

    def total_on_hand(self):
        """Total current quantity across every physical unit of this material.

        Grams for filament (summed over spools); default-unit counts otherwise
        (summed over stock items). Always derived from the movement ledger.
        """
        if self.is_filament:
            total = ZERO
            for spool in self.spools.all():
                total += spool.estimated_remaining_g
            return total
        total = ZERO
        for item in self.stock_items.filter(status=StockItem.STATUS_AVAILABLE):
            total += item.on_hand
        return total

    @property
    def is_low_stock(self):
        if self.reorder_threshold is None:
            return False
        return self.total_on_hand() <= self.reorder_threshold


# =============================================================================
# Physical inventory units
# =============================================================================

class FilamentSpool(models.Model):
    """An individual, trackable spool. Per-spool is required for multicolor prints
    and accurate remaining-grams/tare handling.

    Estimated remaining grams come from the movement ledger
    (:attr:`estimated_remaining_g`). Measured remaining grams come from the most
    recent :class:`ScaleMeasurement`. The two are never conflated.
    """

    STATUS_CHOICES = [
        ('sealed', 'Sealed / new'),
        ('open', 'Open / in use'),
        ('low', 'Low'),
        ('empty', 'Empty'),
        ('damaged', 'Damaged'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    material = models.ForeignKey(
        Material, on_delete=models.PROTECT, related_name='spools',
        limit_choices_to={'material_type': 'filament'},
    )
    # A human/label identifier for the physical spool (write it on the spool).
    spool_uid = models.CharField(
        max_length=60, unique=True,
        help_text='Your identifier for this physical spool (e.g. SP-0007).',
    )
    starting_weight_g = models.DecimalField(
        default=ZERO, **WEIGHT_DECIMALS, validators=[MinValueValidator(ZERO)],
        help_text='Net filament weight when this spool entered inventory (g). '
                  'Leave 0 and tick "remaining unknown" to track by status only.',
    )
    # Gram tracking is OPTIONAL. When remaining is untracked we track the spool by
    # material/color + status (sealed/open/low/empty) instead of a weight. "Unknown"
    # is NOT zero and NOT a full spool — it just means grams are not being tracked.
    remaining_unknown = models.BooleanField(
        default=False,
        help_text='Remaining filament is not tracked by weight (track by status instead).',
    )
    # A refill is filament without its own physical spool core (loaded onto a reusable
    # spool). Still inventory, but not another physical spool.
    is_refill = models.BooleanField(
        default=False,
        help_text='This is refill filament (no physical spool core), not a new spool.',
    )
    tare_weight_g = models.DecimalField(
        null=True, blank=True, **WEIGHT_DECIMALS, validators=[MinValueValidator(ZERO)],
        help_text='Empty-spool weight (g), when known. Used to turn a scale reading into remaining filament.',
    )
    cost = models.DecimalField(null=True, blank=True, **MONEY_DECIMALS, help_text='What this spool cost (optional / unknown).')
    cost_unknown = models.BooleanField(default=False)
    location = models.ForeignKey(
        Location, on_delete=models.SET_NULL, null=True, blank=True, related_name='spools',
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='sealed', db_index=True)
    source_line = models.ForeignKey(
        'PurchaseLine', on_delete=models.SET_NULL, null=True, blank=True, related_name='spools',
        help_text='The purchase line this spool was received from, if any.',
    )
    notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='operations_spools',
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.spool_uid} — {self.material}'

    @property
    def estimated_remaining_g(self):
        """Ledger truth: sum of this spool's signed movements (grams)."""
        total = self.movements.aggregate(t=Sum('quantity'))['t']
        return total if total is not None else ZERO

    @property
    def latest_measurement(self):
        return self.measurements.order_by('-measured_at', '-created_at').first()

    @property
    def measured_remaining_g(self):
        m = self.latest_measurement
        return m.net_g if m else None

    @property
    def variance_g(self):
        """measured − estimated (positive = more filament than the ledger thinks)."""
        measured = self.measured_remaining_g
        if measured is None:
            return None
        return measured - self.estimated_remaining_g

    @property
    def is_tracked(self):
        """True when this spool's remaining filament is tracked by weight."""
        return not self.remaining_unknown

    @property
    def remaining_display(self):
        """Human label for remaining filament. When grams aren't tracked, show the
        status word ("Unknown" is deliberately NOT 0 g and NOT a full spool)."""
        if self.remaining_unknown:
            measured = self.measured_remaining_g
            if measured is not None:
                return f'{measured:g} g (measured)'
            return 'Unknown (tracked by status)'
        return f'{self.estimated_remaining_g:g} g'


class StockItem(models.Model):
    """Quantity-tracked stock for hardware, consumables and packaging.

    A row is a (material, location, status, unit) bucket; its quantity is derived
    from the movement ledger. Damaged/unusable stock is a separate ``status`` row
    so it is never counted as available.
    """

    STATUS_AVAILABLE = 'available'
    STATUS_DAMAGED = 'damaged'
    STATUS_UNUSABLE = 'unusable'
    STATUS_CHOICES = [
        (STATUS_AVAILABLE, 'Available'),
        (STATUS_DAMAGED, 'Damaged'),
        (STATUS_UNUSABLE, 'Unusable'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    material = models.ForeignKey(
        Material, on_delete=models.PROTECT, related_name='stock_items',
        limit_choices_to={'material_type__in': ['hardware', 'consumable', 'packaging']},
    )
    location = models.ForeignKey(
        Location, on_delete=models.SET_NULL, null=True, blank=True, related_name='stock_items',
    )
    unit = models.CharField(max_length=10, choices=UnitChoices.choices, default=UnitChoices.EACH)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_AVAILABLE, db_index=True)
    notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='operations_stock_items',
    )

    class Meta:
        ordering = ['material__name']
        constraints = [
            models.UniqueConstraint(
                fields=['material', 'location', 'status', 'unit'],
                name='unique_stock_bucket',
            )
        ]

    def __str__(self):
        loc = f' @ {self.location}' if self.location else ''
        extra = '' if self.status == self.STATUS_AVAILABLE else f' [{self.get_status_display()}]'
        return f'{self.material}{loc}{extra}'

    @property
    def on_hand(self):
        total = self.movements.aggregate(t=Sum('quantity'))['t']
        return total if total is not None else ZERO


class Equipment(models.Model):
    """Printers and tools. Equipment is an asset record, NOT consumable stock, so
    it never appears in the inventory ledger and receiving it creates no movement."""

    EQUIPMENT_TYPE_CHOICES = [
        ('printer', 'Printer'),
        ('tool', 'Tool'),
        ('other', 'Other'),
    ]
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('retired', 'Retired'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=160)
    equipment_type = models.CharField(max_length=20, choices=EQUIPMENT_TYPE_CHOICES, default='printer')
    manufacturer = models.CharField(max_length=120, blank=True, default='')
    model = models.CharField(max_length=120, blank=True, default='')
    serial_number = models.CharField(max_length=120, blank=True, default='')
    cost = models.DecimalField(null=True, blank=True, **MONEY_DECIMALS)
    cost_unknown = models.BooleanField(default=False)
    acquired_date = models.DateField(null=True, blank=True)
    location = models.ForeignKey(
        Location, on_delete=models.SET_NULL, null=True, blank=True, related_name='equipment',
    )
    source_line = models.ForeignKey(
        'PurchaseLine', on_delete=models.SET_NULL, null=True, blank=True, related_name='equipment',
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='active', db_index=True)
    notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='operations_equipment',
    )

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'Equipment'

    def __str__(self):
        return self.name


# =============================================================================
# Purchasing (bridges to finance for money; emits receipts for the asset side)
# =============================================================================

class Purchase(models.Model):
    """A buying event. The money side links to finance ``Transaction`` rows via
    :class:`PurchasePayment` (zero, one or many — no single-payment assumption).
    The asset side is realised by *receiving* lines, which emit inventory
    movements. Receiving never creates an expense."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, null=True, blank=True, related_name='purchases',
    )
    supplier_name = models.CharField(
        max_length=200, blank=True, default='',
        help_text='Free-text supplier when you have not created a Supplier record.',
    )
    order_date = models.DateField(default=timezone.localdate)
    order_number = models.CharField(max_length=120, blank=True, default='')
    product_links = models.TextField(blank=True, default='', help_text='One product URL per line (optional).')
    # Order-level charges. Kept separate from line costs; no accounting policy imposed.
    shipping_total = models.DecimalField(default=ZERO, **MONEY_DECIMALS)
    tax_total = models.DecimalField(default=ZERO, **MONEY_DECIMALS)
    discount_total = models.DecimalField(default=ZERO, **MONEY_DECIMALS)
    notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='operations_purchases',
    )

    class Meta:
        ordering = ['-order_date', '-created_at']

    def __str__(self):
        who = self.supplier.name if self.supplier else (self.supplier_name or 'Unknown supplier')
        num = f' #{self.order_number}' if self.order_number else ''
        return f'{who}{num} ({self.order_date})'

    @property
    def supplier_display(self):
        if self.supplier:
            return self.supplier.name
        return self.supplier_name or 'Unknown supplier'

    def lines_subtotal(self):
        return sum((line.line_total for line in self.lines.all()), ZERO)

    def order_total(self):
        return self.lines_subtotal() + self.shipping_total + self.tax_total - self.discount_total

    def linked_payment_total(self):
        return self.payments.aggregate(t=Sum('amount'))['t'] or ZERO

    @property
    def receipt_status(self):
        """Derived receiving state across all lines."""
        lines = list(self.lines.all())
        if not lines:
            return 'empty'
        states = {line.receipt_state for line in lines}
        if states == {'received'}:
            return 'received'
        if states == {'none'}:
            return 'none'
        return 'partial'


class PurchaseLine(models.Model):
    """A single ordered item on a purchase. Resolves on receipt to filament
    spools, stock, or an equipment record. Carries the business/personal/shared
    use split that finance lacks."""

    ITEM_TYPE_CHOICES = [
        ('filament', 'Filament (creates spools)'),
        ('stock', 'Stock (hardware / consumable / packaging)'),
        ('equipment', 'Equipment (printer / tool)'),
        ('other', 'Other (no inventory)'),
    ]
    USE_CHOICES = [
        ('business', 'Business'),
        ('personal', 'Personal'),
        ('shared', 'Shared'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, related_name='lines')
    item_type = models.CharField(max_length=12, choices=ITEM_TYPE_CHOICES, default='stock')
    description = models.CharField(max_length=300)
    material = models.ForeignKey(
        Material, on_delete=models.PROTECT, null=True, blank=True, related_name='purchase_lines',
        help_text='For filament/stock lines: which catalog material this is.',
    )
    quantity_ordered = models.DecimalField(**QTY_DECIMALS, validators=[MinValueValidator(Decimal('0'))])
    quantity_received = models.DecimalField(default=ZERO, **QTY_DECIMALS, validators=[MinValueValidator(ZERO)])
    unit = models.CharField(max_length=10, choices=UnitChoices.choices, default=UnitChoices.EACH)
    unit_cost = models.DecimalField(default=ZERO, **MONEY_DECIMALS, validators=[MinValueValidator(ZERO)])
    line_discount = models.DecimalField(default=ZERO, **MONEY_DECIMALS, validators=[MinValueValidator(ZERO)])
    line_tax = models.DecimalField(default=ZERO, **MONEY_DECIMALS, validators=[MinValueValidator(ZERO)])
    use_type = models.CharField(max_length=10, choices=USE_CHOICES, default='business')
    business_pct = models.DecimalField(
        default=Decimal('100.00'), max_digits=5, decimal_places=2,
        validators=[MinValueValidator(ZERO), MaxValueValidator(Decimal('100'))],
        help_text='Percent of this line that is business use (100 for business, 0 for personal, in between for shared).',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'{self.description} ({self.quantity_received}/{self.quantity_ordered} {self.unit})'

    @property
    def line_total(self):
        return (self.quantity_ordered * self.unit_cost) - self.line_discount + self.line_tax

    @property
    def quantity_outstanding(self):
        return self.quantity_ordered - self.quantity_received

    @property
    def receipt_state(self):
        if self.item_type == 'other':
            return 'received'  # nothing to receive into inventory
        if self.quantity_received <= ZERO:
            return 'none'
        if self.quantity_received >= self.quantity_ordered:
            return 'received'
        return 'partial'

    def clean(self):
        super().clean()
        if self.use_type == 'business':
            self.business_pct = Decimal('100.00')
        elif self.use_type == 'personal':
            self.business_pct = Decimal('0.00')


class PurchasePayment(models.Model):
    """Links a purchase to an existing finance ``Transaction`` (the expense).

    This is the ONLY place operations touches money. A purchase may have zero,
    one, or many payments. Creating one of these does not itself move inventory.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, related_name='payments')
    transaction = models.ForeignKey(
        'finance.Transaction', on_delete=models.PROTECT, related_name='operations_purchase_payments',
    )
    amount = models.DecimalField(**MONEY_DECIMALS)
    note = models.CharField(max_length=300, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='operations_purchase_payments',
    )

    class Meta:
        ordering = ['created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['purchase', 'transaction'],
                name='unique_purchase_transaction_link',
            )
        ]

    def __str__(self):
        return f'{self.purchase} ↔ {self.transaction} (${self.amount})'


class PurchaseDocument(models.Model):
    """A receipt/invoice attached to a purchase.

    Reuses the finance private-storage backend (``finance.storage.database_storage``):
    bytes live in PostgreSQL, there is no public URL, and the file is served only
    through the staff-gated operations view. This is the same durable, private
    mechanism finance receipts use — no new paid resource.
    """
    from finance.storage import database_storage  # local import to avoid ordering issues

    FILE_TYPE_CHOICES = [
        ('pdf', 'PDF'),
        ('jpg', 'JPEG'),
        ('png', 'PNG'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, related_name='documents')
    file = models.FileField(upload_to='operations/purchase_docs/%Y/%m/', storage=database_storage)
    original_filename = models.CharField(max_length=255)
    file_type = models.CharField(max_length=10, choices=FILE_TYPE_CHOICES)
    file_size = models.IntegerField(default=0, help_text='File size in bytes')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='operations_purchase_documents',
    )

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return f'Document: {self.original_filename}'


# =============================================================================
# The movement ledger (append-only source of truth) + prints + measurements
# =============================================================================

class InventoryMovement(models.Model):
    """One immutable change to the quantity of exactly one spool OR one stock item.

    Positive ``quantity`` adds to on hand (receipt, opening balance, return,
    positive adjustment); negative removes it (consumption, waste, negative
    adjustment). Current quantity of any unit == ``sum(its movements)``.

    Immutable: once written, a row cannot be edited or deleted. Corrections are
    new movements — a :attr:`reverses` entry negates an earlier one; a fresh
    ``adjustment`` reconciles to a measured value.
    """

    MOVEMENT_TYPE_CHOICES = [
        ('purchase_receipt', 'Purchase receipt'),
        ('opening_balance', 'Opening balance'),
        ('consumption', 'Consumption (print)'),
        ('waste', 'Waste (purge / support / failure)'),
        ('production_output', 'Production output (finished units)'),
        ('fulfillment', 'Fulfillment (finished units out)'),
        ('return', 'Return'),
        ('adjustment', 'Adjustment / reconciliation'),
        ('reversal', 'Reversal of a prior movement'),
    ]

    # Movement types whose sign must be negative (deductions) vs positive (additions).
    DEDUCTION_TYPES = {'consumption', 'waste', 'fulfillment'}
    ADDITION_TYPES = {'purchase_receipt', 'opening_balance', 'return', 'production_output'}
    # 'adjustment' and 'reversal' may be either sign.

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    movement_type = models.CharField(max_length=20, choices=MOVEMENT_TYPE_CHOICES, db_index=True)

    spool = models.ForeignKey(
        FilamentSpool, on_delete=models.PROTECT, null=True, blank=True, related_name='movements',
    )
    stock_item = models.ForeignKey(
        StockItem, on_delete=models.PROTECT, null=True, blank=True, related_name='movements',
    )
    # Finished-goods inventory target (units of a product variant). Produced by
    # prints (production_output) and removed by internal-order fulfillment.
    product_variant = models.ForeignKey(
        'ProductVariant', on_delete=models.PROTECT, null=True, blank=True, related_name='movements',
    )

    quantity = models.DecimalField(
        **QTY_DECIMALS,
        help_text='Signed. Grams for spools, stock unit for stock items. + adds, − removes.',
    )
    unit = models.CharField(max_length=10, choices=UnitChoices.choices)
    reason = models.CharField(max_length=300, blank=True, default='')

    # What caused this movement (optional provenance).
    purchase_line = models.ForeignKey(
        PurchaseLine, on_delete=models.SET_NULL, null=True, blank=True, related_name='movements',
    )
    print_use = models.ForeignKey(
        'PrintMaterialUse', on_delete=models.SET_NULL, null=True, blank=True, related_name='movements',
    )
    reverses = models.ForeignKey(
        'self', on_delete=models.PROTECT, null=True, blank=True, related_name='reversed_by',
    )

    # Idempotency: a repeated submission carrying the same key is rejected, so a
    # double-click or retried request cannot post the same movement twice.
    idempotency_key = models.CharField(max_length=160, null=True, blank=True, unique=True)

    occurred_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='operations_movements',
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['spool', 'created_at'], name='ops_mv_spool_idx'),
            models.Index(fields=['stock_item', 'created_at'], name='ops_mv_stock_idx'),
        ]
        constraints = [
            # Exactly one target of the three (spool / stock item / finished good).
            models.CheckConstraint(
                name='movement_exactly_one_target',
                check=(
                    models.Q(spool__isnull=False, stock_item__isnull=True, product_variant__isnull=True)
                    | models.Q(spool__isnull=True, stock_item__isnull=False, product_variant__isnull=True)
                    | models.Q(spool__isnull=True, stock_item__isnull=True, product_variant__isnull=False)
                ),
            ),
        ]

    def __str__(self):
        return f'{self.get_movement_type_display()} {self.quantity} {self.unit} → {self.target}'

    @property
    def target(self):
        if self.spool_id:
            return self.spool
        if self.stock_item_id:
            return self.stock_item
        return self.product_variant

    @property
    def is_reversed(self):
        return self.reversed_by.exists()

    def save(self, *args, **kwargs):
        if self.pk and InventoryMovement.objects.filter(pk=self.pk).exists():
            raise ValidationError(
                'Inventory movements are immutable. Post a reversing or adjusting '
                'movement instead of editing this one.'
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Inventory movements cannot be deleted (append-only ledger).')


class PrintLog(models.Model):
    """A print job. Finished-goods inventory is deferred, so a successful print
    records a quantity for reference only; the ledger effect is the material it
    consumed (and wasted)."""

    PURPOSE_CHOICES = [
        ('business', 'Business'),
        ('prototype', 'Prototype'),
        ('personal', 'Personal'),
    ]
    OUTCOME_CHOICES = [
        ('success', 'Success'),
        ('partial', 'Partial'),
        ('failed', 'Failed'),
        ('in_progress', 'In progress'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    printed_on = models.DateField(default=timezone.localdate)
    printer = models.ForeignKey(
        Equipment, on_delete=models.PROTECT, null=True, blank=True, related_name='prints',
        limit_choices_to={'equipment_type': 'printer'},
    )
    purpose = models.CharField(max_length=12, choices=PURPOSE_CHOICES, default='business')
    outcome = models.CharField(max_length=12, choices=OUTCOME_CHOICES, default='success')
    success_quantity = models.IntegerField(
        default=0, validators=[MinValueValidator(0)],
        help_text='Legacy/simple good-unit count. When product lines are used, their '
                  'successful quantities drive finished-goods stock instead.',
    )
    is_historical = models.BooleanField(
        default=False,
        help_text='Recorded after the fact while reconstructing history (back-dated).',
    )
    notes = models.TextField(blank=True, default='')
    # Idempotency for the whole print submission.
    submission_token = models.CharField(max_length=64, null=True, blank=True, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='operations_prints',
    )

    class Meta:
        ordering = ['-printed_on', '-created_at']

    def __str__(self):
        return f'{self.name} ({self.printed_on}, {self.get_outcome_display()})'

    @property
    def total_consumed_g(self):
        return sum((u.grams_consumed for u in self.material_uses.all()), ZERO)

    @property
    def total_waste_g(self):
        return sum((u.waste_grams for u in self.material_uses.all()), ZERO)

    @property
    def total_filament_g(self):
        """All filament that left inventory for this print = consumed + waste.
        Consumed and waste are stored separately so waste is never double-counted."""
        return self.total_consumed_g + self.total_waste_g


class PrintMaterialUse(models.Model):
    """One spool's contribution to one print.

    ``grams_consumed`` is filament that went into the part(s); ``waste_grams`` is
    purge/support/failure waste. They are recorded separately and each deducts
    exactly once, so waste is never counted twice.

    ``basis`` labels where the numbers came from (recipe ESTIMATE vs SLICER total
    vs MEASURED). ``all_inclusive`` means ``grams_consumed`` ALREADY includes
    supports/purge — when true, ``waste_grams`` is forced to 0 so waste is never
    added on top of an all-inclusive figure.
    """

    BASIS_CHOICES = [
        ('recipe', 'Recipe estimate'),
        ('slicer', 'Slicer total'),
        ('measured', 'Measured'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    print_log = models.ForeignKey(PrintLog, on_delete=models.CASCADE, related_name='material_uses')
    spool = models.ForeignKey(FilamentSpool, on_delete=models.PROTECT, related_name='print_uses')
    grams_consumed = models.DecimalField(default=ZERO, **WEIGHT_DECIMALS, validators=[MinValueValidator(ZERO)])
    waste_grams = models.DecimalField(default=ZERO, **WEIGHT_DECIMALS, validators=[MinValueValidator(ZERO)])
    basis = models.CharField(max_length=10, choices=BASIS_CHOICES, default='slicer')
    all_inclusive = models.BooleanField(
        default=False,
        help_text='The grams figure already includes supports/purge; do not add waste again.',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'{self.spool.spool_uid}: {self.grams_consumed}g + {self.waste_grams}g waste'

    @property
    def total_g(self):
        return self.grams_consumed + self.waste_grams


class ScaleMeasurement(models.Model):
    """A weigh-in of a spool. Stores the measured value (and the tare used) so a
    measured remaining weight is always distinguishable from the ledger estimate.
    Reconciling turns the gap into an explicit adjustment movement."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    spool = models.ForeignKey(FilamentSpool, on_delete=models.CASCADE, related_name='measurements')
    gross_grams = models.DecimalField(
        **WEIGHT_DECIMALS, validators=[MinValueValidator(ZERO)],
        help_text='Total weight on the scale (spool + remaining filament).',
    )
    tare_grams = models.DecimalField(
        **WEIGHT_DECIMALS, validators=[MinValueValidator(ZERO)],
        help_text='Empty-spool weight used for this reading.',
    )
    net_g = models.DecimalField(**WEIGHT_DECIMALS, help_text='gross − tare (remaining filament).')
    reconciled = models.BooleanField(default=False, help_text='Whether an adjustment movement was posted from this reading.')
    note = models.CharField(max_length=300, blank=True, default='')
    measured_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    measured_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='operations_measurements',
    )

    class Meta:
        ordering = ['-measured_at', '-created_at']

    def __str__(self):
        return f'{self.spool.spool_uid}: {self.net_g}g net @ {self.measured_at:%Y-%m-%d}'


# =============================================================================
# Physical products, variants, and versioned production recipes
# =============================================================================

class PhysicalProduct(models.Model):
    """A distinct printed design — separate from Beacon's software-download
    ``products.Product``. Includes internal-only items (bins, swatches, printer
    accessories, office items) and things that may later be sold publicly."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    description = models.TextField(blank=True, default='')
    design_source = models.CharField(
        max_length=300, blank=True, default='',
        help_text='e.g. self-designed, a model site, or a URL.')
    file_reference = models.TextField(
        blank=True, default='',
        help_text='Design/slicer file + version references (one per line).')
    internal_only = models.BooleanField(
        default=True, help_text='Internal use only (not for the future public catalog).')
    catalog_eligible = models.BooleanField(
        default=False, help_text='Eligible for the future public catalog.')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='operations_products')

    class Meta:
        ordering = ['name']
        verbose_name = 'Physical product'

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            from django.utils.text import slugify
            base = slugify(self.name)[:200] or 'product'
            slug = base
            i = 2
            while PhysicalProduct.objects.exclude(pk=self.pk).filter(slug=slug).exists():
                slug = f'{base}-{i}'
                i += 1
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def total_on_hand(self):
        return sum((v.on_hand for v in self.variants.all()), 0)


class ProductVariant(models.Model):
    """A printable/stockable variant of a product (size / material / print profile
    that changes consumption). Every product has at least one ('Default')."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(PhysicalProduct, on_delete=models.CASCADE, related_name='variants')
    name = models.CharField(max_length=120, default='Default')
    notes = models.CharField(max_length=300, blank=True, default='')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['product__name', 'name']
        constraints = [
            models.UniqueConstraint(fields=['product', 'name'], name='unique_variant_per_product'),
        ]

    def __str__(self):
        if self.name and self.name != 'Default':
            return f'{self.product.name} — {self.name}'
        return self.product.name

    @property
    def on_hand(self):
        """Finished units on hand = Σ(finished-goods movements for this variant)."""
        total = self.movements.aggregate(t=Sum('quantity'))['t']
        return int(total) if total is not None else 0

    @property
    def current_recipe(self):
        return self.recipes.filter(is_current=True).order_by('-version').first()


class ProductionRecipe(models.Model):
    """A versioned bill of expected filament usage for a variant. A new version is
    a new row (old versions are preserved), so editing a recipe never rewrites the
    consumption of prints that referenced an earlier version."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name='recipes')
    version = models.PositiveIntegerField(default=1)
    is_current = models.BooleanField(default=True)
    notes = models.CharField(max_length=300, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='operations_recipes')

    class Meta:
        ordering = ['variant', '-version']
        constraints = [
            models.UniqueConstraint(fields=['variant', 'version'], name='unique_recipe_version'),
        ]

    def __str__(self):
        return f'{self.variant} recipe v{self.version}'

    def expected_for(self, quantity):
        """Per-material expected usage for ``quantity`` units.

        Returns a list of dicts: material, grams_consumed, waste_grams. Waste here
        is the per-unit component only; shared batch purge/support overhead is added
        once at print time (it does not scale with quantity)."""
        qty = Decimal(quantity)
        rows = []
        for line in self.materials.select_related('material').all():
            rows.append({
                'material': line.material,
                'grams_consumed': line.grams_per_unit * qty,
                'waste_grams': line.waste_per_unit * qty,
            })
        return rows


class RecipeMaterial(models.Model):
    """Expected per-unit filament usage for one material/color in a recipe."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipe = models.ForeignKey(ProductionRecipe, on_delete=models.CASCADE, related_name='materials')
    material = models.ForeignKey(
        Material, on_delete=models.PROTECT, related_name='recipe_lines',
        limit_choices_to={'material_type': 'filament'})
    grams_per_unit = models.DecimalField(
        default=ZERO, **WEIGHT_DECIMALS, validators=[MinValueValidator(ZERO)],
        help_text='Filament into the part per unit (g).')
    waste_per_unit = models.DecimalField(
        default=ZERO, **WEIGHT_DECIMALS, validators=[MinValueValidator(ZERO)],
        help_text='Per-unit supports/purge that scales with quantity (g). Shared '
                  'batch overhead is added once at print time, not here.')

    class Meta:
        ordering = ['id']
        constraints = [
            models.UniqueConstraint(fields=['recipe', 'material'], name='unique_recipe_material'),
        ]

    def __str__(self):
        return f'{self.material}: {self.grams_per_unit}g (+{self.waste_per_unit}g waste) /unit'

    @property
    def total_per_unit(self):
        return self.grams_per_unit + self.waste_per_unit


class PrintProduct(models.Model):
    """A product produced by a print. Snapshots the recipe VERSION used so later
    recipe edits never change this print's record. Successful units feed finished
    inventory (a ``production_output`` movement)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    print_log = models.ForeignKey(PrintLog, on_delete=models.CASCADE, related_name='products')
    variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT, related_name='print_products')
    recipe = models.ForeignKey(
        ProductionRecipe, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='print_products', help_text='Recipe version used (snapshot).')
    quantity_planned = models.PositiveIntegerField(default=0)
    quantity_success = models.PositiveIntegerField(
        default=0, help_text='Good units produced — these are added to finished inventory.')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'{self.variant} ×{self.quantity_success}/{self.quantity_planned}'


# =============================================================================
# Internal orders (staff-only, no payment) — remove finished goods, not filament
# =============================================================================

class InternalOrder(models.Model):
    """A staff-only internal order with NO payment. Fulfilling it removes finished
    units from inventory; it never deducts filament. Kept entirely separate from
    any (future) customer sales/revenue."""

    PURPOSE_CHOICES = [
        ('personal', 'Personal use'),
        ('office', 'Office / print-room setup'),
        ('sample', 'Sample / display'),
        ('gift', 'Gift / promotional'),
    ]
    STATUS_CHOICES = [
        ('open', 'Open'),
        ('fulfilled', 'Fulfilled'),
        ('cancelled', 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    purpose = models.CharField(max_length=12, choices=PURPOSE_CHOICES, default='personal')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='open', db_index=True)
    notes = models.TextField(blank=True, default='')
    ordered_on = models.DateField(default=timezone.localdate)
    fulfilled_at = models.DateTimeField(null=True, blank=True)
    # Idempotency for fulfillment (a double-click can't deduct finished goods twice).
    fulfillment_token = models.CharField(max_length=64, null=True, blank=True, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='operations_internal_orders')

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Internal order ({self.get_purpose_display()}, {self.get_status_display()})'

    @property
    def payment_label(self):
        return 'No payment required'


class InternalOrderLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(InternalOrder, on_delete=models.CASCADE, related_name='lines')
    variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT, related_name='internal_order_lines')
    quantity = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'{self.variant} ×{self.quantity}'
