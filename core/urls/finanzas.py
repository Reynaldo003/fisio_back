from rest_framework.routers import DefaultRouter
from core.views.finanzas import PagoViewSet

router = DefaultRouter(); router.register("pagos", PagoViewSet, basename="pagos")
urlpatterns = router.urls
