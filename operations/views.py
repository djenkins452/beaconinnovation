"""Views for the staff-only Operations module (3D-printing).

Every view is gated by :func:`staff_required` (authenticated **and** ``is_staff``;
non-staff get a 404, matching ``admin_console``). All state changes go through
``operations.services`` so audit, the ledger, idempotency and the finance bridge
are always honoured.
"""
import uuid
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from finance.forms import validate_receipt_file
from operations import services
from operations.forms import (
    CreateExpenseForm, EquipmentForm, LinkPaymentForm, LocationForm, MaterialForm,
    OpeningSpoolForm, OpeningStockForm, PrintLogForm, PrintMaterialUseFormSet,
    PurchaseForm, PurchaseLineForm, ReceiveEquipmentForm, ReceiveFilamentForm,
    ReceiveStockForm, SupplierForm, WeighSpoolForm,
)
from operations.models import (
    AuditEvent, Equipment, FilamentSpool, InventoryMovement, Location, Material,
    PrintLog, Purchase, PurchaseDocument, PurchaseLine, ScaleMeasurement,
    StockItem, Supplier,
)


def staff_required(view):
    """Authenticated + is_staff. Unauthenticated → login; authed non-staff → 404
    (do not reveal the internal area)."""
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_staff:
            raise Http404()
        return view(request, *args, **kwargs)
    return wrapper


# =============================================================================
# Dashboard
# =============================================================================

@staff_required
def dashboard(request):
    materials = list(Material.objects.filter(is_active=True))
    low_stock = [m for m in materials if m.is_low_stock]
    spools = FilamentSpool.objects.exclude(status='empty').select_related('material')[:12]
    recent_movements = (InventoryMovement.objects.select_related('spool', 'stock_item')
                        .order_by('-created_at')[:10])
    recent_prints = PrintLog.objects.select_related('printer')[:5]
    ctx = {
        'active_nav': 'dashboard',
        'low_stock': low_stock,
        'spool_count': FilamentSpool.objects.exclude(status='empty').count(),
        'material_count': len(materials),
        'open_purchases': Purchase.objects.count(),
        'spools': spools,
        'recent_movements': recent_movements,
        'recent_prints': recent_prints,
    }
    return render(request, 'operations/dashboard.html', ctx)


# =============================================================================
# Suppliers / Locations
# =============================================================================

@staff_required
def supplier_list(request):
    return render(request, 'operations/supplier_list.html',
                  {'active_nav': 'suppliers', 'suppliers': Supplier.objects.all()})


@staff_required
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


@staff_required
def location_list(request):
    return render(request, 'operations/location_list.html',
                  {'active_nav': 'locations', 'locations': Location.objects.all()})


@staff_required
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

@staff_required
def material_list(request):
    qs = Material.objects.filter(is_active=True)
    mtype = request.GET.get('type', '')
    if mtype:
        qs = qs.filter(material_type=mtype)
    materials = list(qs)
    rows = [{'m': m, 'on_hand': m.total_on_hand(), 'low': m.is_low_stock} for m in materials]
    return render(request, 'operations/material_list.html',
                  {'active_nav': 'materials', 'rows': rows, 'type_filter': mtype,
                   'type_choices': Material.MATERIAL_TYPE_CHOICES})


@staff_required
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


@staff_required
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

@staff_required
def spool_list(request):
    spools = FilamentSpool.objects.select_related('material', 'location').all()
    status = request.GET.get('status', '')
    if status:
        spools = spools.filter(status=status)
    rows = [{'s': s, 'est': s.estimated_remaining_g, 'measured': s.measured_remaining_g,
             'variance': s.variance_g} for s in spools]
    return render(request, 'operations/spool_list.html',
                  {'active_nav': 'spools', 'rows': rows, 'status_filter': status,
                   'status_choices': FilamentSpool.STATUS_CHOICES})


@staff_required
def spool_detail(request, spool_id):
    spool = get_object_or_404(FilamentSpool.objects.select_related('material', 'location'), pk=spool_id)
    weigh_form = WeighSpoolForm(initial={'tare_grams': spool.tare_weight_g or ''})
    ctx = {
        'active_nav': 'spools', 'spool': spool,
        'est': spool.estimated_remaining_g, 'measured': spool.measured_remaining_g,
        'variance': spool.variance_g,
        'movements': spool.movements.select_related('actor').all(),
        'measurements': spool.measurements.all(),
        'weigh_form': weigh_form,
    }
    return render(request, 'operations/spool_detail.html', ctx)


@staff_required
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


@staff_required
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

@staff_required
def stock_list(request):
    items = StockItem.objects.select_related('material', 'location').all()
    rows = [{'i': i, 'on_hand': i.on_hand} for i in items]
    return render(request, 'operations/stock_list.html', {'active_nav': 'stock', 'rows': rows})


@staff_required
def equipment_list(request):
    return render(request, 'operations/equipment_list.html',
                  {'active_nav': 'equipment', 'equipment': Equipment.objects.all()})


@staff_required
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

@staff_required
def opening_index(request):
    return render(request, 'operations/opening_index.html', {'active_nav': 'opening'})


@staff_required
def opening_spool(request):
    form = OpeningSpoolForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        try:
            spool = services.enter_opening_spool(
                material=d['material'], spool_uid=d['spool_uid'],
                starting_weight_g=d['starting_weight_g'], tare_weight_g=d['tare_weight_g'],
                cost=d['cost'], cost_unknown=d['cost_unknown'], location=d['location'],
                status=d['status'], notes=d['notes'], actor=request.user)
            messages.success(request, f'Opening spool "{spool.spool_uid}" added with '
                                      f'{spool.estimated_remaining_g} g (no expense created).')
            return redirect('operations:spool_detail', spool_id=spool.id)
        except Exception as e:
            messages.error(request, f'Could not add spool: {e}')
    return render(request, 'operations/generic_form.html',
                  {'active_nav': 'opening', 'form': form, 'title': 'Opening inventory — filament spool',
                   'intro': 'Enter a spool you already own. This creates stock via an opening-balance '
                            'movement and does NOT create a finance expense.',
                   'cancel_url': reverse('operations:opening_index')})


@staff_required
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

@staff_required
def purchase_list(request):
    purchases = Purchase.objects.select_related('supplier').prefetch_related('lines', 'payments').all()
    paginator = Paginator(purchases, 25)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'operations/purchase_list.html',
                  {'active_nav': 'purchases', 'page': page})


@staff_required
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


@staff_required
def purchase_detail(request, purchase_id):
    purchase = get_object_or_404(
        Purchase.objects.select_related('supplier').prefetch_related('lines', 'payments', 'documents'),
        pk=purchase_id)
    line_form = PurchaseLineForm()
    link_form = LinkPaymentForm()
    expense_form = CreateExpenseForm(initial={'amount': purchase.order_total(),
                                              'transaction_date': purchase.order_date,
                                              'description': f'Purchase {purchase}'})
    ctx = {
        'active_nav': 'purchases', 'purchase': purchase,
        'lines': purchase.lines.select_related('material').all(),
        'payments': purchase.payments.select_related('transaction').all(),
        'documents': purchase.documents.all(),
        'line_form': line_form, 'link_form': link_form, 'expense_form': expense_form,
        'linked_total': purchase.linked_payment_total(),
    }
    return render(request, 'operations/purchase_detail.html', ctx)


@staff_required
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


@staff_required
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


@staff_required
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


@staff_required
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

@staff_required
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


@staff_required
def document_view(request, document_id):
    return _serve_document(request, document_id, 'inline')


@staff_required
def document_download(request, document_id):
    return _serve_document(request, document_id, 'attachment')


# =============================================================================
# Printing
# =============================================================================

@staff_required
def print_list(request):
    prints = PrintLog.objects.select_related('printer').all()
    paginator = Paginator(prints, 25)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'operations/print_list.html', {'active_nav': 'prints', 'page': page})


@staff_required
def print_create(request):
    if request.method == 'POST':
        form = PrintLogForm(request.POST)
        formset = PrintMaterialUseFormSet(request.POST, prefix='use')
        token = request.POST.get('submission_token') or None
        if form.is_valid() and formset.is_valid():
            uses = []
            for f in formset:
                spool = f.cleaned_data.get('spool')
                gc = f.cleaned_data.get('grams_consumed') or 0
                wg = f.cleaned_data.get('waste_grams') or 0
                if spool and (gc or wg):
                    uses.append({'spool': spool, 'grams_consumed': gc, 'waste_grams': wg})
            try:
                d = form.cleaned_data
                print_log = services.log_print(
                    name=d['name'], printer=d['printer'], purpose=d['purpose'],
                    outcome=d['outcome'], success_quantity=d['success_quantity'],
                    notes=d['notes'], printed_on=d['printed_on'], uses=uses,
                    actor=request.user, submission_token=token)
                messages.success(request, f'Print "{print_log.name}" logged; '
                                          f'{print_log.total_filament_g} g of filament deducted '
                                          f'(incl. {print_log.total_waste_g} g waste).')
                return redirect('operations:print_detail', print_id=print_log.id)
            except ValidationError as e:
                messages.error(request, '; '.join(e.messages))
        else:
            messages.error(request, 'Please correct the print form.')
    else:
        form = PrintLogForm()
        formset = PrintMaterialUseFormSet(prefix='use')
    return render(request, 'operations/print_form.html',
                  {'active_nav': 'prints', 'form': form, 'formset': formset,
                   'submission_token': uuid.uuid4().hex})


@staff_required
def print_detail(request, print_id):
    print_log = get_object_or_404(PrintLog.objects.select_related('printer'), pk=print_id)
    return render(request, 'operations/print_detail.html',
                  {'active_nav': 'prints', 'print_log': print_log,
                   'uses': print_log.material_uses.select_related('spool').all()})


# =============================================================================
# Inventory history (movements) + corrections
# =============================================================================

@staff_required
def movement_list(request):
    movements = InventoryMovement.objects.select_related('spool', 'spool__material', 'stock_item',
                                                         'stock_item__material', 'actor', 'reverses').all()
    mtype = request.GET.get('type', '')
    if mtype:
        movements = movements.filter(movement_type=mtype)
    q = request.GET.get('q', '').strip()
    if q:
        movements = movements.filter(Q(reason__icontains=q) | Q(spool__spool_uid__icontains=q))
    paginator = Paginator(movements, 50)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'operations/movement_list.html',
                  {'active_nav': 'history', 'page': page, 'type_filter': mtype, 'q': q,
                   'type_choices': InventoryMovement.MOVEMENT_TYPE_CHOICES})


@staff_required
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
