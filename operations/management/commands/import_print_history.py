"""Import historical print-room purchases, inventory, products and production.

This command is GENERIC and contains **no business data**. All of the actual
purchases, prices, order numbers, filament and production history live in an
external JSON file that is NOT committed to the repository (keep it private, e.g.
under ``~/beacon-backups/``). Pass it with ``--data``.

Design goals (match the operations architecture, never bypass it):

* **Idempotent / re-runnable.** Natural keys and stable tokens mean a second run
  creates nothing new and never double-counts:
  - Purchase            → (supplier, order_number)
  - PurchaseLine        → (purchase, description)
  - FilamentSpool       → spool_uid
  - Equipment           → (source purchase line)  [or name when no line]
  - stock receipt       → movement idempotency_key
  - PrintLog            → submission_token
  - InternalOrder       → fulfillment_token
* **Uses the service layer** for everything that touches the ledger, finance or
  audit (``operations.services``), so every mutation is audited and safe.
* **No finance expense is created.** Receiving stock/filament and opening balances
  never create a ``finance.Transaction`` (that bridge stays manual). An order
  confirmation is not proof of a settled payment; expenses are added later, once,
  against the correct account.
* **Filament grams are optional.** Spools can be marked ``remaining_unknown`` and
  are then tracked by status only — no weight is invented, and prints can be
  recorded with no filament usage at all.
* **Received ≠ ordered.** Only lines flagged ``received`` create inventory; the
  rest stay outstanding (recorded as a purchase line, no stock).

Run a PREVIEW first (default), check the reconciliation, then ``--apply``.
"""
import json
import os
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.contrib.auth import get_user_model
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from operations import models as m
from operations import services

ZERO = Decimal('0')
CENT = Decimal('0.01')


def D(v):
    if v in (None, ''):
        return ZERO
    return Decimal(str(v)).quantize(CENT, rounding=ROUND_HALF_UP)


def to_date(v):
    """Parse an ISO 'YYYY-MM-DD' string to a date (pass through date/None)."""
    if v in (None, ''):
        return None
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v))


class Command(BaseCommand):
    help = 'Import historical print-room purchases/inventory/products/production from a private JSON file.'

    def add_arguments(self, parser):
        parser.add_argument('--data', required=True, help='Path to the private import JSON (not in the repo).')
        parser.add_argument('--apply', action='store_true', help='Write to the database (default: preview only).')

    # ------------------------------------------------------------------ helpers
    def resolve_actor(self, username):
        User = get_user_model()
        try:
            return User.objects.get(username=username)
        except User.DoesNotExist:
            raise CommandError(f'Actor user {username!r} not found in this database.')

    def line_total(self, ln):
        return D(ln.get('quantity', 0)) * D(ln.get('unit_cost', 0)) - D(ln.get('line_discount', 0)) + D(ln.get('line_tax', 0))

    def purchase_computed_total(self, p):
        sub = sum((self.line_total(ln) for ln in p.get('lines', [])), ZERO)
        return sub + D(p.get('shipping_total', 0)) + D(p.get('tax_total', 0)) - D(p.get('discount_total', 0))

    # ------------------------------------------------------------------ preview
    def preview(self, data):
        out = self.stdout.write
        out('=== IMPORT PREVIEW (no changes written) ===\n')
        grand = ZERO
        problems = []
        out('\nPurchases / reconciliation:')
        for p in data['purchases']:
            computed = self.purchase_computed_total(p)
            expected = D(p.get('expected_total', 0))
            grand += computed
            ok = 'OK' if computed == expected else f'MISMATCH (Δ {computed - expected})'
            if computed != expected:
                problems.append(f"{p['order_number']}: computed {computed} vs expected {expected}")
            recv = sum(1 for ln in p['lines'] if ln.get('received'))
            out(f"  {p['supplier']:14} {p['order_number']:24} computed ${computed:>8} / expected ${expected:>8}  {ok}"
                f"  ({len(p['lines'])} lines, {recv} received)")
        out(f"\n  GRAND TOTAL of included purchases: ${grand}")

        # Counts of what would be created
        spool_specs = [s for p in data['purchases'] for ln in p['lines']
                       if ln['item_type'] == 'filament' and ln.get('received') for s in ln.get('spools', [])]
        equip = [ln for p in data['purchases'] for ln in p['lines']
                 if ln['item_type'] == 'equipment' and ln.get('received')]
        equip_out = [ln for p in data['purchases'] for ln in p['lines']
                     if ln['item_type'] == 'equipment' and not ln.get('received')]
        stock_recv = [ln for p in data['purchases'] for ln in p['lines']
                      if ln['item_type'] == 'stock' and ln.get('received') and ln.get('track_inventory', True)]
        outstanding = [ln for p in data['purchases'] for ln in p['lines'] if not ln.get('received')]
        out('\nWould create:')
        out(f"  suppliers: {len(data.get('suppliers', []))}, locations: {len(data.get('locations', []))}, "
            f"filament materials: {len(data.get('filament_materials', []))}")
        out(f"  purchases: {len(data['purchases'])}, purchase lines: {sum(len(p['lines']) for p in data['purchases'])}")
        out(f"  filament spools/refills received: {len(spool_specs)} "
            f"(refills: {sum(1 for s in spool_specs if s.get('is_refill'))}, "
            f"gift $0: {sum(1 for s in spool_specs if D(s.get('cost', 0)) == ZERO)})")
        out(f"  equipment received: {len(equip)}; equipment outstanding (not received): {len(equip_out)}")
        out(f"  stock lines received into inventory: {len(stock_recv)}")
        out(f"  outstanding lines (ordered, not received): {len(outstanding)}")
        docs = [p for p in data['purchases'] if p.get('document')]
        out(f"  private documents to attach: {len(docs)}")
        out(f"  products: {len(data.get('products', []))}, "
            f"variants: {sum(len(pr.get('variants', [])) for pr in data.get('products', []))}")
        out(f"  prints: {len(data.get('prints', []))} "
            f"(in-progress: {sum(1 for pr in data.get('prints', []) if pr.get('outcome') == 'in_progress')})")
        out(f"  internal orders (fulfilled, no payment): {len(data.get('internal_orders', []))}")

        if problems:
            out('\n!! RECONCILIATION PROBLEMS:')
            for pr in problems:
                out(f'   - {pr}')
        else:
            out('\nAll purchases reconcile to the penny.')
        return not problems

    # -------------------------------------------------------------------- apply
    def apply(self, data):
        actor = self.resolve_actor(data['actor_username'])
        tag = data['import_tag']
        out = self.stdout.write

        suppliers = {}
        for name in data.get('suppliers', []):
            s, _ = m.Supplier.objects.get_or_create(name=name)
            suppliers[name] = s
        locations = {}
        for loc in data.get('locations', []):
            l, _ = m.Location.objects.get_or_create(name=loc['name'], defaults={'kind': loc.get('kind', 'shelf')})
            locations[loc['name']] = l

        fil_materials = {}
        for fm in data.get('filament_materials', []):
            mat, _ = m.Material.objects.get_or_create(
                material_type='filament', manufacturer=fm.get('manufacturer', ''),
                product_type=fm.get('product_type', ''), name=fm['name'], sku=fm.get('sku', ''),
                defaults={'color_code': fm.get('color_code', ''), 'default_unit': 'g',
                          'nominal_spool_weight_g': fm.get('nominal_spool_weight_g'),
                          'notes': fm.get('notes', ''), 'created_by': actor})
            fil_materials[fm['key']] = mat

        def stock_material(ln):
            return m.Material.objects.get_or_create(
                material_type=ln.get('stock_category', 'consumable'),
                manufacturer='', name=ln['material_name'],
                defaults={'default_unit': ln.get('unit', 'each'), 'notes': ln.get('description', ''),
                          'created_by': actor})[0]

        # --- Purchases ---
        for p in data['purchases']:
            supplier = suppliers.get(p['supplier'])
            purchase, created = m.Purchase.objects.get_or_create(
                supplier=supplier, order_number=p['order_number'],
                defaults={'order_date': to_date(p['order_date']), 'tax_total': D(p.get('tax_total', 0)),
                          'shipping_total': D(p.get('shipping_total', 0)),
                          'discount_total': D(p.get('discount_total', 0)),
                          'product_links': p.get('product_links', ''), 'notes': p.get('notes', ''),
                          'created_by': actor})
            if created:
                services.record_audit(actor, 'create', purchase, summary=f'Imported purchase ({tag})')

            # Document (private DB storage) — attach once.
            doc_path = p.get('document')
            if doc_path and not purchase.documents.filter(original_filename=os.path.basename(doc_path)).exists():
                if os.path.exists(doc_path):
                    with open(doc_path, 'rb') as fh:
                        size = os.fstat(fh.fileno()).st_size
                        doc = m.PurchaseDocument(
                            purchase=purchase, original_filename=os.path.basename(doc_path),
                            file_type=os.path.splitext(doc_path)[1].lstrip('.').lower() or 'pdf',
                            file_size=size, uploaded_by=actor)
                        doc.file.save(os.path.basename(doc_path), File(fh), save=True)
                    services.record_audit(actor, 'create', doc, summary='Private purchase document attached')
                else:
                    out(f'  ! document missing, skipped: {doc_path}')

            for idx, ln in enumerate(p['lines']):
                material = None
                if ln['item_type'] == 'filament':
                    material = fil_materials[ln['material_key']]
                elif ln['item_type'] == 'stock':
                    material = stock_material(ln)
                line, _ = m.PurchaseLine.objects.get_or_create(
                    purchase=purchase, description=ln['description'],
                    defaults={'item_type': ln['item_type'], 'material': material,
                              'quantity_ordered': D(ln.get('quantity', 1)), 'unit': ln.get('unit', 'each'),
                              'unit_cost': D(ln.get('unit_cost', 0)), 'line_discount': D(ln.get('line_discount', 0)),
                              'line_tax': D(ln.get('line_tax', 0)), 'use_type': ln.get('use_type', 'business')})

                if not ln.get('received'):
                    continue  # outstanding — recorded as a line, no inventory

                loc = locations.get(ln.get('location'))
                if ln['item_type'] == 'filament':
                    for si, spec in enumerate(ln.get('spools', [])):
                        services.receive_filament_spool(
                            line=line, spool_uid=spec['uid'], actor=actor,
                            starting_weight_g=D(spec.get('starting_weight_g', 0)),
                            remaining_unknown=spec.get('remaining_unknown', True),
                            is_refill=spec.get('is_refill', False), status=spec.get('status', 'sealed'),
                            cost=(None if spec.get('cost') is None else D(spec.get('cost'))),
                            cost_unknown=spec.get('cost_unknown', False), location=loc,
                            notes=spec.get('notes', ''),
                            idempotency_key=f'{tag}:{p["order_number"]}:{idx}:sp{si}')
                elif ln['item_type'] == 'equipment':
                    if not m.Equipment.objects.filter(source_line=line).exists():
                        eq = ln['equipment']
                        services.receive_equipment_line(
                            line=line, actor=actor, name=eq['name'],
                            equipment_type=eq.get('equipment_type', 'other'),
                            location=locations.get(eq.get('location')),
                            cost=(None if eq.get('cost') is None else D(eq.get('cost'))),
                            manufacturer=eq.get('manufacturer', ''), model=eq.get('model', ''))
                elif ln['item_type'] == 'stock':
                    if ln.get('track_inventory', True):
                        services.receive_stock_line(
                            line=line, quantity=D(ln.get('quantity', 1)), actor=actor, location=loc,
                            idempotency_key=f'{tag}:{p["order_number"]}:{idx}:recv')

        # --- Products + variants ---
        variants = {}
        for pr in data.get('products', []):
            product, _ = m.PhysicalProduct.objects.get_or_create(
                name=pr['name'],
                defaults={'description': pr.get('description', ''), 'design_source': pr.get('design_source', ''),
                          'file_reference': pr.get('file_reference', ''),
                          'internal_only': pr.get('internal_only', True),
                          'catalog_eligible': pr.get('catalog_eligible', False), 'created_by': actor})
            for v in pr.get('variants', []):
                variant, _ = m.ProductVariant.objects.get_or_create(
                    product=product, name=v.get('name', 'Default'), defaults={'notes': v.get('notes', '')})
                variants[v['key']] = variant

        # --- Prints (idempotent on submission_token) ---
        for pr in data.get('prints', []):
            printer = None
            if pr.get('printer_name'):
                printer = m.Equipment.objects.filter(name=pr['printer_name'], equipment_type='printer').first()
            products = [{'variant': variants[x['variant_key']], 'recipe': None,
                         'quantity_planned': x.get('quantity_planned', 0),
                         'quantity_success': x.get('quantity_success', 0)} for x in pr.get('products', [])]
            services.log_print(
                name=pr['name'], printer=printer, purpose=pr.get('purpose', 'business'),
                outcome=pr.get('outcome', 'success'), notes=pr.get('notes', ''), uses=[],
                actor=actor, products=products, is_historical=pr.get('is_historical', False),
                printed_on=to_date(pr.get('printed_on')), submission_token=pr['token'])

        # --- Internal orders (idempotent on fulfillment_token; no payment) ---
        for io in data.get('internal_orders', []):
            lines = [{'variant': variants[x['variant_key']], 'quantity': x['quantity']} for x in io.get('lines', [])]
            services.create_and_fulfill_internal_order(
                purpose=io.get('purpose', 'personal'), lines=lines, actor=actor,
                notes=io.get('notes', ''), ordered_on=to_date(io.get('ordered_on')),
                fulfillment_token=io['token'])

        out(self.style.SUCCESS('Apply complete.'))

    # ------------------------------------------------------------------- handle
    def handle(self, *args, **opts):
        path = opts['data']
        if not os.path.exists(path):
            raise CommandError(f'Data file not found: {path}')
        with open(path) as fh:
            data = json.load(fh)

        ok = self.preview(data)
        if not opts['apply']:
            self.stdout.write('\n(Preview only. Re-run with --apply to write.)')
            return
        if not ok:
            raise CommandError('Reconciliation problems found — fix the data before applying.')
        self.stdout.write('\nApplying…')
        self.apply(data)
        # Re-preview counts from DB for a quick post-apply sanity line.
        self.stdout.write(self.style.SUCCESS('\nDone. Verify with the operations screens / a DB count.'))
