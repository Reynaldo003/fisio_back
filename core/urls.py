# core/urls.py
from django.urls import include, path
from rest_framework.routers import DefaultRouter
from estadisticas.views import estadisticas
from .views import (
    PacienteViewSet, ComentarioViewSet, CitaViewSet, ServicioViewSet,
    ProfesionalViewSet, PagoViewSet,
    public_agenda, public_create_cita, public_team,
    StaffUserViewSet, me
)

router = DefaultRouter()
router.register("pacientes", PacienteViewSet, basename="pacientes")
router.register("comentarios", ComentarioViewSet, basename="comentarios")
router.register("citas", CitaViewSet, basename="citas")
router.register("servicios", ServicioViewSet, basename="servicios")
router.register("profesionales", ProfesionalViewSet, basename="profesionales")
router.register("pagos", PagoViewSet, basename="pagos")
router.register("staff", StaffUserViewSet, basename="staff")

urlpatterns = [
    path("", include(router.urls)),
    path("me/", me, name="me"),
    path("dashboard-stats/", estadisticas, name="dashboard-stats"),
    path("public/agenda/", public_agenda, name="public-agenda"),
    path("public/citas/", public_create_cita, name="public-create-cita"),
    path("public/team/", public_team, name="public-team"),
]
