from django.urls import include, path
from rest_framework.routers import DefaultRouter
from core.views.equipo import ProfesionalViewSet, StaffUserViewSet, me, me_update, public_team

router = DefaultRouter(); router.register("profesionales", ProfesionalViewSet, basename="profesionales"); router.register("staff", StaffUserViewSet, basename="staff")
urlpatterns = [path("", include(router.urls)), path("me/", me, name="me"), path("me/update/", me_update, name="me-update"), path("public/team/", public_team, name="public-team")]
