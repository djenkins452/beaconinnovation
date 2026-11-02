"""Service layer for Operations.

Every write to operations state goes through here so that:

* an immutable :class:`~operations.models.AuditEvent` is recorded on every mutation
  (the wired-audit discipline copied from ``aegis.core``);
* the inventory ledger stays the single source of truth — callers never mutate a
  quantity counter, they *post a movement*;
* deductions are **serialized per unit** (``select_for_update``) and **checked for
  sufficiency**, so concurrent requests cannot oversell stock and insufficient
  stock is rejected with a clear reconciliation path;
* repeated submissions are **idempotent** (an ``idempotency_key`` /
  ``submission_token`` is posted at most once), so a double-click or retried POST
  never double-counts;
* money stays in ``finance`` — receiving/opening never create an expense; the only
  bridge is an explicit :class:`~operations.models.PurchasePayment`.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from operations.models import (
    AuditEvent, FilamentSpool, InternalOrder, InternalOrderLine, InventoryMovement,
    Location, Material, PrintLog, PrintMaterialUse, PrintProduct, ProductionRecipe,
    ProductVariant, Purchase, PurchaseLine, PurchasePayment, ScaleMeasurement,
    StockItem, UnitChoices,
)

ZERO = Decimal('0')


class InsufficientStockError(ValidationError):
    """Raised when a consumption/waste would drive a unit below zero."""


class DuplicateSubmissionError(ValidationError):
    """Raised when a non-idempotent duplicate is detected."""


# =============================================================================
# Audit
# =============================================================================

def record_audit(actor, action, instance, summary='', changes=None):
    """Write one immutable audit event for ``instance``."""
    return AuditEvent.objects.create(
        actor=actor if (actor and getattr(actor, 'is_authenticated', False)) else None,
        action=action,
        model_name=instance.__class__.__name__,
        object_id=str(instance.pk),
        object_repr=str(instance)[:500],
        summary=summary[:500],
        changes=changes or {},
    )


# =============================================================================
# Core ledger primitive
# =============================================================================

def _current_quantity(spool=None, stock_item=None, product_variant=None):
    from django.db.models import Sum
    qs = InventoryMovement.objects.all()
    if spool is not None:
        qs = qs.filter(spool=spool)
    elif stock_item is not None:
        qs = qs.filter(stock_item=stock_item)
    else:
        qs = qs.filter(product_variant=product_variant)
    return qs.aggregate(t=Sum('quantity'))['t'] or ZERO


@transaction.atomic
def post_movement(*, movement_type, quantity, unit, actor, spool=None, stock_item=None,
                  product_variant=None, reason='', occurred_at=None, purchase_line=None,
                  print_use=None, reverses=None, idempotency_key=None, allow_negative=False):
    """Append one movement to the ledger, atomically and safely.

    * Exactly one of ``spool`` / ``stock_item`` / ``product_variant`` must be given.
    * ``quantity`` is signed (+ adds, − removes).
    * The target row is locked for the duration so concurrent deductions are
      serialized; a deduction that would make on-hand negative is rejected unless
      ``allow_negative``.
    * If ``idempotency_key`` is given and already used, the existing movement is
      returned unchanged (safe retry) and no new row/audit is written.
    """
    if sum(t is not None for t in (spool, stock_item, product_variant)) != 1:
        raise ValidationError(
            'A movement must target exactly one spool, stock item, or product variant.')

    if idempotency_key:
        existing = InventoryMovement.objects.filter(idempotency_key=idempotency_key).first()
        if existing is not None:
            return existing

    # Lock the target so two concurrent deductions can't both pass the check.
    if spool is not None:
        FilamentSpool.objects.select_for_update().get(pk=spool.pk)
    elif stock_item is not None:
        StockItem.objects.select_for_update().get(pk=stock_item.pk)
    else:
        ProductVariant.objects.select_for_update().get(pk=product_variant.pk)

    quantity = Decimal(quantity)
    if quantity < ZERO and not allow_negative:
        current = _current_quantity(spool=spool, stock_item=stock_item, product_variant=product_variant)
        if current + quantity < ZERO:
            target = spool or stock_item or product_variant
            raise InsufficientStockError(
                f'Not enough on hand for {target}: have {current} {unit}, '
                f'tried to remove {abs(quantity)} {unit}. Recount/reconcile before '
                f'removing more.'
            )

    movement = InventoryMovement.objects.create(
        movement_type=movement_type,
        spool=spool,
        stock_item=stock_item,
        product_variant=product_variant,
        quantity=quantity,
        unit=unit,
        reason=reason,
        occurred_at=occurred_at or timezone.now(),
        purchase_line=purchase_line,
        print_use=print_use,
        reverses=reverses,
        idempotency_key=idempotency_key or None,
        actor=actor if (actor and getattr(actor, 'is_authenticated', False)) else None,
    )
    record_audit(
        actor, 'reverse' if movement_type == 'reversal' else 'movement', movement,
        summary=f'{movement.get_movement_type_display()} {quantity} {unit}',
        changes={'quantity': str(quantity), 'type': movement_type},
    )
    return movement


@transaction.atomic
def reverse_movement(movement, actor, reason=''):
    """Correct a prior movement by posting its negation. The original stays
    immutable; a movement can only be reversed once.

    The reversal respects the stock-sufficiency check: if the original addition has
    since been drawn down (e.g. you produced 4 units and already fulfilled 3), the
    reversal that would drive the balance negative is rejected — reverse the later
    movement first. This keeps both inventories from being corrupted by a reversal.
    """
    if movement.movement_type == 'reversal':
        raise ValidationError('A reversal cannot itself be reversed.')
    if movement.reversed_by.exists():
        raise ValidationError('This movement has already been reversed.')
    return post_movement(
        movement_type='reversal',
        spool=movement.spool,
        stock_item=movement.stock_item,
        product_variant=movement.product_variant,
        quantity=-movement.quantity,
        unit=movement.unit,
        actor=actor,
        reason=reason or f'Reversal of {movement.get_movement_type_display().lower()}',
        reverses=movement,
    )


# =============================================================================
# Opening inventory (never creates a finance expense)
# =============================================================================

@transaction.atomic
def enter_opening_spool(*, material, spool_uid, starting_weight_g, actor,
                        tare_weight_g=None, cost=None, cost_unknown=False,
                        location=None, status='open', notes='', occurred_at=None,
                        remaining_unknown=False, is_refill=False):
    """Create a spool you already own and seed it with an opening-balance movement.
    No finance expense is created.

    Gram tracking is optional: when ``remaining_unknown`` is true no opening-balance
    movement is posted (the spool is tracked by status instead) — we do NOT invent a
    weight to satisfy the ledger. ``is_refill`` marks refill filament with no physical
    spool core.
    """
    starting = Decimal(starting_weight_g or 0)
    spool = FilamentSpool.objects.create(
        material=material, spool_uid=spool_uid, starting_weight_g=starting,
        remaining_unknown=remaining_unknown, is_refill=is_refill,
        tare_weight_g=tare_weight_g, cost=(None if cost_unknown else cost),
        cost_unknown=cost_unknown, location=location, status=status, notes=notes,
        created_by=actor if (actor and getattr(actor, 'is_authenticated', False)) else None,
    )
    record_audit(actor, 'create', spool, summary='Opening spool entered')
    if starting > ZERO and not remaining_unknown:
        post_movement(
            movement_type='opening_balance', spool=spool,
            quantity=starting, unit=UnitChoices.GRAM, actor=actor,
            reason='Opening inventory', occurred_at=occurred_at,
        )
    return spool


@transaction.atomic
def enter_opening_stock(*, material, quantity, unit, actor, location=None,
                        status=StockItem.STATUS_AVAILABLE, notes='', occurred_at=None):
    """Seed a quantity of hardware/consumable/packaging you already own.
    No finance expense is created."""
    stock_item, _ = StockItem.objects.get_or_create(
        material=material, location=location, status=status, unit=unit,
        defaults={'notes': notes,
                  'created_by': actor if (actor and getattr(actor, 'is_authenticated', False)) else None},
    )
    if Decimal(quantity) > ZERO:
        post_movement(
            movement_type='opening_balance', stock_item=stock_item,
            quantity=Decimal(quantity), unit=unit, actor=actor,
            reason='Opening inventory', occurred_at=occurred_at,
        )
    return stock_item


# =============================================================================
# Receiving a purchase (asset side only — NEVER an expense)
# =============================================================================

@transaction.atomic
def receive_stock_line(*, line, quantity, actor, location=None, status=StockItem.STATUS_AVAILABLE,
                       idempotency_key=None, delivery_confirmed=True):
    """Receive ``quantity`` of a stock line into inventory. Updates the line's
    received total and emits a purchase_receipt movement. No expense."""
    if line.item_type != 'stock':
        raise ValidationError('receive_stock_line is only for stock lines.')
    material = line.material
    if material is None:
        raise ValidationError('This line has no material set; set one before receiving.')
    quantity = Decimal(quantity)
    if quantity <= ZERO:
        raise ValidationError('Received quantity must be positive.')

    # Idempotent retry: if this exact submission already posted, do nothing more
    # (never advance the received counter twice).
    if idempotency_key:
        existing = InventoryMovement.objects.filter(idempotency_key=idempotency_key).first()
        if existing is not None:
            return existing

    stock_item, _ = StockItem.objects.get_or_create(
        material=material, location=location, status=status, unit=line.unit,
        defaults={'delivery_confirmed': delivery_confirmed,
                  'created_by': actor if (actor and getattr(actor, 'is_authenticated', False)) else None},
    )
    movement = post_movement(
        movement_type='purchase_receipt', stock_item=stock_item, quantity=quantity,
        unit=line.unit, actor=actor, reason=f'Received: {line.description}',
        purchase_line=line, idempotency_key=idempotency_key,
    )
    _advance_received(line, quantity, movement)
    return movement


@transaction.atomic
def receive_filament_line(*, line, spool_specs, actor, location=None, idempotency_key=None):
    """Receive filament by creating one spool per spec and a receipt movement for
    each. ``spool_specs`` is a list of dicts: spool_uid, starting_weight_g,
    tare_weight_g?, cost?, status?. No expense."""
    if line.item_type != 'filament':
        raise ValidationError('receive_filament_line is only for filament lines.')
    material = line.material
    if material is None or material.material_type != 'filament':
        raise ValidationError('Filament lines need a filament material set.')

    if idempotency_key and InventoryMovement.objects.filter(
            idempotency_key__startswith=f'{idempotency_key}:').exists():
        return list(line.spools.all())  # already processed this submission

    created = []
    for i, spec in enumerate(spool_specs):
        spool = FilamentSpool.objects.create(
            material=material, spool_uid=spec['spool_uid'],
            starting_weight_g=Decimal(spec['starting_weight_g']),
            tare_weight_g=spec.get('tare_weight_g'),
            cost=spec.get('cost'), cost_unknown=spec.get('cost_unknown', False),
            location=location, status=spec.get('status', 'sealed'),
            source_line=line,
            created_by=actor if (actor and getattr(actor, 'is_authenticated', False)) else None,
        )
        record_audit(actor, 'create', spool, summary='Spool received from purchase')
        post_movement(
            movement_type='purchase_receipt', spool=spool,
            quantity=Decimal(spec['starting_weight_g']), unit=UnitChoices.GRAM, actor=actor,
            reason=f'Received: {line.description}', purchase_line=line,
            idempotency_key=(f'{idempotency_key}:{i}' if idempotency_key else None),
        )
        created.append(spool)

    _advance_received(line, Decimal(len(created)), None)
    return created


@transaction.atomic
def receive_filament_spool(*, line, spool_uid, actor, starting_weight_g=ZERO,
                           remaining_unknown=False, is_refill=False, status='sealed',
                           cost=None, cost_unknown=False, tare_weight_g=None,
                           location=None, notes='', idempotency_key=None,
                           delivery_confirmed=True):
    """Receive ONE filament spool (or refill) from a purchase line.

    Idempotent by the physical spool's ``spool_uid`` — re-running returns the
    existing spool and advances nothing twice. When ``remaining_unknown`` is true no
    receipt movement is posted (grams untracked; we never invent a weight); the spool
    is still linked to the line and the line's received count advances by one. No
    finance expense is created."""
    if line.item_type != 'filament':
        raise ValidationError('receive_filament_spool is only for filament lines.')
    material = line.material
    if material is None or material.material_type != 'filament':
        raise ValidationError('Filament lines need a filament material set.')

    existing = FilamentSpool.objects.filter(spool_uid=spool_uid).first()
    if existing is not None:
        return existing  # idempotent by spool identity

    starting = Decimal(starting_weight_g or 0)
    spool = FilamentSpool.objects.create(
        material=material, spool_uid=spool_uid, starting_weight_g=starting,
        remaining_unknown=remaining_unknown, is_refill=is_refill,
        delivery_confirmed=delivery_confirmed,
        tare_weight_g=tare_weight_g, cost=(None if cost_unknown else cost),
        cost_unknown=cost_unknown, location=location, status=status, notes=notes,
        source_line=line,
        created_by=actor if (actor and getattr(actor, 'is_authenticated', False)) else None,
    )
    record_audit(
        actor, 'create', spool,
        summary=f'Spool received from purchase ({"refill" if is_refill else "spool"}'
                f'{", grams untracked" if remaining_unknown else ""}'
                f'{", delivery unconfirmed" if not delivery_confirmed else ""})')
    if starting > ZERO and not remaining_unknown:
        post_movement(
            movement_type='purchase_receipt', spool=spool, quantity=starting,
            unit=UnitChoices.GRAM, actor=actor, reason=f'Received: {line.description}',
            purchase_line=line, idempotency_key=idempotency_key,
        )
    _advance_received(line, Decimal('1'), None)
    return spool


@transaction.atomic
def receive_equipment_line(*, line, actor, name, equipment_type='printer', location=None, **fields):
    """Turn an equipment line into an Equipment asset record. Equipment is NOT
    inventory, so NO movement and NO expense are created here."""
    from operations.models import Equipment
    if line.item_type != 'equipment':
        raise ValidationError('receive_equipment_line is only for equipment lines.')
    equipment = Equipment.objects.create(
        name=name, equipment_type=equipment_type, location=location, source_line=line,
        cost=fields.get('cost'), cost_unknown=fields.get('cost_unknown', False),
        manufacturer=fields.get('manufacturer', ''), model=fields.get('model', ''),
        serial_number=fields.get('serial_number', ''), acquired_date=fields.get('acquired_date'),
        created_by=actor if (actor and getattr(actor, 'is_authenticated', False)) else None,
    )
    record_audit(actor, 'create', equipment, summary='Equipment recorded from purchase (asset, not stock)')
    _advance_received(line, line.quantity_ordered - line.quantity_received, None)
    return equipment


def _advance_received(line, delta, movement):
    line.quantity_received = (line.quantity_received or ZERO) + Decimal(delta)
    line.save(update_fields=['quantity_received'])


# =============================================================================
# Fast dashboard receiving (one-click defaults; reuses the receive services)
# =============================================================================

def default_receiving_location():
    """The location routine receiving defaults to. When there is exactly one active
    location (the common case — "Home Office / Print Room"), use it; otherwise prefer
    one whose name looks like the print room / home office; else the first active one.
    Returns ``None`` only when no active location exists."""
    locs = list(Location.objects.filter(is_active=True))
    if len(locs) == 1:
        return locs[0]
    for needle in ('print room', 'home office'):
        for loc in locs:
            if needle in loc.name.lower():
                return loc
    return locs[0] if locs else None


@transaction.atomic
def quick_receive_line(*, line, actor, quantity=None, is_refill=False,
                       location=None, idempotency_key=None):
    """Receive a filament or stock line with everyday defaults, for the dashboard.

    * Receives the **full outstanding quantity** by default; pass ``quantity`` for a
      partial receipt. Equipment and ``other`` lines are not quick-receivable (they
      need details / have nothing to receive) and raise ``ValidationError``.
    * **Filament** — creates that many spools (or refills, preserving the distinction),
      status *sealed/new*, **grams untracked** (no weighing, no slicer data, no manual
      spool ids), each delivery-confirmed (you are confirming arrival). No finance
      expense. Spool ids are derived from the line and the submission token, so a
      double-click / retry re-uses the same ids and never creates duplicate spools.
    * **Stock** — posts ONE ``purchase_receipt`` movement for the quantity, idempotent
      on the submission token, delivery-confirmed. No finance expense.
    * Costs, funding, payments, finance expenses and attached documents are never
      touched. The line row is locked for the duration so concurrent submissions are
      serialized.

    Returns a dict summarising what was received: ``{'kind', 'created', 'quantity'}``.
    """
    # Lock + re-read the line so two concurrent receives on it are serialized and
    # each sees the other's committed effect (outstanding is read under the lock).
    # of=('self',) locks only the line row — Postgres cannot apply FOR UPDATE across
    # the nullable material join.
    line = (PurchaseLine.objects.select_for_update(of=('self',))
            .select_related('purchase', 'material').get(pk=line.pk))

    if line.item_type == 'other':
        raise ValidationError('This line has nothing to receive into inventory.')
    if line.item_type == 'equipment':
        raise ValidationError('Equipment needs its details (name, type) — use the '
                              'full Receive form for equipment lines.')
    if line.material is None:
        raise ValidationError('This line has no material set; set one before receiving.')

    outstanding = line.quantity_outstanding
    if location is None:
        location = default_receiving_location()
    sub = (idempotency_key or uuid_hex()).replace(':', '').replace('-', '')[:12]

    if line.item_type == 'stock':
        # Idempotent retry of THIS submission: the receipt movement carries the key.
        if idempotency_key and InventoryMovement.objects.filter(
                idempotency_key=idempotency_key).exists():
            return {'kind': 'stock', 'created': 0, 'quantity': ZERO}
        qty = Decimal(quantity) if quantity is not None else outstanding
        if qty <= ZERO:
            raise ValidationError('Nothing left to receive on this line.')
        receive_stock_line(line=line, quantity=qty, actor=actor, location=location,
                           idempotency_key=idempotency_key)
        return {'kind': 'stock', 'created': 1, 'quantity': qty}

    # Filament: whole spools/refills, grams untracked.
    # Idempotent retry of THIS submission: its spools already exist (deterministic ids).
    if idempotency_key and FilamentSpool.objects.filter(
            spool_uid=f'R-{line.pk.hex[:8]}-{sub}-1').exists():
        return {'kind': 'filament', 'created': 0, 'quantity': ZERO, 'is_refill': is_refill}
    count = int(quantity) if quantity is not None else int(outstanding)
    if count <= 0:
        raise ValidationError('Nothing left to receive on this line.')
    created = 0
    for i in range(count):
        # line pk keeps ids unique across lines; sub keeps repeated genuine receipts
        # distinct while making a double-click of THIS submission a no-op (idempotent
        # by spool id in receive_filament_spool).
        uid = f'R-{line.pk.hex[:8]}-{sub}-{i + 1}'
        before = FilamentSpool.objects.filter(spool_uid=uid).exists()
        receive_filament_spool(
            line=line, spool_uid=uid, actor=actor, starting_weight_g=ZERO,
            remaining_unknown=True, is_refill=is_refill, status='sealed',
            location=location, delivery_confirmed=True)
        if not before:
            created += 1
    return {'kind': 'filament', 'created': created, 'quantity': Decimal(count),
            'is_refill': is_refill}


@transaction.atomic
def quick_receive_purchase(*, purchase, actor, is_refill=False, location=None,
                           idempotency_key=None):
    """Receive every still-outstanding filament/stock line on ONE order, with the
    :func:`quick_receive_line` defaults. Scoped strictly to this order's lines, so it
    can never touch unrelated purchases.

    * Only lines that are **not received yet** (``receiving_status == 'outstanding'``)
      are received. Lines already delivery-unconfirmed are left for the Confirm action
      (so nothing is received twice), and equipment lines are reported as skipped
      (receive them individually with their details).
    * ``is_refill`` applies to all filament lines on the order (a single order usually
      ships all refills or all spools). Idempotent: a per-line token derived from the
      submission token makes a double-submit a safe no-op.

    Returns a summary dict: ``{'spools', 'stock_lines', 'skipped_equipment'}``.
    """
    token = idempotency_key or uuid_hex()
    summary = {'spools': 0, 'stock_lines': 0, 'skipped_equipment': 0}
    for line in purchase.lines.select_related('material').all():
        if line.item_type == 'other':
            continue
        if line.receiving_status != 'outstanding':
            continue
        if line.item_type == 'equipment':
            summary['skipped_equipment'] += 1
            continue
        result = quick_receive_line(
            line=line, actor=actor, is_refill=is_refill, location=location,
            idempotency_key=f'{token}-{line.pk.hex[:8]}')
        if result['kind'] == 'filament':
            summary['spools'] += result['created']
        else:
            summary['stock_lines'] += 1
    record_audit(actor, 'update', purchase,
                 summary=f"Received remaining order ({summary['spools']} spool(s), "
                         f"{summary['stock_lines']} stock line(s))")
    return summary


# =============================================================================
# Printing (consumption + waste, each counted once; failures still consume)
# =============================================================================

def _historical_timestamp(printed_on):
    """Noon on the print date, timezone-aware, so back-dated movements sort into
    the ledger on the day the print actually happened."""
    from datetime import datetime, time
    naive = datetime.combine(printed_on, time(12, 0))
    if timezone.is_naive(naive):
        return timezone.make_aware(naive, timezone.get_current_timezone())
    return naive


@transaction.atomic
def log_print(*, name, printer, purpose, outcome, notes, uses, actor,
              products=None, success_quantity=0, is_historical=False,
              printed_on=None, submission_token=None, date_unknown=False):
    """Record a print, deduct its filament, and add successful finished units.

    ``uses`` — list of dicts per spool: ``spool``, ``grams_consumed``,
    ``waste_grams``, optional ``basis`` (recipe/slicer/measured) and
    ``all_inclusive``. When ``all_inclusive`` is true the grams figure already
    includes supports/purge, so ``waste_grams`` is ignored (never added on top). A
    ``consumption`` movement (into the part) and a separate ``waste`` movement are
    posted — each deducts exactly once. Failed prints still consume what is entered
    (the actual/estimated amount, never the full planned amount).

    ``products`` — list of dicts: ``variant``, ``recipe`` (version snapshot),
    ``quantity_planned``, ``quantity_success``. Only the SUCCESSFUL units become
    finished inventory (a ``production_output`` movement). The whole operation is
    idempotent on ``submission_token``.
    """
    if submission_token:
        existing = PrintLog.objects.filter(submission_token=submission_token).first()
        if existing is not None:
            return existing

    printed_on = printed_on or timezone.localdate()
    occurred_at = _historical_timestamp(printed_on) if is_historical else None

    print_log = PrintLog.objects.create(
        name=name, printed_on=printed_on, printer=printer,
        purpose=purpose, outcome=outcome, success_quantity=success_quantity or 0,
        is_historical=is_historical, date_unknown=date_unknown,
        notes=notes, submission_token=submission_token or None,
        created_by=actor if (actor and getattr(actor, 'is_authenticated', False)) else None,
    )
    record_audit(actor, 'create', print_log,
                 summary=f'Print logged ({outcome}{", historical" if is_historical else ""})')
    base = (submission_token or print_log.pk)

    # --- Filament consumption + waste (each deducted exactly once) ---
    for u in uses:
        grams_consumed = Decimal(u.get('grams_consumed') or 0)
        waste_grams = Decimal(u.get('waste_grams') or 0)
        all_inclusive = bool(u.get('all_inclusive'))
        if all_inclusive:
            waste_grams = ZERO  # grams_consumed already includes supports/purge
        if grams_consumed <= ZERO and waste_grams <= ZERO:
            continue
        pmu = PrintMaterialUse.objects.create(
            print_log=print_log, spool=u['spool'],
            grams_consumed=grams_consumed, waste_grams=waste_grams,
            basis=u.get('basis') or 'slicer', all_inclusive=all_inclusive,
        )
        if grams_consumed > ZERO:
            post_movement(
                movement_type='consumption', spool=u['spool'], quantity=-grams_consumed,
                unit=UnitChoices.GRAM, actor=actor, reason=f'Print: {name}',
                print_use=pmu, occurred_at=occurred_at, idempotency_key=(f'{base}:{pmu.pk}:c'),
            )
        if waste_grams > ZERO:
            post_movement(
                movement_type='waste', spool=u['spool'], quantity=-waste_grams,
                unit=UnitChoices.GRAM, actor=actor, reason=f'Print waste: {name}',
                print_use=pmu, occurred_at=occurred_at, idempotency_key=(f'{base}:{pmu.pk}:w'),
            )

    # --- Finished-goods output (successful units only) ---
    for p in (products or []):
        variant = p['variant']
        qty_planned = int(p.get('quantity_planned') or 0)
        qty_success = int(p.get('quantity_success') or 0)
        pp = PrintProduct.objects.create(
            print_log=print_log, variant=variant, recipe=p.get('recipe'),
            quantity_planned=qty_planned, quantity_success=qty_success,
        )
        if qty_success > 0:
            post_movement(
                movement_type='production_output', product_variant=variant,
                quantity=Decimal(qty_success), unit=UnitChoices.EACH, actor=actor,
                reason=f'Produced: {name}', occurred_at=occurred_at,
                idempotency_key=(f'{base}:prod:{pp.pk}'),
            )
    return print_log


# =============================================================================
# Weigh-in + reconciliation (measured vs estimated)
# =============================================================================

@transaction.atomic
def set_spool_status(*, spool, status, actor):
    """Change a spool's status (sealed/open/low/empty/damaged) WITHOUT requiring a
    weight. Status is the everyday signal when grams aren't tracked."""
    valid = {c[0] for c in FilamentSpool.STATUS_CHOICES}
    if status not in valid:
        raise ValidationError(f'Unknown spool status: {status}')
    old = spool.status
    spool.status = status
    spool.save(update_fields=['status'])
    record_audit(actor, 'update', spool, summary=f'Status {old} → {status}',
                 changes={'status': [old, status]})
    return spool


@transaction.atomic
def confirm_spool_delivery(*, spool, actor):
    """Mark an ordered spool as delivered/confirmed (moves it to confirmed on-hand)."""
    if not spool.delivery_confirmed:
        spool.delivery_confirmed = True
        spool.save(update_fields=['delivery_confirmed'])
        record_audit(actor, 'update', spool, summary='Delivery confirmed')
    return spool


@transaction.atomic
def confirm_stock_delivery(*, stock_item, actor):
    if not stock_item.delivery_confirmed:
        stock_item.delivery_confirmed = True
        stock_item.save(update_fields=['delivery_confirmed'])
        record_audit(actor, 'update', stock_item, summary='Delivery confirmed')
    return stock_item


@transaction.atomic
def merge_locations(*, target, sources, actor):
    """Consolidate ``sources`` locations into ``target``: repoint every spool, stock
    item and equipment record, then remove the emptied source locations. Linked
    records and audit history are preserved; no inventory is duplicated."""
    from operations.models import Equipment
    moved = {'spools': 0, 'stock': 0, 'equipment': 0}
    for src in sources:
        if src.pk == target.pk:
            continue
        moved['spools'] += FilamentSpool.objects.filter(location=src).update(location=target)
        moved['stock'] += StockItem.objects.filter(location=src).update(location=target)
        moved['equipment'] += Equipment.objects.filter(location=src).update(location=target)
        record_audit(actor, 'update', target,
                     summary=f'Merged location "{src.name}" → "{target.name}"', changes=moved)
        src.delete()
    return moved


@transaction.atomic
def weigh_spool(*, spool, gross_grams, tare_grams, actor, note='', measured_at=None):
    """Record a scale reading. ``net_g = gross − tare`` is the MEASURED remaining
    filament; it is stored, not applied, until reconciled."""
    gross_grams = Decimal(gross_grams)
    tare_grams = Decimal(tare_grams)
    net = gross_grams - tare_grams
    if net < ZERO:
        raise ValidationError('Tare cannot exceed the gross weight.')
    measurement = ScaleMeasurement.objects.create(
        spool=spool, gross_grams=gross_grams, tare_grams=tare_grams, net_g=net,
        note=note, measured_at=measured_at or timezone.now(),
        measured_by=actor if (actor and getattr(actor, 'is_authenticated', False)) else None,
    )
    record_audit(actor, 'create', measurement, summary=f'Weigh-in: {net}g net')
    # Remember the tare for next time if the spool didn't have one.
    if spool.tare_weight_g is None:
        spool.tare_weight_g = tare_grams
        spool.save(update_fields=['tare_weight_g'])
    return measurement


@transaction.atomic
def reconcile_spool_from_measurement(*, measurement, actor):
    """Post an adjustment movement that brings the spool's ledger estimate into
    line with a measured value. The delta (measured − estimated) is the
    adjustment; the original consumption history is untouched."""
    if measurement.reconciled:
        raise ValidationError('This measurement has already been reconciled.')
    spool = measurement.spool
    estimated = spool.estimated_remaining_g
    delta = measurement.net_g - estimated
    if delta != ZERO:
        post_movement(
            movement_type='adjustment', spool=spool, quantity=delta, unit=UnitChoices.GRAM,
            actor=actor, allow_negative=True,
            reason=f'Reconcile to measured {measurement.net_g}g (was {estimated}g)',
        )
    measurement.reconciled = True
    measurement.save(update_fields=['reconciled'])
    record_audit(actor, 'update', measurement, summary=f'Reconciled (Δ {delta}g)')
    return delta


# =============================================================================
# Editing purchases / lines (owner self-service corrections — audited)
# =============================================================================

# Structural fields on a line that are tied to records/movements created when the
# line was received. They cannot be changed once anything has been received against
# the line, because posted inventory movements and created spool/stock/equipment
# records reference them. Cost, classification and description never touch the ledger
# or linked payments, so they stay editable.
_LINE_STRUCTURAL_FIELDS = ('item_type', 'material', 'unit')
_LINE_EDITABLE_FIELDS = (
    'item_type', 'description', 'material', 'quantity_ordered', 'unit',
    'unit_cost', 'line_discount', 'line_tax', 'use_type', 'business_pct',
)
_PURCHASE_EDITABLE_FIELDS = (
    'supplier', 'supplier_name', 'order_date', 'order_number', 'product_links',
    'shipping_total', 'tax_total', 'discount_total', 'notes', 'funding',
)


def _repr(value):
    """Short, stable string for an audit change entry (handles model instances)."""
    if value is None:
        return ''
    pk = getattr(value, 'pk', None)
    return str(value) if pk is None else f'{value} ({pk})'


@transaction.atomic
def edit_purchase(*, purchase, actor, **fields):
    """Edit a purchase's header fields (supplier, order date/number, order-level
    shipping/tax/discount, notes, funding designation).

    Editing a purchase NEVER receives inventory, creates a payment, or creates a
    finance expense. Attached documents and existing payment links are left exactly
    as they are. Order-level tax lives in ``tax_total`` and is kept separate from a
    line's own ``line_tax`` — the two are never merged, so order-level tax is not
    counted again as line tax. Every change is recorded as one audit event.
    """
    changes = {}
    for key in _PURCHASE_EDITABLE_FIELDS:
        if key not in fields:
            continue
        new = fields[key]
        old = getattr(purchase, key)
        if key == 'supplier':
            if (old.pk if old else None) == (new.pk if new else None):
                continue
        elif old == new:
            continue
        changes[key] = [_repr(old), _repr(new)]
        setattr(purchase, key, new)
    if changes:
        purchase.save(update_fields=list(changes.keys()))
        record_audit(actor, 'update', purchase, summary='Purchase edited', changes=changes)
    return purchase


@transaction.atomic
def edit_purchase_line(*, line, actor, **fields):
    """Edit a single purchase line with inventory/financial-history protection.

    * Description, unit cost, line discount, line tax and use classification are
      ALWAYS editable — none of them touch posted inventory movements or linked
      payments, they only correct the cost basis and classification of the line.
    * On a line that has already been received (``quantity_received > 0``), the
      structural fields (``item_type``, ``material``, ``unit``) are LOCKED, because
      posted movements and the spool/stock/equipment records created from the line
      reference them; changing them would orphan or misattribute real inventory.
      Attempting to change one raises ``ValidationError`` pointing at the reversal
      workflow (reverse the receipt in inventory history first).
    * ``quantity_ordered`` may be corrected at any time but, on a received line, may
      not drop below the quantity already received.

    This never posts, edits, or deletes an inventory movement, and never creates a
    payment or expense — posted ledger rows and linked payments are left untouched.
    Order-level tax stays on the purchase; only the line's own ``line_tax`` is
    touched here, so order-level tax is never counted again as line tax.
    """
    received = (line.quantity_received or ZERO) > ZERO
    changes = {}
    for key in _LINE_EDITABLE_FIELDS:
        if key not in fields:
            continue
        new = fields[key]
        old = getattr(line, key)
        if key == 'material':
            if (old.pk if old else None) == (new.pk if new else None):
                continue
        elif old == new:
            continue

        if received and key in _LINE_STRUCTURAL_FIELDS:
            raise ValidationError(
                f'"{line._meta.get_field(key).verbose_name or key}" cannot be changed on a '
                f'line that has already been received. Reverse the receipt in inventory '
                f'history first, then edit the line.')
        if key == 'quantity_ordered':
            received_qty = line.quantity_received or ZERO
            if received and Decimal(new) < received_qty:
                raise ValidationError(
                    f'Ordered quantity cannot be less than the {received_qty} already '
                    f'received. Reverse the receipt first to lower it further.')

        changes[key] = [_repr(old), _repr(new)]
        setattr(line, key, new)

    if changes:
        # Keep business_pct consistent with use_type (model rule), then persist only
        # the fields that changed (+ business_pct when use_type drove it).
        line.clean()
        save_fields = set(changes.keys())
        if 'use_type' in changes:
            save_fields.add('business_pct')
        line.save(update_fields=list(save_fields))
        record_audit(actor, 'update', line, summary='Purchase line edited', changes=changes)
    return line


# =============================================================================
# Delivery-status corrections (owner self-service — audited, history-preserving)
# =============================================================================

def _line_inventory_records(line):
    """Inventory records created from a line.

    Returns ``(spools, stock_items)``. Filament spools are linked by ``source_line``;
    stock items are the ones this line posted a ``purchase_receipt`` into. Equipment is
    an asset (never in the ledger) and is deliberately not touched by delivery-status
    corrections.
    """
    spools = list(line.spools.all())
    stock_items = list(
        StockItem.objects.filter(
            movements__purchase_line=line, movements__movement_type='purchase_receipt',
        ).distinct()
    )
    return spools, stock_items


@transaction.atomic
def mark_line_not_received(*, line, actor):
    """Correct a line wrongly recorded as received/assumed-delivered back to NOT
    received — safely, through the ledger, with history preserved.

    * **Protects inventory already used.** If a spool from this line has any movement
      other than its own purchase receipt (consumed, wasted, adjusted, or already
      reversed), the correction is refused with a message pointing at the inventory
      reversal workflow — real inventory is never silently rewritten. For stock, the
      ledger's own sufficiency check refuses a reversal that would drive on-hand
      negative (i.e. stock already drawn down), to the same effect.
    * For each remaining record it reverses any ``purchase_receipt`` movement (an
      established reversing movement; the original stays immutable), then deletes the
      now-empty, unused record so no phantom spool/stock lingers. A record whose
      receipt was reversed keeps its immutable ledger rows and is left at zero and
      delivery-unconfirmed rather than deleted.
    * Resets the line's received quantity to zero and sets its delivery state to
      ``outstanding``. Costs, funding, payments, finance expenses and attached
      documents are never touched, and no new spool/stock/movement is duplicated.

    Idempotent: running it again on an already-not-received line is a no-op.
    """
    spools, stock_items = _line_inventory_records(line)

    used = [f'spool {s.spool_uid}' for s in spools
            if s.movements.exclude(movement_type='purchase_receipt').exists()]
    if used:
        raise ValidationError(
            'This line has inventory that has already been used or adjusted (' +
            ', '.join(used) + '). Reverse those movements in inventory history first, '
            'then mark the line not received.')

    summary = {'spools_removed': 0, 'receipts_reversed': 0, 'records_zeroed': 0}

    for spool in spools:
        for mv in spool.movements.filter(movement_type='purchase_receipt'):
            if not mv.reversed_by.exists():
                reverse_movement(mv, actor, reason='Delivery corrected: not received')
                summary['receipts_reversed'] += 1
        if not spool.movements.exists():
            record_audit(actor, 'delete', spool,
                         summary='Phantom spool removed (delivery corrected to not received)')
            spool.delete()
            summary['spools_removed'] += 1
        else:
            if spool.delivery_confirmed:
                spool.delivery_confirmed = False
                spool.save(update_fields=['delivery_confirmed'])
            record_audit(actor, 'update', spool,
                         summary='Receipt reversed; spool left at zero (not received)')
            summary['records_zeroed'] += 1

    for si in stock_items:
        for mv in si.movements.filter(purchase_line=line, movement_type='purchase_receipt'):
            if not mv.reversed_by.exists():
                # reverse_movement refuses (InsufficientStockError) if the stock has
                # since been drawn down — that is the "already used" protection for stock.
                reverse_movement(mv, actor, reason='Delivery corrected: not received')
                summary['receipts_reversed'] += 1
        if si.delivery_confirmed:
            si.delivery_confirmed = False
            si.save(update_fields=['delivery_confirmed'])
        record_audit(actor, 'update', si,
                     summary='Receipt reversed; stock left at zero (not received)')
        summary['records_zeroed'] += 1

    changes = {}
    if (line.quantity_received or ZERO) != ZERO:
        changes['quantity_received'] = [str(line.quantity_received), '0']
        line.quantity_received = ZERO
    if line.delivery != 'outstanding':
        changes['delivery'] = [line.delivery or '', 'outstanding']
        line.delivery = 'outstanding'
    if changes:
        line.save(update_fields=list(changes.keys()))
    record_audit(actor, 'update', line,
                 summary='Line marked NOT received (delivery correction)',
                 changes={**changes, **{k: v for k, v in summary.items() if v}})
    return line


@transaction.atomic
def confirm_line_received(*, line, actor):
    """Confirm that a recorded/assumed delivery has actually arrived.

    Flips every spool/stock record created from this line to delivery-confirmed (so it
    now counts as on-hand) and sets the line's delivery state to ``received``. Creates
    no new inventory movement and never touches costs, funding, payments, expenses or
    documents. Refuses if there is nothing recorded to confirm (use the Receive flow to
    record what arrived). Idempotent."""
    spools, stock_items = _line_inventory_records(line)
    received = (line.quantity_received or ZERO) > ZERO
    if not spools and not stock_items and not received:
        raise ValidationError(
            'Nothing has been recorded on this line to confirm. Use Receive to record '
            'what arrived.')

    confirmed = 0
    for spool in spools:
        if not spool.delivery_confirmed:
            confirm_spool_delivery(spool=spool, actor=actor)
            confirmed += 1
    for si in stock_items:
        if not si.delivery_confirmed:
            confirm_stock_delivery(stock_item=si, actor=actor)
            confirmed += 1

    changes = {}
    if line.delivery != 'received':
        changes['delivery'] = [line.delivery or '', 'received']
        line.delivery = 'received'
        line.save(update_fields=['delivery'])
    if changes or confirmed:
        record_audit(actor, 'update', line,
                     summary=f'Delivery confirmed ({confirmed} record(s) now on-hand)',
                     changes=changes)
    return line


@transaction.atomic
def mark_purchase_not_received(*, purchase, actor):
    """Mark every receivable line on an order NOT received (see
    :func:`mark_line_not_received`). Non-inventory ('other') lines are skipped. One
    summary audit event is written for the order."""
    n = 0
    for line in purchase.lines.all():
        if line.item_type == 'other':
            continue
        mark_line_not_received(line=line, actor=actor)
        n += 1
    record_audit(actor, 'update', purchase,
                 summary=f'Whole order marked NOT received ({n} line(s))')
    return n


@transaction.atomic
def confirm_purchase_received(*, purchase, actor):
    """Confirm delivery of every line on an order that has something recorded to
    confirm (see :func:`confirm_line_received`). One summary audit event is written."""
    n = 0
    for line in purchase.lines.all():
        if line.item_type == 'other':
            continue
        spools, stock_items = _line_inventory_records(line)
        if spools or stock_items or (line.quantity_received or ZERO) > ZERO:
            confirm_line_received(line=line, actor=actor)
            n += 1
    record_audit(actor, 'update', purchase,
                 summary=f'Whole order confirmed received ({n} line(s))')
    return n


# =============================================================================
# Finance bridge (the only money touch — manual by design)
# =============================================================================

@transaction.atomic
def link_payment(*, purchase, transaction_obj, amount=None, note='', actor):
    """Link a purchase to an EXISTING finance transaction (the expense)."""
    payment = PurchasePayment.objects.create(
        purchase=purchase, transaction=transaction_obj,
        amount=Decimal(amount) if amount is not None else transaction_obj.amount,
        note=note,
        created_by=actor if (actor and getattr(actor, 'is_authenticated', False)) else None,
    )
    record_audit(actor, 'create', payment, summary='Purchase linked to finance transaction')
    return payment


@transaction.atomic
def create_expense_for_purchase(*, purchase, account, category, amount, transaction_date,
                                description, actor, vendor=''):
    """Create EXACTLY ONE finance expense for a purchase and link it. This is the
    only path that writes to finance; receiving/opening never call it, so an
    expense is counted once."""
    from finance.models import Transaction
    txn = Transaction.objects.create(
        account=account, transaction_type='expense', category=category,
        amount=Decimal(amount), transaction_date=transaction_date,
        description=description, vendor=vendor or purchase.supplier_display,
        reference_number=purchase.order_number or '',
        created_by=actor if (actor and getattr(actor, 'is_authenticated', False)) else None,
    )
    payment = link_payment(purchase=purchase, transaction_obj=txn, amount=amount,
                           note='Expense created from purchase', actor=actor)
    return txn, payment


# =============================================================================
# Recipes (versioned — a new version never rewrites past print consumption)
# =============================================================================

@transaction.atomic
def create_recipe_version(*, variant, materials, actor, notes=''):
    """Create a NEW current recipe version for a variant. Previous versions are
    preserved and marked not-current. ``materials`` is a list of dicts:
    ``material``, ``grams_per_unit``, ``waste_per_unit``."""
    from operations.models import RecipeMaterial
    last = variant.recipes.order_by('-version').first()
    next_version = (last.version + 1) if last else 1
    variant.recipes.filter(is_current=True).update(is_current=False)
    recipe = ProductionRecipe.objects.create(
        variant=variant, version=next_version, is_current=True, notes=notes,
        created_by=actor if (actor and getattr(actor, 'is_authenticated', False)) else None,
    )
    for m in materials:
        if m.get('material') is None:
            continue
        RecipeMaterial.objects.create(
            recipe=recipe, material=m['material'],
            grams_per_unit=Decimal(m.get('grams_per_unit') or 0),
            waste_per_unit=Decimal(m.get('waste_per_unit') or 0),
        )
    record_audit(actor, 'create', recipe, summary=f'Recipe v{next_version} created')
    return recipe


# =============================================================================
# Internal orders (no payment) — fulfillment removes finished goods only
# =============================================================================

@transaction.atomic
def create_internal_order(*, purpose, lines, actor, notes='', ordered_on=None):
    """Create a staff-only internal order (no payment). ``lines`` is a list of
    dicts: ``variant``, ``quantity``."""
    order = InternalOrder.objects.create(
        purpose=purpose, notes=notes, ordered_on=ordered_on or timezone.localdate(),
        created_by=actor if (actor and getattr(actor, 'is_authenticated', False)) else None,
    )
    for ln in lines:
        qty = int(ln.get('quantity') or 0)
        if ln.get('variant') is None or qty <= 0:
            continue
        InternalOrderLine.objects.create(order=order, variant=ln['variant'], quantity=qty)
    record_audit(actor, 'create', order, summary='Internal order created (no payment)')
    return order


@transaction.atomic
def fulfill_internal_order(*, order, actor, fulfillment_token=None, occurred_at=None):
    """Fulfill an internal order: remove finished units from inventory. This NEVER
    deducts filament. Idempotent on the order's fulfillment token, so a retry can't
    deduct finished goods twice."""
    # Lock + re-read the order to serialize concurrent fulfillments.
    order = InternalOrder.objects.select_for_update().get(pk=order.pk)
    if order.status == 'fulfilled':
        return order
    if order.status == 'cancelled':
        raise ValidationError('Cannot fulfill a cancelled internal order.')

    token = fulfillment_token or order.fulfillment_token or uuid_hex()
    for line in order.lines.select_related('variant').all():
        post_movement(
            movement_type='fulfillment', product_variant=line.variant,
            quantity=-Decimal(line.quantity), unit=UnitChoices.EACH, actor=actor,
            reason=f'Internal order ({order.get_purpose_display()})',
            occurred_at=occurred_at, idempotency_key=f'{token}:ful:{line.pk}',
        )
    order.status = 'fulfilled'
    order.fulfilled_at = timezone.now()
    order.fulfillment_token = token
    order.save(update_fields=['status', 'fulfilled_at', 'fulfillment_token'])
    record_audit(actor, 'update', order, summary='Internal order fulfilled (finished goods out)')
    return order


@transaction.atomic
def create_and_fulfill_internal_order(*, purpose, lines, actor, notes='', ordered_on=None,
                                      occurred_at=None, fulfillment_token=None):
    """Convenience for the historical flow: create an internal order and fulfill it
    immediately, keeping the order and fulfillment as distinct records.

    If ``fulfillment_token`` is given and an order already carries it, that order is
    returned unchanged (idempotent re-run — no second order, no double deduction)."""
    if fulfillment_token:
        existing = InternalOrder.objects.filter(fulfillment_token=fulfillment_token).first()
        if existing is not None:
            return existing
    order = create_internal_order(purpose=purpose, lines=lines, actor=actor, notes=notes,
                                  ordered_on=ordered_on)
    return fulfill_internal_order(order=order, actor=actor, occurred_at=occurred_at,
                                  fulfillment_token=fulfillment_token)


def uuid_hex():
    import uuid
    return uuid.uuid4().hex
