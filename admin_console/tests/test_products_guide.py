"""Admin → Products + authenticated Developer Guide hosting.

Security is the point: proprietary engineering content must never be retrievable
by an unauthenticated deep link, nor by an authenticated non-staff (customer
portal) user, nor via path traversal. These tests assert HTTP responses, not UI
hiding. A hermetic snapshot is built in a temp DEVGUIDE_ROOT so the suite does
not depend on a deployed Guide.
"""
import io
import json
import tarfile
import tempfile
from pathlib import Path

from django.contrib.auth.models import User
from django.http import Http404
from django.test import Client, RequestFactory, TestCase, override_settings

from admin_console import product_views, product_registry


def _build_snapshot(root: Path):
    d = root / "aims"
    d.mkdir(parents=True, exist_ok=True)
    files = {
        "index.html": b"<!doctype html><title>Home</title><h1>AIMS Developer Guide</h1>",
        "dec__D-167.html": b"<!doctype html><h1>D-167</h1> one authoritative definition",
        "assets/search-index.js": b"window.DEVGUIDE_INDEX = [];",
        "assets/style.css": b":root{--x:0}",
    }
    with tarfile.open(d / "guide.tar.gz", "w:gz") as tf:
        for name, data in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    (d / "snapshot.json").write_text(json.dumps({
        "product": "aims", "name": "AIMS", "commit": "abc1234", "branch": "main",
        "lifecycle": "development", "version": None, "guide_schema": "1.0",
        "generated_at": "2026-01-01 00:00 UTC", "archive": "guide.tar.gz",
    }))


class ProductsGuideTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        _build_snapshot(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()
        super().tearDownClass()

    def setUp(self):
        product_views._GUIDE_CACHE.clear()
        self.staff = User.objects.create_user("danny", password="x", is_staff=True)
        self.customer = User.objects.create_user("parker", password="x", is_staff=False)
        self.INDEX = "/admin-console/products/"
        self.AIMS = "/admin-console/products/aims/"
        self.GUIDE = "/admin-console/products/aims/developer-guide/"
        self.DEEP = "/admin-console/products/aims/developer-guide/dec__D-167.html"
        self.ASSET = "/admin-console/products/aims/developer-guide/assets/search-index.js"

    # ---- UNAUTHENTICATED: nothing is served (redirect to login) --------------
    @override_settings()
    def test_unauthenticated_gets_nothing(self):
        with self.settings(DEVGUIDE_ROOT=self.root):
            c = Client()
            for url in (self.INDEX, self.AIMS, self.GUIDE, self.DEEP, self.ASSET):
                r = c.get(url)
                self.assertEqual(r.status_code, 302, f"{url} should redirect unauthenticated")
                self.assertIn("/login", r.url.lower())
                self.assertNotIn(b"AIMS Developer Guide", r.content)

    # ---- AUTHENTICATED NON-STAFF (customer): 404, no content -----------------
    def test_non_staff_forbidden(self):
        with self.settings(DEVGUIDE_ROOT=self.root):
            c = Client(); c.force_login(self.customer)
            for url in (self.INDEX, self.AIMS, self.GUIDE, self.DEEP, self.ASSET):
                self.assertEqual(c.get(url).status_code, 404, f"{url} must be 404 for non-staff")

    # ---- STAFF: full access --------------------------------------------------
    def test_staff_access(self):
        with self.settings(DEVGUIDE_ROOT=self.root):
            c = Client(); c.force_login(self.staff)
            self.assertContains(c.get(self.INDEX), "Products")
            self.assertContains(c.get(self.AIMS), "Advanced Inventory Management System")
            root = c.get(self.GUIDE)
            self.assertEqual(root.status_code, 200)
            self.assertIn(b"AIMS Developer Guide", root.content)
            deep = c.get(self.DEEP)
            self.assertEqual(deep.status_code, 200)
            self.assertIn(b"D-167", deep.content)
            asset = c.get(self.ASSET)
            self.assertEqual(asset.status_code, 200)
            self.assertIn("javascript", asset["Content-Type"])
            self.assertEqual(asset["Cache-Control"], "private, no-store")

    # ---- PATH TRAVERSAL is impossible ---------------------------------------
    def test_traversal_blocked(self):
        with self.settings(DEVGUIDE_ROOT=self.root):
            rf = RequestFactory()
            for bad in ("../snapshot.json", "assets/../../snapshot.json", "..%2f..%2fsettings.py",
                        "/etc/passwd"):
                req = rf.get("/x"); req.user = self.staff
                with self.assertRaises(Http404, msg=f"traversal {bad!r} must 404"):
                    product_views.developer_guide(req, "aims", bad)

    # ---- missing snapshot → 404 (no deploy) ---------------------------------
    def test_no_snapshot_is_404(self):
        with tempfile.TemporaryDirectory() as empty:
            with self.settings(DEVGUIDE_ROOT=Path(empty)):
                product_views._GUIDE_CACHE.clear()
                c = Client(); c.force_login(self.staff)
                self.assertEqual(c.get(self.GUIDE).status_code, 404)
