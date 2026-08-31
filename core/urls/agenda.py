from django.urls import include, path
from rest_framework.routers import DefaultRouter
from core.views.agenda import BloqueoHorarioViewSet, CitaViewSet, public_agenda, public_create_cita

router = DefaultRouter(); router.register("citas", CitaViewSet, basename="citas"); router.register("bloqueos", BloqueoHorarioViewSet, basename="bloqueos")
urlpatterns = [path("", include(router.urls)), path("public/agenda/", public_agenda, name="public-agenda"), path("public/citas/", public_create_cita, name="public-create-cita")]
