# core/urls.py
from django.urls import include, path
from rest_framework.routers import DefaultRouter
from estadisticas.views import estadisticas
from .views import (
    PacienteViewSet, ComentarioViewSet, CitaViewSet, ServicioViewSet,
    ProfesionalViewSet, PagoViewSet,
    public_agenda, public_create_cita, public_team,
    StaffUserViewSet, me, BloqueoHorarioViewSet,
    ServicioAdminViewSet, me_update,
)

router = DefaultRouter()
router.register("pacientes", PacienteViewSet, basename="pacientes")
router.register("comentarios", ComentarioViewSet, basename="comentarios")
router.register("citas", CitaViewSet, basename="citas")

# público (solo activos)
router.register("servicios", ServicioViewSet, basename="servicios")

# ✅ admin CRUD
router.register("servicios-admin", ServicioAdminViewSet, basename="servicios-admin")

router.register("profesionales", ProfesionalViewSet, basename="profesionales")
router.register("pagos", PagoViewSet, basename="pagos")
router.register("staff", StaffUserViewSet, basename="staff")
router.register(r"bloqueos", BloqueoHorarioViewSet, basename="bloqueos")

urlpatterns = [
    path("", include(router.urls)),
    path("me/", me, name="me"),
    path("me/update/", me_update, name="me-update"),  # ✅ nuevo
    path("dashboard-stats/", estadisticas, name="dashboard-stats"),
    path("public/agenda/", public_agenda, name="public-agenda"),
    path("public/citas/", public_create_cita, name="public-create-cita"),
    path("public/team/", public_team, name="public-team"),
]
