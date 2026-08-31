from django.urls import include, path
from estadisticas.views import estadisticas

urlpatterns = [
    path("", include("core.urls.pacientes")),
    path("", include("core.urls.agenda")),
    path("", include("core.urls.finanzas")),
    path("", include("core.urls.servicios")),
    path("", include("core.urls.comentarios")),
    path("", include("core.urls.equipo")),
    path("", include("core.urls.autenticacion")),
    path("dashboard-stats/", estadisticas, name="dashboard-stats"),
]
