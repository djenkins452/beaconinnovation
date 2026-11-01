"""Forms for the Operations module.

These drive the navigable, staff-only screens. Heavy lifting (movements, audit,
finance bridge, idempotency) lives in ``operations.services``; forms only collect
and validate input.
"""
from decimal import Decimal

from django import forms

from finance.models import Account, Category, Transaction
from operations.models import (
    Equipment, FilamentSpool, Location, Material, Purchase, PurchaseLine,
    StockItem, UnitChoices,
)

CONTROL = {'class': 'form-control'}


def _style(form):
    """Apply the shared .form-control class to every visible widget."""
    for field in form.fields.values():
        w = field.widget
        if isinstance(w, (forms.CheckboxInput,)):
            continue
        css = w.attrs.get('class', '')
        w.attrs['class'] = (css + ' form-control').strip()


class StyledModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)


class StyledForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)


# Units sold/counted as indivisible whole items (a spool, a pack, a roll, a unit)
# vs. units measured by weight/volume/length where decimals are meaningful. The
# quantity box steps in whole numbers for the former and allows decimals for the
# latter, so the up/down arrows never nudge a spool count into fractions.
WHOLE_UNITS = {'each', 'pack', 'roll'}
DECIMAL_UNITS = {'g', 'kg', 'ml', 'l', 'm'}


def _configure_quantity_unit(form, qty_field='quantity_ordered', unit_field='unit'):
    """Make quantity entry clear and safe: whole-number stepping for indivisible
    items (spools/packs/rolls) and decimals only for weight/volume/length units.
    A tiny script in the template flips the step live when the unit changes; here we
    set a sensible default so the field never silently steps in thousandths."""
    qf = form.fields.get(qty_field)
    uf = form.fields.get(unit_field)
    if qf is None or uf is None:
        return
    # Decide the initial step from whatever unit is currently selected.
    current = form.initial.get(unit_field) or getattr(
        getattr(form, 'instance', None), unit_field, None) or qf_initial_unit(form, unit_field)
    step = 'any' if current in DECIMAL_UNITS else '1'
    qf.widget.attrs.update({'step': step, 'min': '0', 'data-qty-input': '1'})
    uf.widget.attrs.update({'data-unit-select': '1'})


def qf_initial_unit(form, unit_field):
    """Best-effort current unit for a form field (bound data, then field initial)."""
    if form.is_bound:
        return form.data.get(form.add_prefix(unit_field))
    f = form.fields.get(unit_field)
    return getattr(f, 'initial', None) if f else None


def _collapse_single_location(form):
    """When only one active location exists, default to it and hide the selector so
    routine forms stay simple. The field reappears automatically once a second
    location is added."""
    if 'location' not in form.fields:
        return
    locs = list(Location.objects.filter(is_active=True))
    if len(locs) == 1:
        form.fields['location'].initial = locs[0]
        form.fields['location'].required = False
        form.fields['location'].widget = forms.HiddenInput()


# --------------------------------------------------------------------- reference
class SupplierForm(StyledModelForm):
    class Meta:
        model = __import__('operations').models.Supplier
        fields = ['name', 'website', 'notes', 'is_active']
        widgets = {'notes': forms.Textarea(attrs={'rows': 2})}


class LocationForm(StyledModelForm):
    class Meta:
        model = Location
        fields = ['name', 'kind', 'notes', 'is_active']
        widgets = {'notes': forms.Textarea(attrs={'rows': 2})}


class MaterialForm(StyledModelForm):
    class Meta:
        model = Material
        fields = [
            'material_type', 'manufacturer', 'product_type', 'name', 'color_code',
            'sku', 'default_unit', 'nominal_spool_weight_g', 'reorder_threshold', 'notes',
        ]
        widgets = {'notes': forms.Textarea(attrs={'rows': 2})}


class EquipmentForm(StyledModelForm):
    class Meta:
        model = Equipment
        fields = [
            'name', 'equipment_type', 'manufacturer', 'model', 'serial_number',
            'cost', 'cost_unknown', 'acquired_date', 'location', 'status', 'notes',
        ]
        widgets = {
            'acquired_date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }


# --------------------------------------------------------------------- opening inventory
class OpeningSpoolForm(StyledForm):
    """Add a filament spool you already own (no finance expense).

    Gram tracking is optional: tick "remaining unknown" to track the spool by status
    only (sealed / open / low / empty) without entering a weight."""
    material = forms.ModelChoiceField(queryset=Material.objects.filter(material_type='filament', is_active=True))
    spool_uid = forms.CharField(max_length=60, label='Spool ID')
    remaining_unknown = forms.BooleanField(
        required=False, initial=True, label='Remaining unknown (track by status only)',
        help_text='Leave ticked to skip gram tracking. Untick to enter a weight.')
    is_refill = forms.BooleanField(required=False, label='Refill (no physical spool core)')
    starting_weight_g = forms.DecimalField(required=False, min_value=Decimal('0'),
                                           label='Remaining filament now (g)',
                                           help_text='Only if tracking by weight: what is left now.')
    tare_weight_g = forms.DecimalField(required=False, min_value=Decimal('0'), label='Empty-spool weight (g)')
    cost = forms.DecimalField(required=False, min_value=Decimal('0'))
    cost_unknown = forms.BooleanField(required=False, label='Cost unknown')
    location = forms.ModelChoiceField(queryset=Location.objects.filter(is_active=True), required=False)
    status = forms.ChoiceField(choices=FilamentSpool.STATUS_CHOICES, initial='open')
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _collapse_single_location(self)

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('remaining_unknown') and cleaned.get('starting_weight_g') in (None, ''):
            self.add_error('starting_weight_g',
                           'Enter a weight, or tick "remaining unknown" to track by status.')
        return cleaned


class OpeningStockForm(StyledForm):
    """Add hardware/consumables/packaging you already own (no finance expense)."""
    material = forms.ModelChoiceField(
        queryset=Material.objects.filter(material_type__in=['hardware', 'consumable', 'packaging'], is_active=True))
    quantity = forms.DecimalField(min_value=Decimal('0'), label='Quantity on hand now')
    unit = forms.ChoiceField(choices=UnitChoices.choices, initial=UnitChoices.EACH)
    location = forms.ModelChoiceField(queryset=Location.objects.filter(is_active=True), required=False)
    status = forms.ChoiceField(choices=StockItem.STATUS_CHOICES, initial=StockItem.STATUS_AVAILABLE)
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _collapse_single_location(self)


# --------------------------------------------------------------------- purchasing
class PurchaseForm(StyledModelForm):
    class Meta:
        model = Purchase
        fields = [
            'supplier', 'supplier_name', 'order_date', 'order_number', 'product_links',
            'shipping_total', 'tax_total', 'discount_total', 'notes',
        ]
        widgets = {
            'order_date': forms.DateInput(attrs={'type': 'date'}),
            'product_links': forms.Textarea(attrs={'rows': 2, 'placeholder': 'One URL per line'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['supplier'].required = False
        self.fields['supplier'].queryset = __import__('operations').models.Supplier.objects.filter(is_active=True)


class PurchaseLineForm(StyledModelForm):
    class Meta:
        model = PurchaseLine
        fields = [
            'item_type', 'description', 'material', 'quantity_ordered', 'unit',
            'unit_cost', 'line_discount', 'line_tax', 'use_type', 'business_pct',
        ]
        labels = {
            'quantity_ordered': 'Quantity ordered',
            'unit': 'Purchase unit',
            'unit_cost': 'Cost per unit',
            'line_tax': 'Line tax (this line only)',
        }
        help_texts = {
            'quantity_ordered': 'How many you bought. For a spool/pack/roll this steps '
                                'in whole numbers; weight units (g/kg) allow decimals.',
            'unit': 'What one unit is — e.g. 1 roll (spool) of filament, 1 pack, 1 each.',
            'unit_cost': 'Price for ONE unit. 1 spool at $15.99 → quantity 1, unit roll, cost $15.99.',
            'line_tax': 'Tax charged on this line only. Order-wide tax goes on the purchase, not here.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['material'].required = False
        self.fields['material'].queryset = Material.objects.filter(is_active=True)
        _configure_quantity_unit(self)

    def clean(self):
        cleaned = super().clean()
        item_type = cleaned.get('item_type')
        material = cleaned.get('material')
        if item_type in ('filament', 'stock') and material is None:
            self.add_error('material', 'Pick a material for filament/stock lines.')
        if item_type == 'filament' and material and material.material_type != 'filament':
            self.add_error('material', 'This line is filament but the material is not a filament.')
        return cleaned


class PurchaseEditForm(StyledModelForm):
    """Edit a purchase's header: supplier, order date/number, order-level shipping,
    tax and discount, notes, and funding designation. Order-level tax is a separate
    field from any line's own tax, so it is never counted twice."""
    class Meta:
        model = Purchase
        fields = [
            'supplier', 'supplier_name', 'order_date', 'order_number', 'funding',
            'shipping_total', 'tax_total', 'discount_total', 'product_links', 'notes',
        ]
        labels = {
            'tax_total': 'Order-level tax',
            'discount_total': 'Order-level discount',
            'shipping_total': 'Shipping',
            'funding': 'Funding',
        }
        help_texts = {
            'tax_total': 'Tax charged on the whole order. Per-line tax is set on each line, '
                         'not here — the two are added separately and never doubled.',
            'funding': 'How this was paid, by your confirmation. Not a Finance expense, loan, '
                       'or tax decision.',
        }
        widgets = {
            'order_date': forms.DateInput(attrs={'type': 'date'}),
            'product_links': forms.Textarea(attrs={'rows': 2, 'placeholder': 'One URL per line'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['supplier'].required = False
        self.fields['supplier'].queryset = __import__('operations').models.Supplier.objects.filter(is_active=True)


class PurchaseLineEditForm(StyledModelForm):
    """Edit one purchase line. On a line that has already been received, the
    structural fields (item type, material, purchase unit) are shown read-only — they
    are locked because real inventory was created from them; cost, tax, discount, use
    classification and description stay editable. The service layer enforces the same
    rule, so a tampered submission is still rejected."""
    class Meta:
        model = PurchaseLine
        fields = [
            'item_type', 'description', 'material', 'quantity_ordered', 'unit',
            'unit_cost', 'line_discount', 'line_tax', 'use_type', 'business_pct',
        ]
        labels = {
            'quantity_ordered': 'Quantity ordered',
            'unit': 'Purchase unit',
            'unit_cost': 'Cost per unit',
            'line_tax': 'Line tax (this line only)',
        }
        help_texts = {
            'quantity_ordered': 'For a spool/pack/roll this steps in whole numbers; '
                                'weight units (g/kg) allow decimals.',
            'unit_cost': 'Price for ONE unit. 1 spool at $15.99 → quantity 1, unit roll, cost $15.99.',
            'line_tax': 'Tax on this line only. Order-wide tax is set on the purchase.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['material'].required = False
        self.fields['material'].queryset = Material.objects.filter(is_active=True)
        _configure_quantity_unit(self)
        line = self.instance
        self.received = bool(line and line.pk and (line.quantity_received or Decimal('0')) > Decimal('0'))
        if self.received:
            # Lock the fields tied to created inventory/records. Disabled fields keep
            # their initial value on submit, so they cannot be changed from the form.
            for name in ('item_type', 'material', 'unit'):
                self.fields[name].disabled = True
                self.fields[name].help_text = 'Locked — this line has been received. ' \
                    'Reverse the receipt in inventory history to change this.'

    def clean(self):
        cleaned = super().clean()
        item_type = cleaned.get('item_type')
        material = cleaned.get('material')
        if item_type in ('filament', 'stock') and material is None:
            self.add_error('material', 'Pick a material for filament/stock lines.')
        if item_type == 'filament' and material and material.material_type != 'filament':
            self.add_error('material', 'This line is filament but the material is not a filament.')
        return cleaned


class ReceiveStockForm(StyledForm):
    quantity = forms.DecimalField(min_value=Decimal('0.001'), label='Quantity to receive now')
    location = forms.ModelChoiceField(queryset=Location.objects.filter(is_active=True), required=False)
    status = forms.ChoiceField(choices=StockItem.STATUS_CHOICES, initial=StockItem.STATUS_AVAILABLE)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _collapse_single_location(self)


class ReceiveFilamentForm(StyledForm):
    """Receive filament by creating one or more individual spools."""
    count = forms.IntegerField(min_value=1, initial=1, label='How many spools')
    uid_prefix = forms.CharField(max_length=40, label='Spool ID prefix',
                                 help_text='Spools are numbered PREFIX-1, PREFIX-2, …')
    starting_weight_g = forms.DecimalField(min_value=Decimal('0'), label='Net filament per spool (g)')
    tare_weight_g = forms.DecimalField(required=False, min_value=Decimal('0'), label='Empty-spool weight (g)')
    cost_each = forms.DecimalField(required=False, min_value=Decimal('0'), label='Cost per spool')
    location = forms.ModelChoiceField(queryset=Location.objects.filter(is_active=True), required=False)
    status = forms.ChoiceField(choices=FilamentSpool.STATUS_CHOICES, initial='sealed')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _collapse_single_location(self)


class ReceiveEquipmentForm(StyledForm):
    name = forms.CharField(max_length=160)
    equipment_type = forms.ChoiceField(choices=Equipment.EQUIPMENT_TYPE_CHOICES, initial='printer')
    manufacturer = forms.CharField(max_length=120, required=False)
    model = forms.CharField(max_length=120, required=False)
    serial_number = forms.CharField(max_length=120, required=False)
    cost = forms.DecimalField(required=False, min_value=Decimal('0'))
    acquired_date = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    location = forms.ModelChoiceField(queryset=Location.objects.filter(is_active=True), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _collapse_single_location(self)


class LinkPaymentForm(StyledForm):
    """Link a purchase to an existing finance transaction."""
    transaction = forms.ModelChoiceField(
        queryset=Transaction.objects.filter(transaction_type='expense').order_by('-transaction_date')[:500],
        label='Existing finance expense')
    amount = forms.DecimalField(required=False, help_text='Defaults to the transaction amount.')
    note = forms.CharField(max_length=300, required=False)


class CreateExpenseForm(StyledForm):
    """Create exactly one finance expense for this purchase and link it."""
    account = forms.ModelChoiceField(queryset=Account.objects.filter(is_active=True))
    category = forms.ModelChoiceField(queryset=Category.objects.filter(category_type='expense', is_active=True))
    amount = forms.DecimalField(min_value=Decimal('0.01'))
    transaction_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    description = forms.CharField(max_length=500)


class WeighSpoolForm(StyledForm):
    gross_grams = forms.DecimalField(min_value=Decimal('0'), label='Scale reading (g)',
                                     help_text='Total weight: spool + remaining filament.')
    tare_grams = forms.DecimalField(min_value=Decimal('0'), label='Empty-spool weight (g)')
    note = forms.CharField(max_length=300, required=False)


# --------------------------------------------------------------------- printing
class PrintLogForm(StyledModelForm):
    class Meta:
        model = __import__('operations').models.PrintLog
        fields = ['name', 'printed_on', 'printer', 'purpose', 'outcome', 'is_historical', 'notes']
        widgets = {
            'printed_on': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }
        labels = {'is_historical': 'Historical (back-dated reconstruction)'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['printer'].required = False
        self.fields['printer'].queryset = Equipment.objects.filter(equipment_type='printer', status='active')


class PrintProductForm(StyledForm):
    """A product produced by a print (drives finished-goods output)."""
    variant = forms.ModelChoiceField(queryset=None, required=False, label='Product / variant')
    quantity_planned = forms.IntegerField(min_value=0, required=False, initial=0, label='Planned')
    quantity_success = forms.IntegerField(min_value=0, required=False, initial=0, label='Good units')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from operations.models import ProductVariant
        self.fields['variant'].queryset = ProductVariant.objects.filter(
            is_active=True, product__is_active=True).select_related('product')


class PrintMaterialUseForm(StyledForm):
    spool = forms.ModelChoiceField(queryset=FilamentSpool.objects.none(), required=False)
    grams_consumed = forms.DecimalField(min_value=Decimal('0'), required=False, initial=0,
                                        label='Into part (g)')
    waste_grams = forms.DecimalField(min_value=Decimal('0'), required=False, initial=0,
                                     label='Waste: purge/support (g)')
    basis = forms.ChoiceField(
        choices=[('recipe', 'Recipe estimate'), ('slicer', 'Slicer total'), ('measured', 'Measured')],
        initial='slicer', required=False, label='Source')
    all_inclusive = forms.BooleanField(required=False, label='Total already includes waste')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['spool'].queryset = FilamentSpool.objects.exclude(status='empty').select_related('material')


PrintMaterialUseFormSet = forms.formset_factory(PrintMaterialUseForm, extra=3)
PrintProductFormSet = forms.formset_factory(PrintProductForm, extra=3)


# --------------------------------------------------------------------- products & recipes
class PhysicalProductForm(StyledModelForm):
    class Meta:
        model = __import__('operations').models.PhysicalProduct
        fields = ['name', 'description', 'design_source', 'file_reference',
                  'internal_only', 'catalog_eligible']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 2}),
            'file_reference': forms.Textarea(attrs={'rows': 2}),
        }


class ProductVariantForm(StyledModelForm):
    class Meta:
        model = __import__('operations').models.ProductVariant
        fields = ['name', 'notes']


class RecipeMaterialForm(StyledForm):
    material = forms.ModelChoiceField(
        queryset=Material.objects.filter(material_type='filament', is_active=True),
        required=False, label='Filament')
    grams_per_unit = forms.DecimalField(min_value=Decimal('0'), required=False, initial=0,
                                        label='Into part /unit (g)')
    waste_per_unit = forms.DecimalField(min_value=Decimal('0'), required=False, initial=0,
                                        label='Waste /unit (g)')


RecipeMaterialFormSet = forms.formset_factory(RecipeMaterialForm, extra=3)


class RecipeForm(StyledForm):
    notes = forms.CharField(max_length=300, required=False,
                            help_text='What changed in this version (optional).')


# --------------------------------------------------------------------- internal orders
class InternalOrderForm(StyledModelForm):
    class Meta:
        model = __import__('operations').models.InternalOrder
        fields = ['purpose', 'ordered_on', 'notes']
        widgets = {
            'ordered_on': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }


class InternalOrderLineForm(StyledForm):
    variant = forms.ModelChoiceField(queryset=None, required=False, label='Product / variant')
    quantity = forms.IntegerField(min_value=1, required=False, initial=1)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from operations.models import ProductVariant
        self.fields['variant'].queryset = ProductVariant.objects.filter(
            is_active=True, product__is_active=True).select_related('product')


InternalOrderLineFormSet = forms.formset_factory(InternalOrderLineForm, extra=3)
