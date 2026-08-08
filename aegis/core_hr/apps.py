from django.apps import AppConfig


class CoreHrConfig(AppConfig):
    name = 'aegis.core_hr'
    # Explicit, stable app label — the router keys platform-DB isolation off it.
    label = 'aegis_core_hr'
    verbose_name = 'Enterprise Platform — Core HR'
    default_auto_field = 'django.db.models.BigAutoField'
