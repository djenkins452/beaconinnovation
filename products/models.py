"""
Models for the secure product download portal.

Phase 1 scope: distribute the *latest* build of each Beacon product to
authorized users. Intentionally minimal — a single downloadable file per
product, replaced in place when a new build is uploaded.

The design leaves room for future expansion (release notes, version history,
beta channels, licensing) without requiring a redesign: those would become
related models pointing at Product, or extra fields, rather than changes to
the core access/download flow implemented here.
"""
import os

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils.text import slugify


class Product(models.Model):
    """A Beacon product that authorized users can download.

    Each product carries exactly ONE current downloadable build. Uploading a
    new build replaces the previous one (see ``save``); older builds are not
    retained in Phase 1.
    """

    name = models.CharField(max_length=120)
    slug = models.SlugField(
        max_length=140,
        unique=True,
        blank=True,
        help_text="Used in the product URL. Auto-generated from the name if left blank.",
    )
    description = models.TextField(blank=True)

    # Free-form so it fits any versioning scheme (semver, build numbers, dates).
    current_version = models.CharField(
        max_length=60,
        blank=True,
        help_text="e.g. '1.0.4'. Shown to users on the product page.",
    )

    # Build identifier shown alongside the version. Useful during testing.
    # Not release management — just the current build number/string.
    current_build = models.CharField(
        max_length=60,
        blank=True,
        help_text="e.g. '28'. Shown alongside the version on the product page.",
    )

    # iOS bundle identifier (CFBundleIdentifier), required to build the OTA
    # install manifest. Auto-populated from the IPA's Info.plist on publish.
    bundle_id = models.CharField(
        max_length=200,
        blank=True,
        help_text="iOS bundle identifier (e.g. com.beaconinnovation.aims.field). "
                  "Required for over-the-air install; set automatically from the IPA.",
    )

    icon = models.ImageField(
        upload_to='product_icons/',
        blank=True,
        null=True,
        help_text="Optional. Small square image shown next to the product.",
    )

    # No file-type restriction: products may ship IPA / APK / EXE / DMG / ZIP /
    # or anything else. The file is served through an authenticated view, never
    # a public URL.
    download_file = models.FileField(
        upload_to='product_downloads/',
        blank=True,
        null=True,
        help_text="The latest build. Uploading a new file replaces the previous one.",
    )

    download_enabled = models.BooleanField(
        default=True,
        help_text="Uncheck to temporarily disable downloads without deleting the file.",
    )

    # Authorization: users only ever see / download products granted to them.
    authorized_users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='products',
        blank=True,
        help_text="Users allowed to see and download this product.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)

        # Replace-in-place: if the download file changed on an existing product,
        # delete the previous file from storage so old builds don't linger.
        old_file = None
        if self.pk:
            try:
                old_file = Product.objects.get(pk=self.pk).download_file
            except Product.DoesNotExist:
                old_file = None

        super().save(*args, **kwargs)

        if old_file and old_file.name and old_file.name != (self.download_file.name or ''):
            old_file.delete(save=False)

    def get_absolute_url(self):
        return reverse('products:detail', kwargs={'slug': self.slug})

    @property
    def filename(self):
        """Base filename of the current build, or '' if none."""
        if self.download_file and self.download_file.name:
            return os.path.basename(self.download_file.name)
        return ''

    @property
    def file_extension(self):
        """Lowercased extension without the dot (e.g. 'ipa'), or '' if none."""
        name = self.filename
        if not name or '.' not in name:
            return ''
        return name.rsplit('.', 1)[1].lower()

    @property
    def has_download(self):
        return bool(self.download_file and self.download_file.name)

    @property
    def is_ios_app(self):
        """True for iOS apps (IPA) — eligible for over-the-air install."""
        return self.file_extension == 'ipa'

    @property
    def ota_capable(self):
        """True when this product can be installed over-the-air right now."""
        return self.is_ios_app and self.is_available and bool(self.bundle_id)

    @property
    def is_available(self):
        """True when a build exists and downloads are enabled."""
        return self.download_enabled and self.has_download

    def user_can_access(self, user):
        """Whether ``user`` is authorized to see/download this product."""
        if not user or not user.is_authenticated:
            return False
        return self.authorized_users.filter(pk=user.pk).exists()
