"""One-time, idempotent, audited corrections to the imported print-room records.

Fixes applied to EXISTING records (the importer's get_or_create only sets fields on
create, so these in-place corrections are done here instead of by re-importing):

1. Consolidate every location into a single "Home Office / Print Room" (room).
2. Benchy — record one production output + one no-payment internal fulfillment
   (it was imported as a 0-output sample; it is a kept physical item).
3. Cable ties (order 111-0612057) — receive them (delivered Oct 31); the glue
   stick on the same order stays outstanding.
4. Bambu order 2 refills — mark delivery UNCONFIRMED (no delivery evidence), so
   they are not shown as confirmed on-hand.
5. TESSAN surge protector — mark delivery UNCONFIRMED (shipped, not confirmed).
6. Historical prints — mark date_unknown so screens stop showing the import date
   as if it were the print date.
7. Purchases — label funding "Paid personally" (owner confirmation).

Idempotent + guarded: a marker audit event is written when done; re-running is a
no-op (so it cannot overwrite later user edits). ``--apply`` to write; default is a
preview. Nothing is deleted or rebuilt; the import and its audit history stay.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Sum

from operations import models as m
from operations import services

MARKER = 'print-history-correction-2026-11 applied'
BAMBU2 = 'us792642123445854209'
TESSAN = 'C-876-00002414583'
CABLE_ORDER = '111-0612057-9983435'
TARGET_LOCATION = 'Home Office / Print Room'


class Command(BaseCommand):
    help = 'Apply one-time corrections to the imported operations records (idempotent).'

    def add_arguments(self, parser):
        parser.add_argument('--actor', default='dannyjenkins71@gmail.com')
        parser.add_argument('--apply', action='store_true', help='Write changes (default: preview).')
        parser.add_argument('--force', action='store_true', help='Run even if the marker is present.')

    def handle(self, *args, **opts):
        out = self.stdout.write
        User = get_user_model()
        try:
            actor = User.objects.get(username=opts['actor'])
        except User.DoesNotExist:
            raise CommandError(f'Actor {opts["actor"]!r} not found.')

        already = m.AuditEvent.objects.filter(summary=MARKER).exists()
        if already and not opts['force']:
            out('Corrections already applied (marker present) — nothing to do.')
            return

        plan = self._plan()
        out('=== CORRECTION PLAN ===')
        for label, detail in plan:
            out(f'  [{"TODO" if detail else "done"}] {label}: {detail or "already correct"}')

        if not opts['apply']:
            out('\n(Preview only. Re-run with --apply to write.)')
            return

        out('\nApplying…')
        self._apply(actor)
        # Marker on the consolidated location (a stable, existing row).
        target = m.Location.objects.filter(name=TARGET_LOCATION).first()
        if target:
            services.record_audit(actor, 'update', target, summary=MARKER)
        out(self.style.SUCCESS('Corrections applied.'))

    # ------------------------------------------------------------------ preview
    def _plan(self):
        rows = []
        extra_locs = m.Location.objects.exclude(name=TARGET_LOCATION).count()
        rows.append(('Consolidate locations', f'{extra_locs} to merge' if extra_locs else ''))

        bv = m.ProductVariant.objects.filter(product__name='Benchy').first()
        produced = 0
        if bv:
            produced = bv.movements.filter(movement_type='production_output').aggregate(t=Sum('quantity'))['t'] or 0
        rows.append(('Benchy production + fulfillment', 'needed' if produced == 0 else ''))

        ct = m.PurchaseLine.objects.filter(purchase__order_number=CABLE_ORDER,
                                           description__icontains='Cable Ties').first()
        rows.append(('Receive cable ties', 'needed' if (ct and ct.receipt_state == 'none') else ''))

        b2 = m.FilamentSpool.objects.filter(source_line__purchase__order_number=BAMBU2, delivery_confirmed=True).count()
        rows.append(('Bambu order 2 → delivery unconfirmed', f'{b2} spools' if b2 else ''))

        tz = m.StockItem.objects.filter(material__name__icontains='TESSAN', delivery_confirmed=True).count()
        rows.append(('TESSAN → delivery unconfirmed', f'{tz} item' if tz else ''))

        hp = m.PrintLog.objects.filter(is_historical=True, date_unknown=False).count()
        rows.append(('Historical prints → date unknown', f'{hp} prints' if hp else ''))

        pf = m.Purchase.objects.filter(funding='').count()
        rows.append(('Purchases → Paid personally', f'{pf} purchases' if pf else ''))
        return rows

    # -------------------------------------------------------------------- apply
    def _apply(self, actor):
        # 1) Locations -> single "Home Office / Print Room" (room).
        target, _ = m.Location.objects.get_or_create(
            name=TARGET_LOCATION, defaults={'kind': 'room'})
        if target.kind != 'room':
            target.kind = 'room'
            target.save(update_fields=['kind'])
        sources = list(m.Location.objects.exclude(pk=target.pk))
        if sources:
            services.merge_locations(target=target, sources=sources, actor=actor)

        # 2) Benchy: one production output + one no-payment internal fulfillment.
        bv = m.ProductVariant.objects.filter(product__name='Benchy').first()
        if bv:
            produced = bv.movements.filter(movement_type='production_output').aggregate(t=Sum('quantity'))['t'] or 0
            if produced == 0:
                pp = m.PrintProduct.objects.filter(variant=bv).first()
                if pp and pp.quantity_success == 0:
                    pp.quantity_success = 1
                    pp.save(update_fields=['quantity_success'])
                services.post_movement(
                    movement_type='production_output', product_variant=bv,
                    quantity=Decimal('1'), unit=m.UnitChoices.EACH, actor=actor,
                    reason='Produced: Benchy (correction)', idempotency_key='correct:benchy:prod')
                services.create_and_fulfill_internal_order(
                    purpose='personal',
                    lines=[{'variant': bv, 'quantity': 1}], actor=actor,
                    notes='Benchy kept (calibration/sample) — no payment required.',
                    fulfillment_token='import:io:benchy')

        # 3) Cable ties — receive; glue stick stays outstanding.
        ct = m.PurchaseLine.objects.filter(purchase__order_number=CABLE_ORDER,
                                           description__icontains='Cable Ties').first()
        if ct and ct.receipt_state == 'none' and ct.material:
            loc = m.Location.objects.filter(name=TARGET_LOCATION).first()
            services.receive_stock_line(line=ct, quantity=Decimal('1'), actor=actor, location=loc,
                                        delivery_confirmed=True, idempotency_key='correct:cableties:recv')
            ct.delivery = 'received'
            ct.save(update_fields=['delivery'])

        # 4) Bambu order 2 → delivery unconfirmed.
        for s in m.FilamentSpool.objects.filter(source_line__purchase__order_number=BAMBU2, delivery_confirmed=True):
            s.delivery_confirmed = False
            s.save(update_fields=['delivery_confirmed'])
            services.record_audit(actor, 'update', s, summary='Delivery marked unconfirmed (no delivery evidence)')
        m.PurchaseLine.objects.filter(purchase__order_number=BAMBU2).exclude(delivery='unconfirmed').update(delivery='unconfirmed')

        # 5) TESSAN surge protector → delivery unconfirmed.
        for si in m.StockItem.objects.filter(material__name__icontains='TESSAN', delivery_confirmed=True):
            si.delivery_confirmed = False
            si.save(update_fields=['delivery_confirmed'])
            services.record_audit(actor, 'update', si, summary='Delivery marked unconfirmed (shipped, not confirmed)')
        m.PurchaseLine.objects.filter(purchase__order_number=TESSAN).exclude(delivery='unconfirmed').update(delivery='unconfirmed')

        # 6) Historical prints → date unknown (honest dates).
        for p in m.PrintLog.objects.filter(is_historical=True, date_unknown=False):
            p.date_unknown = True
            p.save(update_fields=['date_unknown'])

        # 7) Purchases → Paid personally.
        m.Purchase.objects.filter(funding='').update(funding='personal')
