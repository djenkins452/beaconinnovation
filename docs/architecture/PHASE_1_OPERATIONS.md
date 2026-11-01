# Phase 1 — Operations module (3D-printing) — implemented

**App:** `operations` (staff-only) · **Branch:** `phase-1-operations`
**Status:** implemented, tested locally against PostgreSQL, deployed to Beacon.
**Builds on:** Phase 0 (durable Postgres + private DB-backed file storage — see
`PHASE_0_DURABILITY.md`) and the discovery in `PRINT_BUSINESS_OS_DISCOVERY.md` (§7, §9).

This is the "track what I buy, own, and print" release. It is intentionally the
smallest useful system: purchasing, inventory, and print-logging on an auditable
movement ledger. Products/recipes, orders, a storefront, and a full costing engine
are **not** built (see Boundaries).

---

## What it does

A staff-only area at **`/operations/`** with navigable screens (not just Django
admin). Gate: authenticated **and** `is_staff`; non-staff get a 404 (same pattern
as `admin_console`).

- **Dashboard** `/operations/` — stock summary, items at/below reorder threshold,
  recent movements and prints, quick actions.
- **Purchases** `/operations/purchases/` — supplier, order date/number, product
  links, order-level shipping/tax/discount, and **purchase lines** (ordered vs
  received qty, unit cost, per-line discount/tax, and a **business / personal /
  shared** use split with % business). Partial receipt supported. Private
  receipt/invoice upload per purchase.
- **Receive a line** — turns a line into inventory: filament → individual
  **spools**; stock → quantity on hand; equipment → an **asset record** (not stock,
  no movement). Receiving **never** creates a finance expense.
- **Spools** `/operations/spools/` — per-spool tracking: manufacturer/material/
  color (via Material), spool ID, starting weight, tare, cost, location, status.
  Estimated remaining (from the ledger) is shown **separately** from measured
  (from a weigh-in). Weigh-in + one-click **reconcile** posts an adjustment.
- **Stock** `/operations/stock/` — hardware/consumables/packaging quantities, with
  available vs damaged/unusable buckets.
- **Materials** `/operations/materials/` — the catalog + reorder thresholds.
- **Prints** `/operations/prints/` — print name/date/printer/purpose/outcome, with
  **multiple spools per print**; records filament **into the part** and **waste**
  (purge/support) separately so waste is never double-counted. **Failed prints
  still consume material.** Successful quantity is recorded for reference
  (finished-goods inventory is deferred).
- **Opening inventory** `/operations/opening/` — enter things you already own
  (including partly-used spools; costs optional/unknown). Creates stock via
  opening-balance movements and **never** a finance expense.
- **Inventory history** `/operations/history/` — the full movement ledger.
  Immutable; corrections are **reversing** entries (the original is preserved).
- Supporting screens: Equipment, Suppliers, Locations.

## The spine: an append-only movement ledger

Every gram and unit changes only through an `InventoryMovement`
(`purchase_receipt`, `opening_balance`, `consumption`, `waste`, `return`,
`adjustment`, `reversal`). **On hand = Σ(movements).** There is no mutable quantity
counter. Movements are immutable (`save`/`delete` are blocked); corrections are new
movements. Every mutation goes through `operations/services.py`, which also writes
an **immutable `AuditEvent`** (the wired-audit discipline from `aegis.core` that
finance's `AuditLogMixin` never got).

- **Concurrency / double-submit:** deductions lock the target row
  (`select_for_update`) and re-check sufficiency, and each receive/print submission
  carries an idempotency key/token, so a double-click or retry cannot post twice.
- **Insufficient stock:** a consumption that would go below zero is rejected with a
  message pointing to weigh-in + reconciliation.
- **Decimals/units:** grams `Decimal(12,2)`, counts `Decimal(12,3)`, money
  `Decimal(12,2)`; units are explicit on every quantity.

## Finance linking — manual vs automatic

| Link | Mode | How |
|---|---|---|
| Purchase **receipt** → inventory movements | **Automatic** | Receiving a line posts receipt movements. No expense is ever created here. |
| Opening inventory → inventory movements | **Automatic** | Opening-balance movements; no expense. |
| Purchase → finance **expense** (money) | **Manual** | On a purchase, either **link an existing** finance expense or **create one** expense and link it (`PurchasePayment`). |

This keeps money counted **once**: receiving the goods (asset side) and recording
the expense (cash side) are deliberately separate actions. A purchase may have
zero, one, or several linked payments — no single-payment assumption. The same
finance transaction cannot be linked to a purchase twice (DB constraint).

## File storage (and its cost)

Purchase receipts/invoices reuse the **Phase 0 private DB-backed storage**
(`finance.storage.database_storage`): bytes live in PostgreSQL, there is **no
public URL**, and files are served only through the staff-gated operations views.
No Railway Volume or other paid resource was added.

**Disclosure (not "free"):** these document bytes and the operations rows live in
the managed Postgres database, so they add to database size and to backup size.
Inventory/movement/print rows are tiny; uploaded documents are the only material
contributor (PDF/JPG/PNG, capped by `FINANCE_RECEIPT_MAX_SIZE_MB`, default 10 MB
each). At this shop's volume the growth is negligible, but it is real DB usage. If
document volume ever grows, moving them to a Railway Volume or object storage is a
drop-in change — but that is billable and must be approved first.

## Validation (synthetic data only)

`operations/tests/` — 23 tests, all passing on PostgreSQL. They assert:
opening inventory creates stock with **no expense**; partial then full receipts;
**exactly one** expense per purchase (no double count); multicolor and **failed**
prints deduct correctly; **waste counted once**; duplicate submissions don't
duplicate movements; reversals are auditable and preserve the original;
reconciliation adjusts estimate → measured; insufficient-stock is rejected; and
every screen renders for staff while non-staff (and anonymous) are denied both the
screens and the document attachments. No real purchase data was loaded.

## Boundaries (not built — kept compatible for later)

Not built, per the brief: storefront/public surface, customer orders, quotes,
personalization approvals, production scheduling, automated pricing, printer
integration, QR labeling, full costing engine. No **reservations** (no workflow
needs them yet). Finance behavior, private file storage, and aegis DB isolation are
unchanged (operations lives in Beacon's `default` DB; aegis stays dormant).

## Known limitations / deferred decisions

- **Finished-goods inventory is deferred** — a successful print records a reference
  count but does not create sellable stock.
- **Business/personal/shared split** is captured per purchase line for reporting;
  it does not yet post split entries into finance.
- **Receiving unit vs spool unit:** filament spools are tracked in grams while a
  purchase line may be ordered in rolls/kg; the line's received counter is in its
  own unit and spools carry grams. This is intentional, not a reconciliation.
- **Reorder thresholds** are a simple on-hand comparison (no net-of-incoming).
- Admin registrations exist for convenience; the ledger and audit log are
  **read-only** in admin to preserve immutability.

---

# Phase 1b — products, recipes, production, internal orders, finished goods

Extends the module to the clarified workflow: each distinct printed design is a
**product**; recipes know expected usage; prints deduct consumption and add
successful units to **finished-goods inventory**; **internal orders** (no payment)
remove finished units; and history can be **reconstructed** chronologically.

## New concepts

- **PhysicalProduct → ProductVariant** — a distinct printed design (separate from
  `products.Product`, the software-download model), including internal-only items
  (bins, swatches, printer accessories). `internal_only` vs `catalog_eligible`
  flags keep it compatible with a future public catalog without building one.
  Every product gets a `Default` variant; variants cover size/material/profile
  differences that change consumption.
- **ProductionRecipe (versioned) + RecipeMaterial** — expected filament per unit
  by material/color: `grams_per_unit` (into part) + `waste_per_unit` (per-unit
  supports). Saving edits a **new version**; old versions are preserved and a
  print snapshots the version it used (`PrintProduct.recipe`), so recipe changes
  never rewrite past consumption. Waste does **not** auto-scale: per-unit waste is
  in the recipe; shared batch purge/support is entered once at print time.
- **Finished-goods inventory** — the movement ledger gained a third target
  (`InventoryMovement.product_variant`) and two types: `production_output` (+ units,
  from a print's successful quantities) and `fulfillment` (− units, from an
  internal order). `ProductVariant.on_hand = Σ(its movements)`.
- **InternalOrder → InternalOrderLine** — staff-only, **no payment** (shows "No
  payment required", never "Paid"), kept entirely separate from any customer
  sales/revenue. Fulfilling removes finished units — it **never** deducts filament.
  Not reachable by any public/email-based path; it is an explicit back-office
  screen behind the staff gate.

## Production (extends the existing print log — one workflow, not two)

The print form now also selects **products + planned/good quantities** and the
actual spools. A **Suggest filament from recipe** button prefills expected grams
from the selected products' current recipes. Each spool row labels its **source**
(recipe estimate / slicer total / measured) and has an **all-inclusive** flag: when
ticked, the grams figure already includes supports/purge and waste is **not added
again**. Consumption and waste each post exactly one movement. **Failed/cancelled**
prints deduct what you enter (actual/estimate), never the full plan. Only
**successful** units become finished inventory. Idempotency, concurrency locking,
audit, and reversal rules are unchanged; a correction is still a reversing movement
— and a reversal now **respects stock sufficiency**, so it cannot drive either
inventory negative (reverse the later movement first).

## Reconstructing the first days

A **Reconstruct history** guide (`/operations/prints/reconstruct/`) lays out the
order of operations. Spools are entered at their **full 1,000 g** start (not today's
remaining weight); each historical print is logged **back-dated** (the
`is_historical` flag sets the movements' `occurred_at` to the print date, so the
ledger is chronological). For items already in use, the print form can **also fulfil
the good units as an internal order in one step** — recording the production and the
fulfilment as **separate** records, with filament deducted once. Remaining filament
= 1,000 g + later adjustments − recorded consumption. Nothing is auto-imported; the
workflow is built for you to enter real records (unknowns flagged in notes). An
unopened refill loaded onto a reusable spool is just material you already own — it
is not recorded as a second purchase.

## Validation (synthetic only; production kept clean)

`operations/tests/` now has 34 tests (all pass on PostgreSQL). The Phase 1b set
walks the full sequence: start a spool at 1,000 g → print a batch (product material
+ shared batch waste) → confirm remaining grams → add successful finished units →
create + fulfil a no-payment internal order → confirm fulfilment changes finished
inventory with **no** filament deduction → reverse/correct without corrupting either
inventory → duplicate submissions don't duplicate movements. Plus: recipe-version
history preserves past prints, all-inclusive totals aren't double-counted, failed
prints consume actual (not planned) and produce nothing, and the print/order views
post correctly through their formsets.

## Still deferred (unchanged boundaries)

No public storefront, customer checkout, payment integration, printer connection,
QR, or full costing engine. Finance behaviour, private storage, and aegis isolation
are untouched. No reservations.

---

# Access & navigation update (2026-11-01)

Operations is **administrator-only**. The gate (`operations/views.py` `admin_required`,
on every view) now requires authenticated **AND `is_active` AND `is_superuser`** —
`is_staff` alone is not enough. Anonymous users are redirected to login; regular
users and non-admin staff get a 404 (pages, private attachments, and mutation
endpoints alike). An admin-only "Operations" link (named URLs, existing styles,
mobile-friendly) appears on the main website, the software-downloads portal, Finance,
and the admin console; Operations itself has a "Beacon Home" link back. Earlier
references in this doc to "staff-only"/`is_staff` are superseded by this rule.
