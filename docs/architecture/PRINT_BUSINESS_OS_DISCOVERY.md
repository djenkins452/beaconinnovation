# Beacon Print Business — Operating-System Discovery & Architecture

**Repository:** `beaconinnovation` (Django 5.1 monolith)
**Prepared:** 2026-10-31
**Prepared for:** Danny Jenkins, Beacon Innovations LLC
**Scope:** Discovery + architecture only. **No code is proposed for implementation yet.** This document grounds every recommendation in the current codebase, separates verified facts from assumptions, and gives a phased plan that keeps the first build small.
**Method:** Direct inspection of `settings.py`, root URLs, `requirements.txt`, `Procfile`, and the `finance`, `products`, `distribution`, `admin_console`, `website`, and `aegis` apps, plus the existing `docs/ProductStrategyDiscoveryReport.md` and architecture docs.

---

## 0. TL;DR

- **Build the internal operations system *inside* Beacon** as one new, staff-only Django app (working name `operations`). It reuses the `finance` ledger for money and lives in Beacon's main database.
- **Do not build your own public storefront or ecommerce platform.** Use an established provider (Shopify / Etsy / Stripe-hosted) that owns customer accounts and payments. Beacon stays the internal **system of record** for recipes, true inventory, production, and true cost; it *ingests* orders from the storefront.
- **One prerequisite blocks everything: a durable database.** Beacon's business data runs on **SQLite**, and no persistent-storage/volume config is committed to the repo. Whether production *actually* loses data on redeploy depends on a Railway Volume that could not be inspected from here — so treat it as a serious **unverified risk**, not a proven fact. Either way, the fix is the same: move Beacon's default database to managed Postgres **first**. *(This is now underway — see §Update and `docs/architecture/PHASE_0_DURABILITY.md`.)*
- **The architectural spine is an append-only inventory movement ledger.** Every gram and every unit changes only through a movement record (purchase, reserve, consume, produce, waste, adjust, return). Current on-hand = the sum of movements. This is what makes inventory auditable and prevents double-counting.
- **The smallest useful first release is purchasing + inventory on a durable DB** — track what you buy, own, and print. Products, orders, costing, and the storefront come in later, well-sequenced phases.
- Beacon already contains the exact precedent for doing this cleanly: the `aegis` Enterprise Platform is a bounded module with its own database, a service layer, and **wired immutable audit** — "the wiring that Beacon's finance `AuditLogMixin` never got" (`aegis/core/audit.py:6`). Copy that discipline.

---

## Update (2026-10-31) — directions approved; Phase 0 underway

The owner approved these directions: Beacon owns internal physical-goods operations as a **separate bounded module** using Beacon's **default database** (bounded from finance + software distribution); auditable inventory movements with explicit financial-linking rules; storefront evaluated later; printer integration, automated pricing, and storefront integration deferred. **Building the operations module is not yet authorized.**

**Phase 0 (durability only)** is in progress on branch `phase-0-durable-db`: PostgreSQL is now mandatory in every environment (SQLite removed), receipt storage is made volume-ready, and a verified SQLite→Postgres backup/migration/restore procedure exists. It is **code-complete and locally validated; the live production cutover has not been performed.** Full detail and the production steps live in **`docs/architecture/PHASE_0_DURABILITY.md`** — refer there for the current durability status rather than this report's original, pre-verification wording.

---

## 1. Recommendation — what belongs in Beacon, what belongs elsewhere, and why

| Concern | Owner | Why |
|---|---|---|
| Purchasing, expenses, receipts, tax books | **Beacon `finance` (existing)** | Already built, cash-basis, tax-aware. Reuse; do not re-implement money. |
| Inventory (filament, hardware, WIP, finished goods), movements | **Beacon `operations` (new)** | Internal, single-operator, must join to finance money data. No external tool models per-spool filament well. |
| Product definitions, variants, production recipes/BOM | **Beacon `operations` (new)** | These encode *your* manufacturing knowledge; they are not a storefront concern. |
| Production jobs, print outcomes, waste, printer capacity | **Beacon `operations` (new)** | Internal shop-floor truth; no storefront models this. |
| True cost & operational profit (COGS-style estimate) | **Beacon `operations` + `finance`** | Separate from tax books by design (see §8, decision D5). |
| Internal order lifecycle, quotes, proofs, fulfillment state | **Beacon `operations` (new)** | You need one internal view across all three sales models and manual orders. |
| **Public catalog display, customer accounts, checkout, card data** | **Established storefront provider (Shopify / Etsy / Stripe)** | PCI scope, auth, fraud, tax calc, and uptime are solved problems. Rebuilding them is the single largest maintenance liability you could take on. |
| **Payment capture / refunds** | **Payment provider (via storefront or Stripe)** | Never hold card data in Beacon. |
| Custom-quote *intake* from the public | **Thin public form → Beacon queue** (or storefront's quote/draft-order feature) | Low-risk, no internal access granted to customers. |

**The one-sentence rule:** *Beacon is the back office; the storefront is the front counter.* Beacon owns what you make, own, and spend. The storefront owns who buys and how they pay. A narrow, auditable integration moves orders from front counter to back office.

**Where Beacon is the wrong boundary (say-so, as requested):**
- **Do not** put public customers, customer logins, or card data inside Beacon. Beacon today is authentication-only with no role system and no per-record ownership (`finance` is `@login_required` on every view, no `is_staff` gate — verified in `finance/views.py`). Exposing any of it to the public internet is unsafe. Customer identity belongs to the storefront.
- **Do not** try to make Beacon a general ledger / accounting product. `finance` is a deliberately cash-basis, single-user tracker (`docs/BeaconInnovationFinance.md`). Keep formal tax accounting there; keep *operational* profit estimates in `operations`; keep anything your accountant signs in their own tool.

---

## 2. Current-state findings (verified vs. assumed)

### 2.1 Platform & deployment (verified)
- **Django 5.1.4**, server-rendered templates + function-based views, no DRF, no Celery (`requirements.txt`). Gunicorn + WhiteNoise on Railway (`Procfile`).
- **Beacon's `default` database is SQLite** (`beaconinnovation/settings.py`), file `db.sqlite3`, git-tracked. No `DATABASE_URL` parsing for `default`; **no volume/persistent-storage config is committed** anywhere. **Risk (unverified against live hosting): if no Railway Volume is mounted at the DB path, data is lost on redeploy.** This is the top finding and the subject of Phase 0. *(Being addressed now — see §Update.)*
- `psycopg[binary]` and `dj-database-url` **are** now in `requirements.txt`, and `settings.py:144-151` parses `PLATFORM_DATABASE_URL` — but **only** for the separate `platform` (aegis) database, routed by `aegis.core.routers.PlatformRouter` (`settings.py:151`). Beacon's own business data does **not** use it.
- No scheduler/cron, no Celery/APScheduler. The only "jobs" are management commands run once at deploy in the `Procfile`. `finance/management/commands/{calculate_tax_alerts,generate_recurring}.py` are built to be cron-driven but **nothing schedules them**.
- **No email/notification delivery anywhere** (no `send_mail`, no `EMAIL_BACKEND`, no SMTP config). In-app alerting exists only as `finance.TaxAlert` (a DB-backed acknowledge/unacknowledge record).
- **No payment integration** (no Stripe/PayPal). Cloudinary is configured in settings (`settings.py:228-236`) but **entirely unwired** — `finance` receipts use a plain local `FileField` (`finance/models.py:355`).
- Config smells to fix in passing: `STATICFILES_STOREAGE` is **misspelled** (`settings.py:195`), so WhiteNoise's compressed-manifest storage is silently inactive.

### 2.2 `finance` app — reusable money engine, no physical-goods concepts (verified)
8 models, UUID PKs, `Decimal(12,2)`, `PROTECT` on referential deletes:
- `Account` (`finance/models.py:79`) with a one-query balance engine `AccountManager.with_balances()` (`:11-76`); `Category` (`:185`); `Transaction` (`:225`) — the ledger core, four types (income/expense/transfer/owner's-draw), **`vendor` is a free-text CharField, not a model** (`:258`); `Receipt` (`:340`) — local `FileField` + **real, working Tesseract OCR** (`finance/ocr.py`, PDFs rejected for OCR); `RecurringTransaction` (`:395`); `TaxAlert` (`:456`); `AuditLog` (`:495`, immutable — `save()`/`delete()` blocked); `CSVImport` (`:541`, Amex importer in `finance/importers.py`).
- **Audit logging is built but dormant:** `AuditLogMixin` (`finance/mixins.py`) exists but **no model inherits it and it is never called** — mutations are not recorded. Confirmed independently by `aegis/core/audit.py:6`.
- **Access control is authentication-only:** every finance view is `@login_required`; there is **no `is_staff`/role/permission gate** and no per-object ownership except a receipt-access check. No services layer (`services.py` does not exist); logic lives in views + `importers.py`.
- **Greenfield (absent entirely):** inventory, stock, SKU, quantity-on-hand, bill-of-materials, unit cost, vendor/supplier entity, purchase order/receiving, equipment/asset, business/personal/**shared** split (only a single `Account.is_personal` boolean).

### 2.3 `products` / `distribution` / AIMS — software distribution, **not** goods (verified)
- `products` has exactly **one** model, `Product` (`products/models.py:21`): a single uploaded *software build* file + `authorized_users` M2M. No price, quantity, variant, SKU, BOM, or order. "Replace in place," no version history.
- `distribution` is model-less; it serves release artifacts from the filesystem for iOS OTA installs.
- **Naming trap:** the flagship software product **AIMS = "Advanced Inventory Management System"** (`admin_console/product_registry.py:27`) is an *iOS app Beacon sells* for military property accountability. It is **not** a reusable inventory engine for your shop. Do not conflate them.
- Reusable *patterns* here: `admin_console.product_registry` + staff-gated snapshot serving (`admin_console/product_views.py`, `@staff_required = login_required + is_staff`) is a clean "internal product shell" pattern; `authorized_users` M2M is a download-gating pattern.

### 2.4 `admin_console` / `website` (verified)
- `admin_console`: `AdminTask` model + the Claude task API (API-key header auth). Dashboard is a status count. **No notifications, no background jobs.**
- `website`: **empty `models.py`**, a static landing page, and a contact form that is an **unwired third-party StartBootstrap stub** (no backend). **No customer, order, lead, quote, or cart anywhere in the repo.**

### 2.5 `aegis` Enterprise Platform — the precedent to copy (verified via docs + settings)
A bounded module incubated inside the monolith: its **own Postgres DB** via a router (no cross-DB FKs — the boundary is enforced by the database), **platform-owned identity** (no FK to `auth.User`), a **service layer that writes an immutable `AuditEvent` on every mutation**, tenant middleware, and fail-closed scoped managers (`docs/architecture/ENTERPRISE_PLATFORM_ARCHITECTURE_PROPOSAL.md`). The `operations` module does **not** need its own DB (it must join finance money data — see §8/D3), but it **should** copy the *service-layer + wired-audit* discipline from day one.

---

## 3. Proposed architecture

```
                         PUBLIC INTERNET
   ┌───────────────────────────────────────────────────────────┐
   │  Storefront provider (Shopify / Etsy)   +  Payments (Stripe)│
   │  • public catalog + variants   • customer accounts/login    │
   │  • checkout, card data (PCI)   • personalization inputs      │
   │  • "request a quote" / draft orders                          │
   └───────────────┬───────────────────────────────▲────────────┘
                   │  orders (webhook/poll)          │ availability
                   │  payment status                 │ + listing data
        ┌──────────▼─────────────────────────────────┴───────────┐
        │              INTEGRATION SEAM (idempotent)               │
        │  • order ingestion w/ external_id dedupe                 │
        │  • retry queue + dead-letter + daily reconciliation      │
        │  • NO customer PII beyond what fulfillment needs         │
        └──────────┬───────────────────────────────────────────────┘
                   │
   ┌───────────────▼───────────────────────────────────────────────┐
   │  BEACON (back office, staff-only)  — Django monolith, Postgres  │
   │                                                                 │
   │  operations (NEW app)              finance (EXISTING)           │
   │  • Materials / FilamentSpool       • Account / Transaction      │
   │  • StockItem / Location            • Receipt + OCR              │
   │  • InventoryMovement (ledger) ◄───►• Purchase bridge (1 expense │
   │  • Product / Variant                 per purchase, no double    │
   │  • ProductionRecipe (versioned)      count)                     │
   │  • ProductionJob / outcomes        • TaxAlert (cash-basis books)│
   │  • Printer / Equipment                                          │
   │  • Order / OrderLine (3 models)    SHARED: auth.User (staff),   │
   │  • Quote / Proof / Shipment        Django admin, audit pattern  │
   │  • Costing (estimate vs actual)                                 │
   └─────────────────────────────────────────────────────────────────┘
```

**Component boundaries & ownership:**
- **`finance` owns money-in/money-out and tax books.** It is the authority for cash-basis P&L and receipts.
- **`operations` owns the physical and production world** and *references* finance for the cash side of a purchase. The link is a `Purchase`/`PurchaseLine` that points at a finance `Transaction` (the one expense) and emits inventory **receipt movements** (the asset side). The expense is counted once; movements never create expenses.
- **The storefront owns the customer and the card.** Beacon stores a *lightweight* customer reference (external id, name, shipping address) sufficient for fulfillment — never credentials, never card data.
- **The integration seam is the only place the two worlds touch**, and it is deliberately narrow and idempotent (see §8/D2 and the data flow below).

**Data flow (order ingestion):** storefront emits an order event → seam checks `external_order_id` (dedupe) → creates/updates a Beacon `Order` + `OrderLine`s, snapshotting recipe + customization + price → reserves stock or queues production → operator works it → fulfillment status flows back to the storefront (ship confirmation) → payment status is read from the provider, never computed in Beacon.

---

## 4. Conceptual data model (core records & relationships, not every field)

> Named at the concept level on purpose; exact fields are a Phase-by-phase decision.

**Purchasing & assets**
- **Supplier** — lightweight upgrade of today's free-text `vendor`. *(optional; can start as a string)*
- **Purchase** → **PurchaseLine** — a buying event; each line links to **one** finance `Transaction` (the expense) and classifies **use: business / personal / shared (+ % business)** — the split `finance` lacks today. A line resolves to either an inventory receipt (materials/finished goods) or an **Equipment** record.
- **Equipment / Asset** — printers, tools; cost basis for machine-hour allocation; links to **Printer**.

**Inventory (the spine)**
- **Location** — shelf/bin/dry-box.
- **Material** — catalog entry (type: filament / hardware / consumable / packaging).
- **FilamentSpool** — *per-spool instance*: manufacturer, material, color, nominal weight, **tare weight**, **estimated remaining g**, **measured remaining g**, cost, location, status (sealed/open/empty/damaged). Per-spool is required for multicolor + remaining-grams accuracy.
- **StockItem / Lot** — quantity-tracked hardware, consumables, packaging, and **finished goods/variants**, with status buckets: **available / reserved / damaged / unusable**.
- **InventoryMovement** — **append-only ledger, the source of truth.** Types: `purchase_receipt`, `opening_balance`, `reservation_hold`, `reservation_release`, `consumption`, `production_output`, `waste`, `cancellation_return`, `customer_return`, `adjustment/reconciliation`. Every movement carries actor, timestamp, reason, and references its cause (purchase line, job, order line). **On-hand = Σ movements; available = on-hand − active reservations.**

**Products & production**
- **Product** → **ProductVariant** (the sellable thing; variants = color/size/text options).
- **ProductionRecipe** — *versioned* BOM bound to a variant: design file version + source, estimated filament by material+color (g), required hardware + packaging, printer/nozzle compatibility + print-profile reference, estimated print/setup/assembly/finishing time, assembly instructions, QC checklist, **design ownership + commercial-use permission**.
- **ProductionJob** → **JobOutcome/Unit** — records *actual* results: successful units, failures, partial batches, waste g, reprints, corrections. **Failed units consume material (movements) but produce no sellable stock.** Captures purge/support/test/prototype/personal waste. Groups by material/color; references a **Printer** for capacity.
- **Printer** — one now (Bambu P2S, multicolor), modeled so adding printers later is data, not code.

**Orders & fulfillment**
- **Customer** — lightweight, keyed by storefront external id (or manual).
- **Order** → **OrderLine** — one order, **mixed line types: catalog / personalized / custom**. Each line **snapshots** the recipe + customization + price + estimated cost at creation, so later product/price changes never alter history.
- **Quote / CustomRequest** (+ revisions, design fee, revision limit) — for custom work (request-a-quote, no auto-pricing).
- **Proof** — personalization approval artifact + customer sign-off.
- **Shipment / Fulfillment** — pack, ship/pickup, tracking.
- **Payment** — status + provider reference only (unpaid / deposit / paid / refunded). No card data.

**Costing**
- **CostingProfile / RateCard** — machine-hour rate, labor rate(s), markup/minimum charge. **Estimated cost** snapshots onto quotes/order lines; **actual cost** is computed from the job's real movements + time. The two are stored separately and never overwrite each other.

**Relationship shape:** `User(staff) → operations`. `Purchase → PurchaseLine → (Transaction | Equipment | InventoryMovement)`. `Order → OrderLine → (ProductVariant snapshot + Recipe snapshot + customization)`; `OrderLine → reservations`; `ProductionJob → OrderLine(s) or to-stock`; `Job completion → InventoryMovements`. `ProductVariant → ProductionRecipe (versions)`.

**State is deliberately split into independent tracks** (keeps ambiguity out):
- **Payment:** unpaid → (deposit) → paid → refunded
- **Production:** queued → in_progress → done / failed
- **Fulfillment:** unfulfilled → packed → shipped/picked_up → delivered
- **Order lifecycle (umbrella):** open → in_production → fulfilled → completed; plus cancelled / returned.
- **Minimum at launch:** order {open, in_production, fulfilled, completed, cancelled}; payment {unpaid, paid} (+ deposit only for custom); production {queued, in_progress, done, failed}; fulfillment {unfulfilled, fulfilled}. Defer partial fulfillment and multi-stage payment until a real order needs them.

---

## 5. End-to-end workflows

### 5.1 Stocked catalog order (finished stock on hand)
1. Order arrives (storefront ingest or manual entry) with a catalog line.
2. **Reserve** the finished unit → `reservation_hold` movement (available −1; on-hand unchanged).
3. Payment reads `paid` from provider.
4. Pack → `consumption`/`production_output`-reversal: finished unit **leaves inventory** (`reservation_release` + on-hand −1) and packaging is consumed.
5. Ship / pickup → fulfillment `shipped`; push confirmation to storefront.
6. Order `completed`.

**Catalog, produce-to-order variant:** no stock → create a **ProductionJob** → reserve filament + hardware (`reservation_hold`) → print → **job completion** emits `consumption` (grams, hardware), `production_output` (+1 finished good → available), and any `waste` → then proceed to pack/ship as above.

### 5.2 Personalized order (text/color/size + proof)
1. Order line captures customization (text, color, size) — **snapshotted** on the line.
2. Payment (or deposit) per policy.
3. Generate **Proof** → customer approves (via storefront message or email link).
4. On approval, create ProductionJob bound to the **snapshotted recipe + customization**.
5. Print → QC checklist → job completion emits consumption/output/waste movements.
6. Pack → ship. Order `completed`.
7. **Unusable personalized return:** returned unit is restocked as **`damaged`/`unusable`** (never `available`), because it can't be resold; refund per policy.

### 5.3 Custom design (request-a-quote → produce)
1. **Request intake** (public form or storefront quote) — no auto-price.
2. **Feasibility review** by operator.
3. **Quote**: design fee + revision limit + production estimate (from RateCard). Sent to customer.
4. Customer approval + **deposit** (provider invoice/Payment Link).
5. Design work; revisions tracked against the limit.
6. **Proof** → approval.
7. ProductionJob → print → QC.
8. Final payment captured.
9. Ship → `completed`. The recipe produced is saved so a repeat order can skip design.

### 5.4 Failed print (cross-cutting)
During any ProductionJob, a unit fails:
- Record a **failure** outcome + a `waste` movement for the grams actually consumed (and any failed hardware).
- **No `production_output`** for that unit — failed prints never create sellable stock.
- Operator chooses **reprint** → a new unit that consumes more material (more movements).
- Net effect: materials ledger goes down by real consumption + waste; finished stock rises only by the count of *successful* units. Failure/waste trends roll up to the dashboard.

### 5.5 Cancellation (cross-cutting)
- **Before production:** release reservations (`reservation_release`); if paid, record refund (status only; actual refund in provider). Order `cancelled`.
- **After a finished unit exists:** if **catalog**, return the unit to `available` (`cancellation_return`); if **personalized/custom**, return to `damaged`/`unusable`. Refund per policy. Order `cancelled`/`returned`.
- The ledger always reconciles because every state change is a movement — no silent quantity edits.

---

## 6. Phased roadmap

Your proposed sequence is right; repository findings add **one prerequisite phase** (durable DB + ledger primitive), because "track what I own" is meaningless on ephemeral SQLite with no movement history.

- **Phase 0 — Durable foundation (NEW, prerequisite).** Provision managed Postgres for Beacon's `default` DB; migrate finance data; add a light **staff/role gate** (operations is staff-only); stand up the `operations` app shell with a **service layer + wired immutable audit** (copy the `aegis` pattern). *Also fix the `STATICFILES_STOREAGE` typo while here.*
- **Phase 1 — Track what I buy, own, and print (First).** Suppliers (light), Purchases/PurchaseLines bridged to `finance` (one expense each, use-split business/personal/shared), Equipment, Materials, **FilamentSpool**, StockItem, Locations, the **InventoryMovement ledger**, opening-inventory entry, manual consumption, and **print-log-lite** (units ok/failed + waste g). *This is the smallest useful release — see §7.*
- **Phase 2 — Products, costs, production, manual orders (Next).** Product/Variant, **versioned ProductionRecipe/BOM** with snapshotting, full ProductionJob (batching, capacity, QC), the **Costing engine** (estimate vs actual, RateCard), and **manually entered Orders** covering all three sales models with internal Quote/Proof and the split state machines. Dashboard + alerts land here.
- **Phase 3 — Launch connected online sales (Then).** Integrate an established storefront; build the **idempotent order-ingestion seam** (dedupe, retry, daily reconciliation), availability push, the customer-data boundary, a custom-quote intake form, and payment-status sync.
- **Phase 4 — Evidence-supported automation (Later).** Only automate what the Phase 1–3 data proves is worth it: slicer/3MF filament-estimate import, QR labels, receipt auto-capture → purchase (reuse finance OCR), batching/capacity optimization, reorder suggestions (net of reservations + incoming POs), and finally email/notification delivery + a real scheduler.

**Challenged / deferred on purpose (more maintenance than value right now):**
- Direct Bambu/Bambu-Studio/printer integration — **unverified and brittle; manual print-log first** (matches your ask).
- Auto-pricing for custom work — **request-a-quote only** (matches your ask).
- Real-time per-gram telemetry — use **estimate vs. measured + periodic reconciliation**; chasing live gram counts is false precision.
- Full accrual/COGS accounting — keep an **operational estimate**, not a second accounting system.
- Multi-printer scheduling optimizer — **model the Printer entity now, build the optimizer never-until-needed.**

---

## 7. Smallest useful first release

**Goal:** *On a database that doesn't disappear, know exactly what filament and hardware I own, what I paid, and what each print consumed — without double-counting money.*

**In scope**
- Managed Postgres for Beacon `default` (Phase 0) + staff-only `operations` app with wired audit.
- Models: Location, Material, **FilamentSpool**, StockItem, **InventoryMovement** (append-only, source of truth), Purchase/PurchaseLine bridging a `finance` Transaction, Equipment.
- Flows: enter **opening inventory** (what you already own), record a **purchase** (creates one finance expense + inventory receipt), log **consumption**, log a **print** (successful units, failures, waste g), weigh-in **reconciliation** adjustment.

**Explicitly deferred:** products/recipes, orders, quotes, proofs, the storefront, the full costing engine, OCR auto-linking, QR, scheduling, email. (All later phases.)

**Acceptance criteria**
1. Migrations run cleanly on Postgres; a redeploy **does not** lose data.
2. **Invariant tested:** for every item, on-hand == Σ(movements); available == on-hand − active reservations.
3. A filament purchase creates **exactly one** finance expense **and** one inventory receipt — **no double count** (test asserts the money side is counted once).
4. **Opening inventory** seeds stock via `opening_balance` movements **without** creating any finance expense.
5. A logged print **decrements estimated grams**, records a **failure + waste** with **no** increase in sellable stock, and a reprint consumes additional material.
6. Every movement is **immutable** and carries actor/time/reason; corrections are new `adjustment` movements, never edits.

**How existing purchases / inventory are entered:** opening stock goes in as dated, costed `opening_balance` movements (no expense). If you want historical spend in the books too, add back-dated `finance` transactions separately — but opening inventory never doubles as a new expense.

---

## 8. Risks & decisions

**Decisions that materially change the architecture (need your call):**

- **D1 — Durable database (BLOCKING).** Recommendation: **provision managed Postgres for Beacon's `default` DB now** and migrate finance. The driver (`psycopg`) and URL parser (`dj_database_url`) are already in `requirements.txt`; only `default` needs wiring + a Railway Postgres service. *Without this, nothing else is safe to build.*
- **D2 — Storefront boundary & provider.** Recommendation: **do not build ecommerce; integrate an established provider.** Decide direction now even if you pick the vendor at Phase 3. Shortlist: **Shopify** (best API/webhooks, line-item personalization, owned brand, ~monthly fee) vs **Etsy** (built-in discovery for handmade/personalized, weaker control, per-listing + transaction fees) vs **Stripe Payment Links/Checkout + thin pages** (lowest cost, you build the catalog UI). For a one-person shop that wants brand control *and* a real integration surface, **Shopify is the primary recommendation; Etsy as an optional reach channel; Stripe for custom-quote invoices.** The architecture treats the provider as pluggable behind the ingestion seam.
- **D3 — Where `operations` lives.** Recommendation: **same Beacon database as finance** (a new app in `default`), *not* its own DB like `aegis` — because operations must join money data and Django has no cross-DB FKs. Keep customer PII minimal so an extraction stays possible later.
- **D4 — Filament granularity.** Recommendation: **per-spool** (needed for multicolor + remaining-grams + tare). Confirm you're willing to register each spool (a QR label later makes this ~5 seconds).
- **D5 — Costing basis.** Recommendation: **operational profit (COGS-style estimate) stays separate from cash-basis tax books**; `finance` remains authoritative for taxes. Confirm you want two distinct numbers (operational margin vs. tax P&L).

**Routine choices I'm recommending without asking:**
- Reuse `finance` for all money; don't duplicate a ledger.
- Adopt the `aegis` **service-layer + immutable audit** for `operations` from day one (this also finally gives Beacon the audit trail finance was designed for but never wired).
- Movements are append-only; corrections are new movements, never edits.
- Start with the **minimum** state sets in §4; add states only when a real order needs them.

**Risks carried from current state:** ephemeral SQLite (D1); dormant audit (addressed by the service layer); auth-only access with no roles (add a staff gate in Phase 0); no scheduler/email (fine — defer to Phase 4); Cloudinary unwired (irrelevant until you want off-box file storage); `STATICFILES_STOREAGE` typo (fix opportunistically).

---

## 9. Next implementation brief (the first development task)

**Task:** *Phase 0 + the Phase 1 inventory/purchasing core* — stand up a durable datastore and the inventory movement ledger.

**Deliverables**
1. **Durable DB:** wire Beacon `default` to managed Postgres via `dj_database_url` (env-driven, SQLite fallback for local dev only); provision the Railway Postgres service; migrate/seed; verify persistence across a redeploy.
2. **`operations` app shell:** staff-gated (`login_required` + `is_staff`), with a `services.py` service layer and a wired immutable audit record on every write (pattern from `aegis/core/audit.py`).
3. **Models:** Location, Material, FilamentSpool, StockItem, Equipment, Purchase, PurchaseLine, **InventoryMovement**.
4. **Finance bridge:** a purchase creates exactly one `finance.Transaction` (expense) and the corresponding inventory receipt movement(s); opening inventory creates movements with no expense.
5. **Operator flows (minimal UI or admin-first):** enter opening inventory, record a purchase, log consumption, log a print (ok/failed/waste), weigh-in reconciliation.

**Boundaries (do NOT build yet):** products/recipes, orders, quotes/proofs, the storefront or any public surface, the costing engine, OCR auto-link, QR, scheduling, email.

**How to validate:** the six acceptance criteria in §7 — foremost the **on-hand == Σ(movements)** invariant, the **no-double-count** of a purchase's money side, and **data surviving a redeploy**. Ship behind the staff gate; no public exposure.

---

*End of discovery report. Nothing in this document has been implemented. Awaiting your review of §8 decisions (especially D1–D3) before any Phase 0 work begins.*
