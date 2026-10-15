from django.apps import AppConfig


class ControlOperativoConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'control_operativo'
    verbose_name = 'Control operativo'

    def ready(self):
        import control_operativo.signals  # noqa: F401
