"""Durable, private storage for sensitive finance uploads (receipts, CSV imports).

Why this exists
---------------
Beacon's web service runs on Railway's ephemeral container filesystem (no volume),
so anything written under ``MEDIA_ROOT`` is lost on every redeploy. Finance
receipts and CSV imports are sensitive financial records that must survive
redeploys AND must never be served from a public URL.

This backend stores the file bytes as rows in the existing, durable, volume-backed
PostgreSQL database (``StoredBlob``). That reuses an already-provisioned, approved
resource at no additional cost, keeps the files fully private (there is no public
URL at all — they are reachable only through the access-checked Django views in
``finance.views``), and leaves WLJ and Cloudinary completely untouched.

It is intentionally scoped (via ``storage=database_storage`` on the specific
FileFields) to finance uploads only; it is not the project-wide default storage.

If upload volume ever grows enough to matter for DB size, migrating these blobs to
a Railway Volume or object storage is a drop-in change — but that is a billable
resource and must be approved first.
"""
from django.core.files.base import ContentFile
from django.core.files.storage import Storage
from django.utils.deconstruct import deconstructible


@deconstructible
class DatabaseStorage(Storage):
    """A Django Storage backend that persists file contents in PostgreSQL.

    Files are keyed by their storage ``name`` (the ``upload_to`` path, e.g.
    ``receipts/2026/10/foo.pdf``). No public URL is exposed.
    """

    def _blob_model(self):
        # Imported lazily so the module is importable before the app registry is
        # ready (FileField ``storage=`` is evaluated at import time).
        from finance.models import StoredBlob
        return StoredBlob

    def _open(self, name, mode="rb"):
        blob = self._blob_model().objects.get(name=name)
        return ContentFile(bytes(blob.data), name=name)

    def _save(self, name, content):
        content.seek(0)
        data = content.read()
        if isinstance(data, str):
            data = data.encode("utf-8")
        content_type = getattr(content, "content_type", "") or ""
        self._blob_model().objects.update_or_create(
            name=name,
            defaults={"data": data, "size": len(data), "content_type": content_type},
        )
        return name

    def exists(self, name):
        return self._blob_model().objects.filter(name=name).exists()

    def delete(self, name):
        self._blob_model().objects.filter(name=name).delete()

    def size(self, name):
        return self._blob_model().objects.get(name=name).size

    def url(self, name):
        # These records are private and have NO public URL. They are served only
        # through the access-checked views (finance:view_receipt / download_receipt).
        # Returning an empty string avoids accidentally emitting a usable link;
        # application code links to the access-checked views, never to .url.
        return ""

    # Timestamps are tracked on the row; Django's Storage API expects these for
    # some introspection paths.
    def get_created_time(self, name):
        return self._blob_model().objects.get(name=name).created_at

    def get_modified_time(self, name):
        return self._blob_model().objects.get(name=name).created_at


def database_storage():
    """Callable used as ``storage=`` on finance FileFields.

    Using a callable keeps migrations referencing this function by import path
    rather than embedding a concrete instance.
    """
    return DatabaseStorage()
