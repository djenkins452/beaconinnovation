from django.apps import AppConfig


class AegisCoreConfig(AppConfig):
    # Import path of the app package.
    name = 'aegis.core'
    # Explicit, stable app label. The router keys migration/read/write isolation
    # off this label, so it must not collide with any Beacon app label and must
    # not change (it would orphan migrations and break routing).
    label = 'aegis_core'
    verbose_name = 'Enterprise Platform — Core'
    # Platform models declare explicit UUID primary keys; this only affects any
    # incidental auto-created tables (e.g. M2M through tables).
    default_auto_field = 'django.db.models.BigAutoField'

    def ready(self):
        # Register the incubation authentication provider. Kept here so the
        # provider registry is populated exactly once at app startup.
        from aegis.core.auth import register_default_providers
        register_default_providers()
