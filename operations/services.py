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
    AuditEvent, FilamentSpool, InventoryMovement, Location, Material,
    PrintLog, PrintMaterialUse, Purchase, PurchaseLine, PurchasePayment,
    ScaleMeasurement, StockItem, UnitChoices,
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

def _current_quantity(spool=None, stock_item=None):
    from django.db.models import Sum
    qs = InventoryMovement.objects.all()
    if spool is not None:
        qs = qs.filter(spool=spool)
    else:
        qs = qs.filter(stock_item=stock_item)
    return qs.aggregate(t=Sum('quantity'))['t'] or ZERO


@transaction.atomic
def post_movement(*, movement_type, quantity, unit, actor, spool=None, stock_item=None,
                  reason='', occurred_at=None, purchase_line=None, print_use=None,
                  reverses=None, idempotency_key=None, allow_negative=False):
    """Append one movement to the ledger, atomically and safely.

    * Exactly one of ``spool`` / ``stock_item`` must be given.
    * ``quantity`` is signed (+ adds, − removes).
    * The target row is locked for the duration so concurrent deductions are
      serialized; a deduction that would make on-hand negative is rejected unless
      ``allow_negative``.
    * If ``idempotency_key`` is given and already used, the existing movement is
      returned unchanged (safe retry) and no new row/audit is written.
    """
    if (spool is None) == (stock_item is None):
        raise ValidationError('A movement must target exactly one spool or one stock item.')

    if idempotency_key:
        existing = InventoryMovement.objects.filter(idempotency_key=idempotency_key).first()
        if existing is not None:
            return existing

    # Lock the target so two concurrent deductions can't both pass the check.
    if spool is not None:
        FilamentSpool.objects.select_for_update().get(pk=spool.pk)
    else:
        StockItem.objects.select_for_update().get(pk=stock_item.pk)

    quantity = Decimal(quantity)
    if quantity < ZERO and not allow_negative:
        current = _current_quantity(spool=spool, stock_item=stock_item)
        if current + quantity < ZERO:
            target = spool or stock_item
            raise InsufficientStockError(
                f'Not enough on hand for {target}: have {current} {unit}, '
                f'tried to remove {abs(quantity)} {unit}. Weigh/recount the item and '
                f'post a reconciliation adjustment before consuming more.'
            )

    movement = InventoryMovement.objects.create(
        movement_type=movement_type,
        spool=spool,
        stock_item=stock_item,
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
    immutable; a movement can only be reversed once."""
    if movement.movement_type == 'reversal':
        raise ValidationError('A reversal cannot itself be reversed.')
    if movement.reversed_by.exists():
        raise ValidationError('This movement has already been reversed.')
    return post_movement(
        movement_type='reversal',
        spool=movement.spool,
        stock_item=movement.stock_item,
        quantity=-movement.quantity,
        unit=movement.unit,
        actor=actor,
        reason=reason or f'Reversal of {movement.get_movement_type_display().lower()}',
        reverses=movement,
        allow_negative=True,  # reversing a prior receipt may legitimately go to 0
    )


# =============================================================================
# Opening inventory (never creates a finance expense)
# =============================================================================

@transaction.atomic
def enter_opening_spool(*, material, spool_uid, starting_weight_g, actor,
                        tare_weight_g=None, cost=None, cost_unknown=False,
                        location=None, status='open', notes='', occurred_at=None):
    """Create a spool you already own and seed it with an opening-balance movement.
    No finance expense is created."""
    spool = FilamentSpool.objects.create(
        material=material, spool_uid=spool_uid, starting_weight_g=Decimal(starting_weight_g),
        tare_weight_g=tare_weight_g, cost=(None if cost_unknown else cost),
        cost_unknown=cost_unknown, location=location, status=status, notes=notes,
        created_by=actor if (actor and getattr(actor, 'is_authenticated', False)) else None,
    )
    record_audit(actor, 'create', spool, summary='Opening spool entered')
    if Decimal(starting_weight_g) > ZERO:
        post_movement(
            movement_type='opening_balance', spool=spool,
            quantity=Decimal(starting_weight_g), unit=UnitChoices.GRAM, actor=actor,
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
                       idempotency_key=None):
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
        defaults={'created_by': actor if (actor and getattr(actor, 'is_authenticated', False)) else None},
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
# Printing (consumption + waste, each counted once; failures still consume)
# =============================================================================

@transaction.atomic
def log_print(*, name, printer, purpose, outcome, success_quantity, notes, uses, actor,
              printed_on=None, submission_token=None):
    """Record a print and deduct its filament.

    ``uses`` is a list of dicts: ``spool``, ``grams_consumed``, ``waste_grams``.
    For each, a ``consumption`` movement (grams into the part) and a separate
    ``waste`` movement (purge/support/failure) are posted — each deducts once, so
    waste is never double-counted. Failed prints still consume material. The whole
    operation is idempotent on ``submission_token``.
    """
    if submission_token:
        existing = PrintLog.objects.filter(submission_token=submission_token).first()
        if existing is not None:
            return existing

    print_log = PrintLog.objects.create(
        name=name, printed_on=printed_on or timezone.localdate(), printer=printer,
        purpose=purpose, outcome=outcome, success_quantity=success_quantity or 0,
        notes=notes, submission_token=submission_token or None,
        created_by=actor if (actor and getattr(actor, 'is_authenticated', False)) else None,
    )
    record_audit(actor, 'create', print_log, summary=f'Print logged ({outcome})')

    for u in uses:
        grams_consumed = Decimal(u.get('grams_consumed') or 0)
        waste_grams = Decimal(u.get('waste_grams') or 0)
        if grams_consumed <= ZERO and waste_grams <= ZERO:
            continue
        pmu = PrintMaterialUse.objects.create(
            print_log=print_log, spool=u['spool'],
            grams_consumed=grams_consumed, waste_grams=waste_grams,
        )
        base = (submission_token or print_log.pk)
        if grams_consumed > ZERO:
            post_movement(
                movement_type='consumption', spool=u['spool'], quantity=-grams_consumed,
                unit=UnitChoices.GRAM, actor=actor, reason=f'Print: {name}',
                print_use=pmu, idempotency_key=(f'{base}:{pmu.pk}:c'),
            )
        if waste_grams > ZERO:
            post_movement(
                movement_type='waste', spool=u['spool'], quantity=-waste_grams,
                unit=UnitChoices.GRAM, actor=actor, reason=f'Print waste: {name}',
                print_use=pmu, idempotency_key=(f'{base}:{pmu.pk}:w'),
            )
    return print_log


# =============================================================================
# Weigh-in + reconciliation (measured vs estimated)
# =============================================================================

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
