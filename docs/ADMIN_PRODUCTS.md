# Beacon Admin → Products

Beacon-owned framework for the internal, authenticated **Admin → Products** area: a reusable shell
listing Beacon products and their internal engineering resources. **AIMS** is the first product; the
design deliberately supports registering **Whole Life Journey**, **Beacon HCM**, and future products
without copying views/routes/templates.

This document is the Beacon side of the cross-repository contract. AIMS owns *generating* the
Developer Guide and the deployment-package format (AIMS `DECISIONS.md` **D-176**, **D-178**, **D-179**);
Beacon owns *hosting, authentication, routing, and deployment consumption*.

## Where it lives

- App: `admin_console` (the existing internal admin, mounted at `/admin-console/`, Django-session auth).
- Registry: `admin_console/product_registry.py` — a **code-level registry**, not a DB model. Beacon owns
  a handful of products, and each product's dynamic state (lifecycle, version, provenance) is owned by
  that product's own repo and travels with its deployed artifact — a DB table would duplicate that truth.
- Views: `admin_console/product_views.py`. Templates: `admin_console/templates/admin_console/products_index.html`,
  `product_detail.html`. Nav entry: `admin_console/base.html`.

## URLs

| Path | Purpose |
|---|---|
| `/admin-console/products/` | Products landing (all registered products) |
| `/admin-console/products/<key>/` | A product's internal page (overview + backed capabilities) |
| `/admin-console/products/<key>/developer-guide/` | The product's authenticated Developer Guide (home) |
| `/admin-console/products/<key>/developer-guide/<path>` | Any nested Guide file, streamed authenticated |

**Bookmark for the AIMS Developer Guide:** `/admin-console/products/aims/developer-guide/`.

## Authorization (least privilege)

The whole area requires an **authenticated staff user** (`is_staff`) — `admin_console.product_views.staff_required`.
Rationale: the Developer Guide is proprietary engineering content. The customer download portal
(`products.Product.authorized_users`, e.g. Parker) grants **non-staff** access to *downloads* only; those
users are correctly excluded here. Unauthenticated requests redirect to login (`LOGIN_URL`); authenticated
non-staff get **404** (the area's existence is not revealed). This reuses Beacon's existing Django auth —
no second framework, no new role model.

## Developer Guide hosting

Each product's Guide is deployed as an **immutable, SHA-identified snapshot** under the **private**
`DEVGUIDE_ROOT` (`settings.py` → `BASE_DIR/product_guides/<key>/`), which is **not** in `STATICFILES_DIRS`
and is served **only** through the staff-gated view — never by WhiteNoise (`/static/`) or `distribution`
(`/downloads/`), both of which are public. A snapshot is two files:

- `guide.tar.gz` — the generated static site (deployed by the product's own pipeline).
- `snapshot.json` — provenance: `commit`, `branch`, `lifecycle`, `version`, `guide_schema`, `generated_at`.

The view streams each requested file **out of the tarball in memory** (small in-process cache keyed by
the tarball's mtime, so a redeploy is picked up without a restart), with a path-traversal guard, a
`Content-Type` map, and `Cache-Control: private, no-store`. An unauthenticated deep link retrieves
**nothing**. Beacon reads `lifecycle`/`version` from `snapshot.json` — it never hard-codes them, so
"AIMS is Development" is stated once, in AIMS, and flows downstream.

## Deployment & rollback

The AIMS pipeline (`scripts/release/deploy_devguide.py` in the AIMS repo) validates, builds, packages,
and copies the snapshot into `product_guides/aims/`, then commits it here; Railway deploys on the normal
Beacon push. Only the **active** snapshot is tracked (`guide.tar.gz` + `snapshot.json`); per-SHA copies
under `product_guides/*/snapshots/` are git-ignored. **Rollback** = redeploy a prior AIMS commit's Guide
(deterministic from the SHA) or `git revert` the deploy commit.

## Adding another product

1. Add a dict entry to `_PRODUCTS` in `product_registry.py` (`key`, `name`, `full_name`, `owner`,
   `summary`, `capabilities`).
2. Deploy its Guide snapshot into `product_guides/<key>/` (its own pipeline).
3. Done — the Products UI discovers and renders it; no per-product views, routes, or templates.
