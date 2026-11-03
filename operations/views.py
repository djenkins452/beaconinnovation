"""Views for the admin-only Operations module (3D-printing).

Every view is gated by :func:`admin_required` (authenticated **and** ``is_active``
**and** ``is_superuser``; any non-admin — regular user or non-admin staff — gets a
404, so the internal area is never revealed). All state changes go through
``operations.services`` so audit, the ledger, idempotency and the finance bridge
are always honoured.
"""
import re
import uuid
from decimal import Decimal
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Prefetch, Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from finance.forms import validate_receipt_file
from operations import services
from operations.search import apply_search, search_terms
from operations.forms import (
    CreateExpenseForm, EquipmentForm, InternalOrderForm, InternalOrderLineFormSet,
    LinkPaymentForm, LocationForm, MaterialForm, OpeningSpoolForm, OpeningStockForm,
    PhysicalProductForm, PrintLogForm, PrintMaterialUseFormSet, PrintProductFormSet,
    ProductVariantForm, PurchaseEditForm, PurchaseForm, PurchaseLineEditForm, PurchaseLineForm,
    RecipeForm, RecipeMaterialFormSet, ReceiveEquipmentForm, ReceiveFilamentForm,
    ReceiveStockForm, SupplierForm, WeighSpoolForm,
)
from operations.models import (
    AuditEvent, Equipment, FilamentSpool, InternalOrder, InventoryMovement, Location,
    Material, PhysicalProduct, PrintLog, ProductionRecipe, ProductVariant, Purchase,
    PurchaseDocument, PurchaseLine, ScaleMeasurement, StockItem, Supplier,
)


def admin_required(view):
    """Administrators only: authenticated AND ``is_active`` AND ``is_superuser``.

    Unauthenticated → login redirect; any authenticated non-admin (including
    regular users and non-admin staff) → 404, so the internal area is never
    revealed. This gate backs every Operations view — pages, attachments and
    mutation endpoints alike — so server-side access always matches the nav.
    """
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not (request.user.is_active and request.user.is_superuser):
            raise Http404()
        return view(request, *args, **kwargs)
    return wrapper


# =============================================================================
# Dashboard
# =============================================================================

@admin_required
def dashboard(request):
    from django.db.models import Sum
    materials = list(Material.objects.filter(is_active=True))

    # 1) What do I own (confirmed on-hand only).
    owned = {
        'equipment': Equipment.objects.filter(status='active').count(),
        'stock_items': StockItem.objects.filter(status=StockItem.STATUS_AVAILABLE,
                                                delivery_confirmed=True).count(),
        'spools': FilamentSpool.objects.filter(delivery_confirmed=True).exclude(status='empty').count(),
    }
    produced = (InventoryMovement.objects.filter(movement_type='production_output')
                .aggregate(t=Sum('quantity'))['t'] or 0)
    owned['produced'] = int(produced)

    # Purchase summary — ACTIVE recorded total (excludes canceled orders/lines); not
    # profit / deductible / cash outflow. Original amounts stay visible in history.
    purchase_total = sum((p.active_order_total()
                          for p in Purchase.objects.prefetch_related('lines')), Decimal('0'))

    # 2) What is arriving / awaiting delivery confirmation.
    #    Build the fast-receive affordances here: each not-received line gets a one-click
    #    Receive (full outstanding by default; partial/refill via a small inline control),
    #    and each multi-line order gets a scoped "Receive remaining order" action. A fresh
    #    idempotency token per rendered form makes a double-click a safe no-op.
    from collections import OrderedDict
    all_lines = list(PurchaseLine.objects.select_related('purchase', 'purchase__supplier', 'material'))
    outstanding_lines, awaiting_lines, order_groups = [], [], OrderedDict()
    for ln in all_lines:
        state = ln.delivery_state
        if state == 'outstanding':
            quickable = ln.item_type in ('filament', 'stock')
            outstanding_lines.append({
                'ln': ln, 'quickable': quickable, 'is_filament': ln.item_type == 'filament',
                'is_equipment': ln.item_type == 'equipment',
                'outstanding': ln.quantity_outstanding, 'token': uuid.uuid4().hex,
            })
            if quickable:
                grp = order_groups.setdefault(ln.purchase_id, {
                    'purchase': ln.purchase, 'quick': 0, 'filament': 0, 'token': uuid.uuid4().hex})
                grp['quick'] += 1
                if ln.item_type == 'filament':
                    grp['filament'] += 1
        elif state == 'unconfirmed':
            awaiting_lines.append(ln)
    # Offer the whole-order button only where it saves clicks (2+ quick-receivable lines).
    receive_order_groups = [g for g in order_groups.values() if g['quick'] >= 2]

    # 3) Filament by colour/status; low spools vs spare stock; only real reorder flags.
    filament_rows = []
    for mat in [m for m in materials if m.is_filament]:
        counts = mat.filament_status_counts()
        if counts['total'] or counts['awaiting']:
            filament_rows.append({'m': mat, 'c': counts})
    low_spools = (FilamentSpool.objects.filter(status='low', delivery_confirmed=True)
                  .select_related('material'))
    reorder_materials = [m for m in materials if m.has_reorder_threshold and m.is_low_stock]
    any_thresholds = any(m.has_reorder_threshold for m in materials)

    # 4) What have I printed / what is in progress.
    in_progress_prints = PrintLog.objects.filter(outcome='in_progress').select_related('printer')
    recent_prints = PrintLog.objects.exclude(outcome='in_progress').select_related('printer')[:6]

    ctx = {
        'active_nav': 'dashboard',
        'owned': owned, 'purchase_total': purchase_total, 'purchase_count': Purchase.objects.count(),
        'outstanding_lines': outstanding_lines, 'awaiting_lines': awaiting_lines,
        'receive_order_groups': receive_order_groups,
        'filament_rows': filament_rows, 'low_spools': low_spools,
        'reorder_materials': reorder_materials, 'any_thresholds': any_thresholds,
        'in_progress_prints': in_progress_prints, 'recent_prints': recent_prints,
    }
    return render(request, 'operations/dashboard.html', ctx)


def _back_to_receiving():
    """Redirect back to the dashboard's receiving section (keeps the owner there)."""
    return redirect(reverse('operations:dashboard') + '#ops-receiving')


def _safe_next(request, default):
    """Redirect to a POSTed ``next`` path when it is safe and same-origin, otherwise to
    ``default`` (a response). Lets the dashboard's fast-receive endpoints be reused from
    the Purchases list and return the owner there — no second receiving code path."""
    nxt = (request.POST.get('next') or '').strip()
    if nxt and url_has_allowed_host_and_scheme(
            nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(nxt)
    return default


def _parse_optional_quantity(request):
    """A blank/absent quantity means 'receive the full outstanding amount'."""
    raw = (request.POST.get('quantity') or '').strip()
    if not raw:
        return None
    try:
        qty = Decimal(raw)
    except (ArithmeticError, ValueError):
        raise ValidationError('Enter a valid quantity.')
    if qty <= Decimal('0'):
        raise ValidationError('Quantity must be greater than zero.')
    return qty


@admin_required
def dashboard_receive_line(request, line_id):
    """Fast receive of one not-yet-received line, straight from the dashboard."""
    line = get_object_or_404(PurchaseLine.objects.select_related('purchase'), pk=line_id)
    if request.method == 'POST':
        try:
            result = services.quick_receive_line(
                line=line, actor=request.user,
                quantity=_parse_optional_quantity(request),
                is_refill=(request.POST.get('is_refill') == 'on'),
                idempotency_key=request.POST.get('idempotency_key') or None)
            if result['kind'] == 'filament':
                noun = 'refill' if result.get('is_refill') else 'spool'
                messages.success(request, f"Received {result['created']} {noun}"
                                          f"{'' if result['created'] == 1 else 's'} "
                                          f'(sealed, grams untracked). No expense created.')
            else:
                messages.success(request, f"Received {result['quantity']} {line.unit}. "
                                          'No expense created.')
        except ValidationError as e:
            messages.error(request, '; '.join(e.messages))
    return _safe_next(request, _back_to_receiving())


@admin_required
def dashboard_confirm_line(request, line_id):
    """Confirm an already-recorded (unconfirmed) delivery from the dashboard — uses the
    existing records, never creates duplicates."""
    line = get_object_or_404(PurchaseLine.objects.select_related('purchase'), pk=line_id)
    if request.method == 'POST':
        try:
            services.confirm_line_received(line=line, actor=request.user)
            messages.success(request, f'"{line.description}" confirmed received — now counted on hand.')
        except ValidationError as e:
            messages.error(request, '; '.join(e.messages))
    return _safe_next(request, _back_to_receiving())


@admin_required
def dashboard_receive_purchase(request, purchase_id):
    """Receive every remaining (not-received) filament/stock line on one order."""
    purchase = get_object_or_404(Purchase, pk=purchase_id)
    if request.method == 'POST':
        try:
            s = services.quick_receive_purchase(
                purchase=purchase, actor=request.user,
                is_refill=(request.POST.get('is_refill') == 'on'),
                idempotency_key=request.POST.get('idempotency_key') or None)
            parts = []
            if s['spools']:
                parts.append(f"{s['spools']} filament spool(s)")
            if s['stock_lines']:
                parts.append(f"{s['stock_lines']} stock line(s)")
            msg = ('Received ' + ', '.join(parts) + ' for this order. No expense created.'
                   if parts else 'Nothing left to receive on this order.')
            if s['skipped_equipment']:
                msg += (f" {s['skipped_equipment']} equipment line(s) skipped — receive "
                        'those individually with their details.')
            messages.success(request, msg)
        except ValidationError as e:
            messages.error(request, '; '.join(e.messages))
    return _safe_next(request, _back_to_receiving())


# =============================================================================
# Suppliers / Locations
# =============================================================================

@admin_required
def supplier_list(request):
    q = request.GET.get('q', '').strip()
    suppliers = apply_search(Supplier.objects.all(), q, ['name', 'website', 'notes'])
    return render(request, 'operations/supplier_list.html',
                  {'active_nav': 'suppliers', 'suppliers': suppliers, 'q': q, 'has_query': bool(q)})


@admin_required
def supplier_create(request):
    form = SupplierForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        supplier = form.save(commit=False)
        supplier.created_by = request.user
        supplier.save()
        services.record_audit(request.user, 'create', supplier, summary='Supplier created')
        messages.success(request, f'Supplier "{supplier.name}" added.')
        return redirect('operations:supplier_list')
    return render(request, 'operations/generic_form.html',
                  {'active_nav': 'suppliers', 'form': form, 'title': 'New supplier',
                   'cancel_url': reverse('operations:supplier_list')})


@admin_required
def location_list(request):
    q = request.GET.get('q', '').strip()
    locations = apply_search(Location.objects.all(), q, ['name', 'notes'])
    return render(request, 'operations/location_list.html',
                  {'active_nav': 'locations', 'locations': locations, 'q': q, 'has_query': bool(q)})


@admin_required
def location_create(request):
    form = LocationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        location = form.save()
        services.record_audit(request.user, 'create', location, summary='Location created')
        messages.success(request, f'Location "{location.name}" added.')
        return redirect('operations:location_list')
    return render(request, 'operations/generic_form.html',
                  {'active_nav': 'locations', 'form': form, 'title': 'New location',
                   'cancel_url': reverse('operations:location_list')})


# =============================================================================
# Materials
# =============================================================================

@admin_required
def material_list(request):
    qs = Material.objects.filter(is_active=True)
    mtype = request.GET.get('type', '')
    if mtype:
        qs = qs.filter(material_type=mtype)
    q = request.GET.get('q', '').strip()
    qs = apply_search(qs, q, ['manufacturer', 'product_type', 'name', 'sku', 'notes'])
    materials = list(qs)
    rows = []
    for m in materials:
        rows.append({
            'm': m,
            'on_hand': m.total_on_hand(),
            'low': m.is_low_stock,
            'counts': m.filament_status_counts() if m.is_filament else None,
        })
    return render(request, 'operations/material_list.html',
                  {'active_nav': 'materials', 'rows': rows, 'type_filter': mtype,
                   'type_choices': Material.MATERIAL_TYPE_CHOICES,
                   'q': q, 'has_query': bool(q), 'search_hidden': {'type': mtype}})


@admin_required
def material_create(request):
    form = MaterialForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        material = form.save(commit=False)
        material.created_by = request.user
        material.save()
        services.record_audit(request.user, 'create', material, summary='Material created')
        messages.success(request, f'Material "{material}" added.')
        return redirect('operations:material_list')
    return render(request, 'operations/generic_form.html',
                  {'active_nav': 'materials', 'form': form, 'title': 'New material',
                   'cancel_url': reverse('operations:material_list')})


@admin_required
def material_detail(request, material_id):
    material = get_object_or_404(Material, pk=material_id)
    ctx = {
        'active_nav': 'materials', 'material': material,
        'on_hand': material.total_on_hand(), 'low': material.is_low_stock,
        'spools': material.spools.all() if material.is_filament else None,
        'stock_items': (material.stock_items.all() if not material.is_filament else None),
    }
    return render(request, 'operations/material_detail.html', ctx)


# =============================================================================
# Spools + weigh-in / reconcile
# =============================================================================

@admin_required
def spool_list(request):
    spools = FilamentSpool.objects.select_related('material', 'location').all()
    status = request.GET.get('status', '')
    if status:
        spools = spools.filter(status=status)
    q = request.GET.get('q', '').strip()
    spools = apply_search(spools, q, [
        'spool_uid', 'material__manufacturer', 'material__product_type', 'material__name',
        'material__sku', 'location__name', 'notes'])
    # Open/low first, then sealed spare stock, then empty/damaged. Awaiting-delivery last.
    order = {'open': 0, 'low': 1, 'sealed': 2, 'damaged': 3, 'empty': 4}
    spools = sorted(spools, key=lambda s: (not s.delivery_confirmed, order.get(s.status, 9),
                                           s.material.name, s.spool_uid))
    rows = [{'s': s, 'est': s.estimated_remaining_g, 'measured': s.measured_remaining_g,
             'variance': s.variance_g} for s in spools]
    return render(request, 'operations/spool_list.html',
                  {'active_nav': 'spools', 'rows': rows, 'status_filter': status,
                   'status_choices': FilamentSpool.STATUS_CHOICES,
                   'q': q, 'has_query': bool(q), 'search_hidden': {'status': status}})


@admin_required
def spool_detail(request, spool_id):
    spool = get_object_or_404(FilamentSpool.objects.select_related('material', 'location'), pk=spool_id)
    weigh_form = WeighSpoolForm(initial={'tare_grams': spool.tare_weight_g or ''})
    ctx = {
        'active_nav': 'spools', 'spool': spool,
        'est': spool.estimated_remaining_g, 'measured': spool.measured_remaining_g,
        'variance': spool.variance_g,
        'status_choices': FilamentSpool.STATUS_CHOICES,
        'movements': spool.movements.select_related('actor').all(),
        'measurements': spool.measurements.all(),
        'weigh_form': weigh_form,
    }
    return render(request, 'operations/spool_detail.html', ctx)


@admin_required
def spool_set_status(request, spool_id):
    """Change a spool's status (open/low/empty/…) without weighing it."""
    spool = get_object_or_404(FilamentSpool, pk=spool_id)
    if request.method == 'POST':
        status = request.POST.get('status', '')
        try:
            services.set_spool_status(spool=spool, status=status, actor=request.user)
            messages.success(request, f'{spool.spool_uid} marked {spool.get_status_display()}.')
        except Exception as e:
            messages.error(request, f'Could not change status: {e}')
    return redirect('operations:spool_detail', spool_id=spool.id)


@admin_required
def spool_confirm_delivery(request, spool_id):
    spool = get_object_or_404(FilamentSpool, pk=spool_id)
    if request.method == 'POST':
        services.confirm_spool_delivery(spool=spool, actor=request.user)
        messages.success(request, f'{spool.spool_uid}: delivery confirmed — now counted as on hand.')
    return redirect('operations:spool_detail', spool_id=spool.id)


@admin_required
def stock_confirm_delivery(request, stock_id):
    item = get_object_or_404(StockItem, pk=stock_id)
    if request.method == 'POST':
        services.confirm_stock_delivery(stock_item=item, actor=request.user)
        messages.success(request, f'{item.material}: delivery confirmed.')
    return _safe_next(request, redirect('operations:stock_list'))


@admin_required
def spool_weigh(request, spool_id):
    spool = get_object_or_404(FilamentSpool, pk=spool_id)
    if request.method != 'POST':
        return redirect('operations:spool_detail', spool_id=spool.id)
    form = WeighSpoolForm(request.POST)
    if form.is_valid():
        try:
            m = services.weigh_spool(
                spool=spool, gross_grams=form.cleaned_data['gross_grams'],
                tare_grams=form.cleaned_data['tare_grams'], note=form.cleaned_data['note'],
                actor=request.user)
            messages.success(request, f'Weigh-in recorded: {m.net_g} g remaining (measured). '
                                      f'Estimate is {spool.estimated_remaining_g} g — reconcile to apply.')
        except ValidationError as e:
            messages.error(request, '; '.join(e.messages))
    else:
        messages.error(request, 'Could not record the weigh-in; check the values.')
    return redirect('operations:spool_detail', spool_id=spool.id)


@admin_required
def measurement_reconcile(request, measurement_id):
    measurement = get_object_or_404(ScaleMeasurement, pk=measurement_id)
    if request.method != 'POST':
        return redirect('operations:spool_detail', spool_id=measurement.spool_id)
    try:
        delta = services.reconcile_spool_from_measurement(measurement=measurement, actor=request.user)
        messages.success(request, f'Reconciled. Adjustment of {delta} g posted to the ledger.')
    except ValidationError as e:
        messages.error(request, '; '.join(e.messages))
    return redirect('operations:spool_detail', spool_id=measurement.spool_id)


# =============================================================================
# Stock + equipment
# =============================================================================

@admin_required
def stock_list(request):
    items = StockItem.objects.select_related('material', 'location').all()
    q = request.GET.get('q', '').strip()
    items = apply_search(items, q, [
        'material__manufacturer', 'material__product_type', 'material__name', 'material__sku',
        'location__name', 'notes'])
    confirmed, awaiting = [], []
    for i in items:
        row = {'i': i, 'on_hand': i.on_hand}
        (awaiting if i.awaiting_confirmation else confirmed).append(row)
    return render(request, 'operations/stock_list.html',
                  {'active_nav': 'stock', 'confirmed': confirmed, 'awaiting': awaiting,
                   'q': q, 'has_query': bool(q)})


@admin_required
def equipment_list(request):
    q = request.GET.get('q', '').strip()
    equipment = apply_search(Equipment.objects.all(), q,
                             ['name', 'manufacturer', 'model', 'serial_number', 'notes'])
    return render(request, 'operations/equipment_list.html',
                  {'active_nav': 'equipment', 'equipment': equipment, 'q': q, 'has_query': bool(q)})


@admin_required
def equipment_create(request):
    form = EquipmentForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        equipment = form.save(commit=False)
        equipment.created_by = request.user
        equipment.save()
        services.record_audit(request.user, 'create', equipment, summary='Equipment created')
        messages.success(request, f'Equipment "{equipment.name}" added.')
        return redirect('operations:equipment_list')
    return render(request, 'operations/generic_form.html',
                  {'active_nav': 'equipment', 'form': form, 'title': 'New equipment',
                   'cancel_url': reverse('operations:equipment_list')})


# =============================================================================
# Opening inventory (never creates a finance expense)
# =============================================================================

@admin_required
def opening_index(request):
    return render(request, 'operations/opening_index.html', {'active_nav': 'opening'})


@admin_required
def opening_spool(request):
    form = OpeningSpoolForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        try:
            spool = services.enter_opening_spool(
                material=d['material'], spool_uid=d['spool_uid'],
                starting_weight_g=d.get('starting_weight_g') or 0,
                remaining_unknown=d.get('remaining_unknown', False),
                is_refill=d.get('is_refill', False),
                tare_weight_g=d['tare_weight_g'],
                cost=d['cost'], cost_unknown=d['cost_unknown'], location=d['location'],
                status=d['status'], notes=d['notes'], actor=request.user)
            messages.success(request, f'Opening spool "{spool.spool_uid}" added '
                                      f'({spool.remaining_display}; no expense created).')
            return redirect('operations:spool_detail', spool_id=spool.id)
        except Exception as e:
            messages.error(request, f'Could not add spool: {e}')
    return render(request, 'operations/generic_form.html',
                  {'active_nav': 'opening', 'form': form, 'title': 'Add a filament spool you own',
                   'intro': 'Grams are optional — leave “remaining unknown” ticked to track this spool by '
                            'status only (sealed / open / low / empty). Adding it does not create a finance expense.',
                   'cancel_url': reverse('operations:opening_index')})


@admin_required
def opening_stock(request):
    form = OpeningStockForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        try:
            item = services.enter_opening_stock(
                material=d['material'], quantity=d['quantity'], unit=d['unit'],
                location=d['location'], status=d['status'], notes=d['notes'], actor=request.user)
            messages.success(request, f'Opening stock for "{item.material}" set to {item.on_hand} '
                                      f'{item.unit} (no expense created).')
            return redirect('operations:stock_list')
        except Exception as e:
            messages.error(request, f'Could not add stock: {e}')
    return render(request, 'operations/generic_form.html',
                  {'active_nav': 'opening', 'form': form, 'title': 'Opening inventory — supplies',
                   'intro': 'Enter hardware/consumables/packaging you already own. No finance expense '
                            'is created.',
                   'cancel_url': reverse('operations:opening_index')})


# =============================================================================
# Purchases
# =============================================================================

def _order_badge(purchase, states):
    """Derive the whole-order receiving badge from its live lines' states — same rule
    as :attr:`Purchase.receiving_status`, computed here from statuses we already have so
    the list never evaluates a line's status twice."""
    if purchase.is_cancelled:
        return 'cancelled'
    if not states:
        return 'empty'
    s = set(states)
    if s == {'received'}:
        return 'received'
    if s <= {'outstanding'}:
        return 'none'
    if s <= {'unconfirmed'}:
        return 'unconfirmed'
    return 'partial'


def _catalog_adds_info(desc, catalog):
    """Show the catalog material name as a sub-note only when it adds information — i.e.
    it is not a near-duplicate of the line description. Compares word sets and hides the
    catalog when ≥80% of its words already appear in the description (so 'Bambu Lab PLA
    Basic Cyan' under 'Bambu PLA Basic Cyan (1 kg refill)' is suppressed, but a genuinely
    different catalog name is still shown)."""
    if not catalog:
        return False
    tokens = lambda s: {t for t in re.split(r'[^a-z0-9]+', s.lower()) if len(t) > 1}
    ct = tokens(catalog)
    if not ct:
        return False
    dt = tokens(desc)
    if not dt:
        return True
    return (len(ct & dt) / len(ct)) < 0.8


# Fields searched on the Purchases list (supplier, order number, item descriptions,
# catalog/material name + SKU, and order notes) — see operations.search.apply_search.
PURCHASE_SEARCH_FIELDS = [
    'supplier__name', 'supplier_name', 'order_number', 'notes',
    'lines__description', 'lines__material__manufacturer', 'lines__material__product_type',
    'lines__material__name', 'lines__material__sku',
]


def _attach_item_rows(purchase, terms=()):
    """Attach compact per-item rows + a derived order badge to a purchase for the list.

    Mirrors the dashboard's fast-receive affordances by reusing its endpoints/services:
    each not-received filament/stock line is quick-receivable, each line's receiving
    status is computed exactly once (no extra query per rendered row), and a whole-order
    'receive remaining' is offered when 2+ lines are quick-receivable.

    When ``terms`` (lowercase search words) are given, a line is flagged as matching so the
    template can point out which item(s) in a multi-item order matched — computed in Python
    from text already loaded, so it adds no query per row.
    """
    rows, quick_count, quick_filament, states = [], 0, False, []
    for ln in purchase.lines.all():
        status = ln.receiving_status
        catalog = str(ln.material) if ln.material else ''
        desc = ln.description or catalog or ln.get_item_type_display()
        quickable = status == 'outstanding' and ln.item_type in ('filament', 'stock')
        match = False
        if terms:
            haystack = ('%s %s %s' % (desc, catalog, ln.material.sku if ln.material else '')).lower()
            match = any(t in haystack for t in terms)
        rows.append({
            'ln': ln, 'status': status,
            'label': PurchaseLine.RECEIVING_LABELS.get(status, 'Not received'),
            'desc': desc, 'catalog': catalog, 'show_catalog': _catalog_adds_info(desc, catalog),
            'quickable': quickable, 'match': match,
            'is_filament': ln.item_type == 'filament', 'is_equipment': ln.item_type == 'equipment',
            'is_outstanding': status == 'outstanding', 'is_unconfirmed': status == 'unconfirmed',
            'is_cancelled': status == 'cancelled', 'is_received': status == 'received',
            'outstanding': ln.quantity_outstanding, 'token': uuid.uuid4().hex,
        })
        if ln.item_type != 'other' and not ln.is_cancelled:
            states.append(status)
        if quickable:
            quick_count += 1
            quick_filament = quick_filament or ln.item_type == 'filament'
    purchase.item_rows = rows
    purchase.order_status = _order_badge(purchase, states)
    purchase.quick_group = ({'token': uuid.uuid4().hex, 'count': quick_count,
                             'filament': quick_filament} if quick_count >= 2 else None)


@admin_required
def purchase_list(request):
    base = (Purchase.objects.select_related('supplier')
            .prefetch_related(
                Prefetch('lines', queryset=PurchaseLine.objects.select_related('material')),
                'lines__spools', 'lines__movements__stock_item', 'payments'))
    # Overall recorded cost is always the WHOLE authorized dataset — searching narrows which
    # orders are listed, it must never look like it changed the recorded acquisition cost.
    total_recorded = sum((p.active_order_total() for p in base.all()), Decimal('0'))
    total_count = base.count()
    cancelled_count = sum(1 for p in base.all() if p.is_cancelled)

    q = request.GET.get('q', '').strip()
    purchases = apply_search(base, q, PURCHASE_SEARCH_FIELDS)
    match_count = purchases.count() if q else total_count

    paginator = Paginator(purchases, 25)
    page = paginator.get_page(request.GET.get('page'))
    terms = search_terms(q)
    # Compact item rows + fast-receive affordances for the orders on THIS page only.
    for p in page.object_list:
        _attach_item_rows(p, terms)
    return render(request, 'operations/purchase_list.html',
                  {'active_nav': 'purchases', 'page': page, 'total_recorded': total_recorded,
                   'total_count': total_count, 'match_count': match_count,
                   'cancelled_count': cancelled_count, 'q': q, 'has_query': bool(q),
                   'next_url': request.get_full_path()})


@admin_required
def purchase_create(request):
    form = PurchaseForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        purchase = form.save(commit=False)
        purchase.created_by = request.user
        purchase.save()
        services.record_audit(request.user, 'create', purchase, summary='Purchase created')
        messages.success(request, 'Purchase created. Now add lines for what you ordered.')
        return redirect('operations:purchase_detail', purchase_id=purchase.id)
    return render(request, 'operations/generic_form.html',
                  {'active_nav': 'purchases', 'form': form, 'title': 'Record a purchase',
                   'cancel_url': reverse('operations:purchase_list')})


@admin_required
def purchase_detail(request, purchase_id):
    purchase = get_object_or_404(
        Purchase.objects.select_related('supplier').prefetch_related('lines', 'payments', 'documents'),
        pk=purchase_id)
    line_form = PurchaseLineForm()
    link_form = LinkPaymentForm()
    expense_form = CreateExpenseForm(initial={'amount': purchase.order_total(),
                                              'transaction_date': purchase.order_date,
                                              'description': f'Purchase {purchase}'})
    lines = list(purchase.lines.select_related('material').all())
    receivable = [ln for ln in lines if ln.item_type != 'other']
    # The whole order can be cancelled only when nothing on it has been received and
    # there is still a live (not already cancelled) line to cancel.
    can_cancel_order = (not purchase.is_cancelled and not purchase.has_received_inventory
                        and any(not ln.is_cancelled for ln in receivable))
    ctx = {
        'active_nav': 'purchases', 'purchase': purchase,
        'lines': lines,
        'payments': purchase.payments.select_related('transaction').all(),
        'documents': purchase.documents.all(),
        'line_form': line_form, 'link_form': link_form, 'expense_form': expense_form,
        'linked_total': purchase.linked_payment_total(),
        'can_cancel_order': can_cancel_order,
        'has_linked_payments': purchase.payments.exists(),
    }
    return render(request, 'operations/purchase_detail.html', ctx)


@admin_required
def purchase_edit(request, purchase_id):
    """Edit a purchase's header (supplier, dates, order number, order-level
    shipping/tax/discount, notes, funding). Never receives inventory, creates a
    payment, or creates a finance expense; documents and payment links are kept."""
    purchase = get_object_or_404(Purchase.objects.select_related('supplier'), pk=purchase_id)
    form = PurchaseEditForm(request.POST or None, instance=purchase)
    if request.method == 'POST' and form.is_valid():
        # Validation mutates form.instance in place, so hand the service a fresh copy
        # to compare against (keeps the audit diff of old → new honest).
        fresh = Purchase.objects.get(pk=purchase.pk)
        services.edit_purchase(purchase=fresh, actor=request.user, **form.cleaned_data)
        messages.success(request, 'Purchase updated. No inventory received, no payment or expense created.')
        return redirect('operations:purchase_detail', purchase_id=purchase.id)
    return render(request, 'operations/purchase_edit.html',
                  {'active_nav': 'purchases', 'form': form, 'purchase': purchase,
                   'has_payments': purchase.payments.exists()})


@admin_required
def line_edit(request, line_id):
    """Edit a purchase line. Cost/tax/discount/classification/description are always
    editable; structural fields (item type, material, unit) are locked once the line
    has been received. The service layer enforces the protection too."""
    line = get_object_or_404(
        PurchaseLine.objects.select_related('purchase', 'material'), pk=line_id)
    form = PurchaseLineEditForm(request.POST or None, instance=line)
    if request.method == 'POST' and form.is_valid():
        try:
            # Validation mutates form.instance in place, so hand the service a fresh
            # copy to compare against (keeps the audit diff of old → new honest).
            fresh = PurchaseLine.objects.select_related('purchase').get(pk=line.pk)
            services.edit_purchase_line(line=fresh, actor=request.user, **form.cleaned_data)
            if fresh.purchase.payments.exists():
                messages.warning(request, 'Line updated. A Finance expense is linked to this '
                                          'purchase — its amount was NOT changed automatically; '
                                          'adjust it in Finance if needed.')
            else:
                messages.success(request, 'Line updated. No inventory movement, payment, or expense changed.')
            return redirect('operations:purchase_detail', purchase_id=line.purchase_id)
        except ValidationError as e:
            for msg in e.messages:
                form.add_error(None, msg)
    return render(request, 'operations/line_edit.html',
                  {'active_nav': 'purchases', 'form': form, 'line': line,
                   'received': getattr(form, 'received', False)})


@admin_required
def line_mark_not_received(request, line_id):
    """Mark one line NOT received (undo an assumed/unconfirmed delivery). Safe,
    audited, history-preserving; never touches costs, payments, or documents."""
    line = get_object_or_404(PurchaseLine.objects.select_related('purchase'), pk=line_id)
    if request.method == 'POST':
        try:
            services.mark_line_not_received(line=line, actor=request.user)
            messages.success(request, f'"{line.description}" marked not received. '
                                      'Costs, funding, payments and documents are unchanged.')
        except ValidationError as e:
            messages.error(request, '; '.join(e.messages))
    return redirect('operations:purchase_detail', purchase_id=line.purchase_id)


@admin_required
def line_confirm_received(request, line_id):
    """Confirm one line's delivery actually arrived (counts its inventory on-hand)."""
    line = get_object_or_404(PurchaseLine.objects.select_related('purchase'), pk=line_id)
    if request.method == 'POST':
        try:
            services.confirm_line_received(line=line, actor=request.user)
            messages.success(request, f'"{line.description}" confirmed received — now counted on hand.')
        except ValidationError as e:
            messages.error(request, '; '.join(e.messages))
    return redirect('operations:purchase_detail', purchase_id=line.purchase_id)


@admin_required
def purchase_mark_not_received(request, purchase_id):
    """Mark the whole order NOT received (every receivable line)."""
    purchase = get_object_or_404(Purchase, pk=purchase_id)
    if request.method == 'POST':
        try:
            n = services.mark_purchase_not_received(purchase=purchase, actor=request.user)
            messages.success(request, f'Whole order marked not received ({n} line(s)). '
                                      'Costs, funding, payments and documents are unchanged.')
        except ValidationError as e:
            messages.error(request, '; '.join(e.messages))
    return redirect('operations:purchase_detail', purchase_id=purchase.id)


@admin_required
def purchase_confirm_received(request, purchase_id):
    """Confirm delivery of the whole order (every line with something recorded)."""
    purchase = get_object_or_404(Purchase, pk=purchase_id)
    if request.method == 'POST':
        try:
            n = services.confirm_purchase_received(purchase=purchase, actor=request.user)
            messages.success(request, f'Whole order confirmed received ({n} line(s)) — now counted on hand.')
        except ValidationError as e:
            messages.error(request, '; '.join(e.messages))
    return redirect('operations:purchase_detail', purchase_id=purchase.id)


@admin_required
def purchase_cancel(request, purchase_id):
    """Cancel a whole order (e.g. the supplier confirmed cancellation). Only valid when
    nothing has been received; preserves prices/documents/history, excludes it from
    active totals, implies no refund, and flags any linked Finance payment for review."""
    purchase = get_object_or_404(Purchase, pk=purchase_id)
    if request.method == 'POST':
        try:
            result = services.cancel_purchase(
                purchase=purchase, actor=request.user,
                reason=(request.POST.get('reason') or '').strip())
            if result.get('already'):
                messages.info(request, 'This order was already canceled.')
            else:
                msg = (f"Order canceled ({result['lines']} line(s)). The original order, "
                       'prices and documents are preserved and it is excluded from active '
                       'acquisition-cost totals. No refund is implied.')
                if result['linked_payments']:
                    msg += (f" Note: {result['linked_payments']} linked Finance payment(s) "
                            'were NOT changed — review them in Finance if a refund is due.')
                messages.success(request, msg)
        except ValidationError as e:
            messages.error(request, '; '.join(e.messages))
    return redirect('operations:purchase_detail', purchase_id=purchase.id)


@admin_required
def line_cancel(request, line_id):
    """Cancel one outstanding line (for partially received orders). Refuses a line with
    received inventory — mark it not received first. Never touches costs/payments/docs."""
    line = get_object_or_404(PurchaseLine.objects.select_related('purchase'), pk=line_id)
    if request.method == 'POST':
        try:
            services.cancel_line(line=line, actor=request.user,
                                 reason=(request.POST.get('reason') or '').strip())
            messages.success(request, f'"{line.description}" canceled. Costs, funding, payments '
                                      'and documents are unchanged; it can no longer be received.')
        except ValidationError as e:
            messages.error(request, '; '.join(e.messages))
    return redirect('operations:purchase_detail', purchase_id=line.purchase_id)


@admin_required
def purchase_add_line(request, purchase_id):
    purchase = get_object_or_404(Purchase, pk=purchase_id)
    if request.method == 'POST':
        form = PurchaseLineForm(request.POST)
        if form.is_valid():
            line = form.save(commit=False)
            line.purchase = purchase
            line.full_clean()
            line.save()
            services.record_audit(request.user, 'create', line, summary='Purchase line added')
            messages.success(request, 'Line added.')
        else:
            messages.error(request, 'Could not add line: ' + '; '.join(
                f'{k}: {", ".join(v)}' for k, v in form.errors.items()))
    return redirect('operations:purchase_detail', purchase_id=purchase.id)


@admin_required
def line_receive(request, line_id):
    line = get_object_or_404(PurchaseLine.objects.select_related('purchase', 'material'), pk=line_id)
    if line.item_type == 'filament':
        form_class, kind = ReceiveFilamentForm, 'filament'
    elif line.item_type == 'stock':
        form_class, kind = ReceiveStockForm, 'stock'
    elif line.item_type == 'equipment':
        form_class, kind = ReceiveEquipmentForm, 'equipment'
    else:
        messages.info(request, 'This line has nothing to receive into inventory.')
        return redirect('operations:purchase_detail', purchase_id=line.purchase_id)

    if request.method == 'POST':
        form = form_class(request.POST)
        token = request.POST.get('idempotency_key') or ''
        if form.is_valid():
            d = form.cleaned_data
            try:
                if kind == 'filament':
                    specs = [{
                        'spool_uid': f"{d['uid_prefix']}-{i+1}",
                        'starting_weight_g': d['starting_weight_g'],
                        'tare_weight_g': d['tare_weight_g'], 'cost': d['cost_each'],
                        'cost_unknown': d['cost_each'] is None, 'status': d['status'],
                    } for i in range(d['count'])]
                    services.receive_filament_line(line=line, spool_specs=specs,
                                                   location=d['location'], actor=request.user,
                                                   idempotency_key=token or None)
                    messages.success(request, f"Received {d['count']} spool(s). Inventory updated; "
                                              f"no expense created.")
                elif kind == 'stock':
                    services.receive_stock_line(line=line, quantity=d['quantity'],
                                                location=d['location'], status=d['status'],
                                                actor=request.user, idempotency_key=token or None)
                    messages.success(request, f"Received {d['quantity']} {line.unit}. No expense created.")
                else:  # equipment
                    services.receive_equipment_line(
                        line=line, actor=request.user, name=d['name'],
                        equipment_type=d['equipment_type'], location=d['location'],
                        manufacturer=d['manufacturer'], model=d['model'],
                        serial_number=d['serial_number'], cost=d['cost'],
                        cost_unknown=d['cost'] is None, acquired_date=d['acquired_date'])
                    messages.success(request, 'Equipment recorded as an asset (not stock); no expense created.')
                return redirect('operations:purchase_detail', purchase_id=line.purchase_id)
            except ValidationError as e:
                messages.error(request, '; '.join(e.messages))
        else:
            messages.error(request, 'Please correct the form.')
    else:
        form = form_class(initial={'quantity': line.quantity_outstanding})

    return render(request, 'operations/line_receive.html',
                  {'active_nav': 'purchases', 'line': line, 'form': form, 'kind': kind,
                   'idempotency_key': uuid.uuid4().hex})


@admin_required
def purchase_link_payment(request, purchase_id):
    purchase = get_object_or_404(Purchase, pk=purchase_id)
    if request.method == 'POST':
        form = LinkPaymentForm(request.POST)
        if form.is_valid():
            try:
                services.link_payment(purchase=purchase, transaction_obj=form.cleaned_data['transaction'],
                                      amount=form.cleaned_data['amount'], note=form.cleaned_data['note'],
                                      actor=request.user)
                messages.success(request, 'Linked purchase to the finance transaction.')
            except Exception as e:
                messages.error(request, f'Could not link: {e}')
        else:
            messages.error(request, 'Please select a transaction.')
    return redirect('operations:purchase_detail', purchase_id=purchase.id)


@admin_required
def purchase_create_expense(request, purchase_id):
    purchase = get_object_or_404(Purchase, pk=purchase_id)
    if request.method == 'POST':
        form = CreateExpenseForm(request.POST)
        if form.is_valid():
            d = form.cleaned_data
            try:
                txn, _ = services.create_expense_for_purchase(
                    purchase=purchase, account=d['account'], category=d['category'],
                    amount=d['amount'], transaction_date=d['transaction_date'],
                    description=d['description'], actor=request.user)
                messages.success(request, f'Created one finance expense (${txn.amount}) and linked it.')
            except Exception as e:
                messages.error(request, f'Could not create expense: {e}')
        else:
            messages.error(request, 'Please correct the expense form.')
    return redirect('operations:purchase_detail', purchase_id=purchase.id)


# =============================================================================
# Purchase documents (private, DB-backed — reuses finance storage)
# =============================================================================

@admin_required
def purchase_upload_document(request, purchase_id):
    purchase = get_object_or_404(Purchase, pk=purchase_id)
    if request.method == 'POST' and 'file' in request.FILES:
        validation = validate_receipt_file(request.FILES['file'])
        if not validation['valid']:
            messages.error(request, validation['error'])
        else:
            doc = PurchaseDocument.objects.create(
                purchase=purchase, file=request.FILES['file'],
                original_filename=validation['original_filename'],
                file_type=validation['file_type'], file_size=validation['file_size'],
                uploaded_by=request.user)
            services.record_audit(request.user, 'create', doc, summary='Purchase document uploaded')
            messages.success(request, 'Document attached.')
    else:
        messages.error(request, 'No file was selected.')
    return redirect('operations:purchase_detail', purchase_id=purchase.id)


def _serve_document(request, document_id, disposition):
    doc = get_object_or_404(PurchaseDocument, pk=document_id)
    content_type_map = {'pdf': 'application/pdf', 'jpg': 'image/jpeg', 'png': 'image/png'}
    content_type = content_type_map.get(doc.file_type, 'application/octet-stream')
    try:
        response = FileResponse(doc.file.open('rb'), content_type=content_type)
    except FileNotFoundError:
        raise Http404('Document file not found')
    response['Content-Disposition'] = f'{disposition}; filename="{doc.original_filename}"'
    return response


@admin_required
def document_view(request, document_id):
    return _serve_document(request, document_id, 'inline')


@admin_required
def document_download(request, document_id):
    return _serve_document(request, document_id, 'attachment')


# =============================================================================
# Printing
# =============================================================================

@admin_required
def print_list(request):
    prints = PrintLog.objects.select_related('printer').all()
    q = request.GET.get('q', '').strip()
    prints = apply_search(prints, q, [
        'name', 'printer__name', 'notes', 'products__variant__name',
        'products__variant__product__name'])
    paginator = Paginator(prints, 25)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'operations/print_list.html',
                  {'active_nav': 'prints', 'page': page, 'q': q, 'has_query': bool(q)})


@admin_required
def print_create(request):
    if request.method == 'POST':
        form = PrintLogForm(request.POST)
        formset = PrintMaterialUseFormSet(request.POST, prefix='use')
        pformset = PrintProductFormSet(request.POST, prefix='prod')
        token = request.POST.get('submission_token') or None
        fulfill_internal = request.POST.get('fulfill_internal') == 'on'
        fulfill_purpose = request.POST.get('fulfill_purpose') or 'personal'
        if form.is_valid() and formset.is_valid() and pformset.is_valid():
            uses = []
            for f in formset:
                spool = f.cleaned_data.get('spool')
                gc = f.cleaned_data.get('grams_consumed') or 0
                wg = f.cleaned_data.get('waste_grams') or 0
                if spool and (gc or wg):
                    uses.append({'spool': spool, 'grams_consumed': gc, 'waste_grams': wg,
                                 'basis': f.cleaned_data.get('basis'),
                                 'all_inclusive': f.cleaned_data.get('all_inclusive')})
            products = []
            for pf in pformset:
                variant = pf.cleaned_data.get('variant')
                qp = pf.cleaned_data.get('quantity_planned') or 0
                qs = pf.cleaned_data.get('quantity_success') or 0
                if variant and (qp or qs):
                    products.append({'variant': variant, 'recipe': variant.current_recipe,
                                     'quantity_planned': qp, 'quantity_success': qs})
            try:
                d = form.cleaned_data
                print_log = services.log_print(
                    name=d['name'], printer=d['printer'], purpose=d['purpose'],
                    outcome=d['outcome'], is_historical=d['is_historical'],
                    notes=d['notes'], printed_on=d['printed_on'], uses=uses,
                    products=products, actor=request.user, submission_token=token)
                msg = (f'Print "{print_log.name}" logged; {print_log.total_filament_g} g '
                       f'deducted (incl. {print_log.total_waste_g} g waste).')
                # Optional: immediately fulfill the successful units as an internal order.
                if fulfill_internal:
                    lines = [{'variant': p['variant'], 'quantity': p['quantity_success']}
                             for p in products if p['quantity_success'] > 0]
                    if lines:
                        occurred = services._historical_timestamp(d['printed_on']) if d['is_historical'] else None
                        order = services.create_and_fulfill_internal_order(
                            purpose=fulfill_purpose, lines=lines, actor=request.user,
                            notes=f'Auto from print: {print_log.name}',
                            ordered_on=d['printed_on'], occurred_at=occurred)
                        msg += f' Internal order fulfilled (no payment) — finished units removed.'
                messages.success(request, msg)
                return redirect('operations:print_detail', print_id=print_log.id)
            except ValidationError as e:
                messages.error(request, '; '.join(e.messages))
        else:
            messages.error(request, 'Please correct the print form.')
    else:
        form = PrintLogForm()
        formset = PrintMaterialUseFormSet(prefix='use')
        pformset = PrintProductFormSet(prefix='prod')
    return render(request, 'operations/print_form.html',
                  {'active_nav': 'prints', 'form': form, 'formset': formset,
                   'pformset': pformset, 'submission_token': uuid.uuid4().hex,
                   'purpose_choices': InternalOrder.PURPOSE_CHOICES})


@admin_required
def print_detail(request, print_id):
    print_log = get_object_or_404(PrintLog.objects.select_related('printer'), pk=print_id)
    return render(request, 'operations/print_detail.html',
                  {'active_nav': 'prints', 'print_log': print_log,
                   'uses': print_log.material_uses.select_related('spool').all(),
                   'products': print_log.products.select_related('variant', 'variant__product').all()})


@admin_required
def recipe_expected(request):
    """JSON: expected per-material consumption for a variant + quantity (recipe
    prefill for the print form). Returns [] when the variant has no current recipe."""
    variant_id = request.GET.get('variant')
    try:
        qty = int(request.GET.get('qty') or 1)
    except ValueError:
        qty = 1
    rows = []
    variant = ProductVariant.objects.filter(pk=variant_id).first() if variant_id else None
    if variant and variant.current_recipe:
        for r in variant.current_recipe.expected_for(qty):
            rows.append({'material': str(r['material']),
                         'grams_consumed': str(r['grams_consumed']),
                         'waste_grams': str(r['waste_grams'])})
    return JsonResponse({'rows': rows})


# =============================================================================
# Inventory history (movements) + corrections
# =============================================================================

@admin_required
def movement_list(request):
    movements = InventoryMovement.objects.select_related(
        'spool', 'spool__material', 'stock_item', 'stock_item__material',
        'product_variant', 'product_variant__product', 'actor', 'reverses').all()
    mtype = request.GET.get('type', '')
    if mtype:
        movements = movements.filter(movement_type=mtype)
    q = request.GET.get('q', '').strip()
    movements = apply_search(movements, q, [
        'reason', 'spool__spool_uid', 'spool__material__name', 'stock_item__material__name',
        'product_variant__name', 'product_variant__product__name'])
    paginator = Paginator(movements, 50)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'operations/movement_list.html',
                  {'active_nav': 'history', 'page': page, 'type_filter': mtype, 'q': q,
                   'has_query': bool(q), 'search_hidden': {'type': mtype},
                   'type_choices': InventoryMovement.MOVEMENT_TYPE_CHOICES})


@admin_required
def movement_reverse(request, movement_id):
    movement = get_object_or_404(InventoryMovement, pk=movement_id)
    if request.method != 'POST':
        return redirect('operations:movement_list')
    reason = request.POST.get('reason', '').strip()
    try:
        rev = services.reverse_movement(movement, actor=request.user, reason=reason)
        messages.success(request, f'Posted a reversing movement ({rev.quantity} {rev.unit}). '
                                  f'The original entry is preserved.')
    except ValidationError as e:
        messages.error(request, '; '.join(e.messages))
    return redirect('operations:movement_list')


# =============================================================================
# Physical products, variants, recipes
# =============================================================================

@admin_required
def product_list(request):
    products = PhysicalProduct.objects.filter(is_active=True).prefetch_related('variants')
    q = request.GET.get('q', '').strip()
    products = apply_search(products, q, ['name', 'description', 'variants__name', 'variants__notes'])
    rows = [{'p': p, 'on_hand': p.total_on_hand, 'variants': p.variants.count()} for p in products]
    return render(request, 'operations/product_list.html',
                  {'active_nav': 'products', 'rows': rows, 'q': q, 'has_query': bool(q)})


@admin_required
def product_create(request):
    form = PhysicalProductForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        product = form.save(commit=False)
        product.created_by = request.user
        product.save()
        # Every product starts with a Default variant so it is printable at once.
        variant = ProductVariant.objects.create(product=product, name='Default')
        services.record_audit(request.user, 'create', product, summary='Physical product created')
        messages.success(request, f'Product "{product.name}" created with a Default variant. '
                                  f'Add a print recipe next.')
        return redirect('operations:product_detail', product_id=product.id)
    return render(request, 'operations/generic_form.html',
                  {'active_nav': 'products', 'form': form, 'title': 'New physical product',
                   'intro': 'A distinct printed design (including internal-only items like bins, '
                            'swatches, printer accessories).',
                   'cancel_url': reverse('operations:product_list')})


@admin_required
def product_detail(request, product_id):
    product = get_object_or_404(PhysicalProduct.objects.prefetch_related('variants'), pk=product_id)
    variants = []
    for v in product.variants.all():
        variants.append({'v': v, 'on_hand': v.on_hand, 'recipe': v.current_recipe})
    return render(request, 'operations/product_detail.html',
                  {'active_nav': 'products', 'product': product, 'variants': variants,
                   'variant_form': ProductVariantForm()})


@admin_required
def variant_create(request, product_id):
    product = get_object_or_404(PhysicalProduct, pk=product_id)
    if request.method == 'POST':
        form = ProductVariantForm(request.POST)
        if form.is_valid():
            variant = form.save(commit=False)
            variant.product = product
            try:
                variant.full_clean()
                variant.save()
                services.record_audit(request.user, 'create', variant, summary='Variant created')
                messages.success(request, f'Variant "{variant.name}" added.')
            except ValidationError as e:
                messages.error(request, '; '.join(f'{k}: {", ".join(v)}' for k, v in e.message_dict.items()))
        else:
            messages.error(request, 'Please correct the variant form.')
    return redirect('operations:product_detail', product_id=product.id)


@admin_required
def recipe_create(request, variant_id):
    variant = get_object_or_404(ProductVariant.objects.select_related('product'), pk=variant_id)
    if request.method == 'POST':
        form = RecipeForm(request.POST)
        formset = RecipeMaterialFormSet(request.POST, prefix='mat')
        if form.is_valid() and formset.is_valid():
            materials = []
            for f in formset:
                material = f.cleaned_data.get('material')
                if material:
                    materials.append({'material': material,
                                      'grams_per_unit': f.cleaned_data.get('grams_per_unit') or 0,
                                      'waste_per_unit': f.cleaned_data.get('waste_per_unit') or 0})
            if not materials:
                messages.error(request, 'Add at least one filament line to the recipe.')
            else:
                recipe = services.create_recipe_version(
                    variant=variant, materials=materials, notes=form.cleaned_data['notes'],
                    actor=request.user)
                messages.success(request, f'Recipe v{recipe.version} saved for {variant}.')
                return redirect('operations:product_detail', product_id=variant.product_id)
        else:
            messages.error(request, 'Please correct the recipe form.')
    else:
        form = RecipeForm()
        formset = RecipeMaterialFormSet(prefix='mat')
    return render(request, 'operations/recipe_form.html',
                  {'active_nav': 'products', 'variant': variant, 'form': form, 'formset': formset,
                   'current': variant.current_recipe})


# =============================================================================
# Finished goods
# =============================================================================

@admin_required
def finished_goods(request):
    from django.db.models import Sum
    variants = ProductVariant.objects.select_related('product').all()
    q = request.GET.get('q', '').strip()
    variants = apply_search(variants, q, ['name', 'product__name', 'notes'])
    rows = []
    for v in variants:
        produced = (v.movements.filter(movement_type='production_output')
                    .aggregate(t=Sum('quantity'))['t'] or 0)
        used = (v.movements.filter(movement_type='fulfillment')
                .aggregate(t=Sum('quantity'))['t'] or 0)
        rows.append({'v': v, 'available': v.on_hand,
                     'produced': int(produced), 'used': int(abs(used))})
    if request.GET.get('nonzero'):
        rows = [r for r in rows if r['available'] != 0]
    return render(request, 'operations/finished_goods.html',
                  {'active_nav': 'finished', 'rows': rows, 'nonzero': request.GET.get('nonzero'),
                   'q': q, 'has_query': bool(q), 'search_hidden': {'nonzero': request.GET.get('nonzero', '')}})


# =============================================================================
# Internal orders (no payment)
# =============================================================================

@admin_required
def order_list(request):
    orders = InternalOrder.objects.prefetch_related('lines').all()
    q = request.GET.get('q', '').strip()
    orders = apply_search(orders, q, [
        'notes', 'lines__variant__name', 'lines__variant__product__name'])
    paginator = Paginator(orders, 25)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'operations/order_list.html',
                  {'active_nav': 'orders', 'page': page, 'q': q, 'has_query': bool(q)})


@admin_required
def order_create(request):
    if request.method == 'POST':
        form = InternalOrderForm(request.POST)
        formset = InternalOrderLineFormSet(request.POST, prefix='line')
        if form.is_valid() and formset.is_valid():
            lines = []
            for f in formset:
                variant = f.cleaned_data.get('variant')
                qty = f.cleaned_data.get('quantity') or 0
                if variant and qty > 0:
                    lines.append({'variant': variant, 'quantity': qty})
            if not lines:
                messages.error(request, 'Add at least one product line.')
            else:
                d = form.cleaned_data
                order = services.create_internal_order(
                    purpose=d['purpose'], lines=lines, notes=d['notes'],
                    ordered_on=d['ordered_on'], actor=request.user)
                messages.success(request, 'Internal order created (no payment required). '
                                          'Fulfill it to remove finished units.')
                return redirect('operations:order_detail', order_id=order.id)
        else:
            messages.error(request, 'Please correct the order form.')
    else:
        form = InternalOrderForm()
        formset = InternalOrderLineFormSet(prefix='line')
    return render(request, 'operations/order_form.html',
                  {'active_nav': 'orders', 'form': form, 'formset': formset})


@admin_required
def order_detail(request, order_id):
    order = get_object_or_404(InternalOrder.objects.prefetch_related('lines__variant__product'), pk=order_id)
    lines = []
    for ln in order.lines.all():
        lines.append({'ln': ln, 'on_hand': ln.variant.on_hand})
    return render(request, 'operations/order_detail.html',
                  {'active_nav': 'orders', 'order': order, 'lines': lines,
                   'fulfillment_token': uuid.uuid4().hex})


@admin_required
def order_fulfill(request, order_id):
    order = get_object_or_404(InternalOrder, pk=order_id)
    if request.method != 'POST':
        return redirect('operations:order_detail', order_id=order.id)
    token = request.POST.get('fulfillment_token') or None
    try:
        services.fulfill_internal_order(order=order, actor=request.user, fulfillment_token=token)
        messages.success(request, 'Order fulfilled — finished units removed from inventory. '
                                  'No filament was deducted.')
    except ValidationError as e:
        messages.error(request, '; '.join(e.messages))
    return redirect('operations:order_detail', order_id=order.id)


@admin_required
def order_cancel(request, order_id):
    order = get_object_or_404(InternalOrder, pk=order_id)
    if request.method == 'POST' and order.status == 'open':
        order.status = 'cancelled'
        order.save(update_fields=['status'])
        services.record_audit(request.user, 'update', order, summary='Internal order cancelled')
        messages.success(request, 'Order cancelled.')
    return redirect('operations:order_detail', order_id=order.id)


# =============================================================================
# Reconstruct-history guide
# =============================================================================

@admin_required
def reconstruct_guide(request):
    return render(request, 'operations/reconstruct.html', {'active_nav': 'prints'})
