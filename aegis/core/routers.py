"""Database router that isolates the Enterprise Platform from Beacon.

This router is the enforced architectural boundary (decision B1):

* All ``aegis.*`` apps read/write **only** the ``platform`` database.
* All other apps (Django's own + Beacon's) read/write **only** ``default``.
* Platform migrations run **only** against ``platform``; everything else runs
  **only** against ``default`` — so platform migrations can never touch Beacon's
  database and vice versa.
* Cross-database relations are denied outright (belt-and-suspenders against an
  accidental FK to ``auth.User`` or ``contenttypes``).

The platform database is therefore independently disposable: dropping it cannot
affect Beacon's ``default`` database.
"""

# App labels owned by the Enterprise Platform. Future platform apps
# (people, identity, badging, hardware) are added here as they are created.
PLATFORM_APP_LABELS = {
    'aegis_core',
}

PLATFORM_DB = 'platform'
DEFAULT_DB = 'default'


class PlatformRouter:
    def _is_platform(self, app_label):
        return app_label in PLATFORM_APP_LABELS

    def db_for_read(self, model, **hints):
        if self._is_platform(model._meta.app_label):
            return PLATFORM_DB
        return None  # defer → default

    def db_for_write(self, model, **hints):
        if self._is_platform(model._meta.app_label):
            return PLATFORM_DB
        return None  # defer → default

    def allow_relation(self, obj1, obj2, **hints):
        p1 = self._is_platform(obj1._meta.app_label)
        p2 = self._is_platform(obj2._meta.app_label)
        if p1 != p2:
            # One side is platform, the other is not → cross-database relation.
            return False
        return None  # same side → let Django decide

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if self._is_platform(app_label):
            # Platform apps migrate ONLY on the platform database.
            return db == PLATFORM_DB
        # Every non-platform app (Django's own + Beacon's) migrates ONLY on
        # default — never on the platform database.
        return db == DEFAULT_DB
