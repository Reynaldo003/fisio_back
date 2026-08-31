from rest_framework.routers import DefaultRouter
from core.views.servicios import ServicioAdminViewSet, ServicioViewSet

router = DefaultRouter(); router.register("servicios", ServicioViewSet, basename="servicios"); router.register("servicios-admin", ServicioAdminViewSet, basename="servicios-admin")
urlpatterns = router.urls
