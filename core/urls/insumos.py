from django.urls import include, path
from rest_framework.routers import DefaultRouter

from core.views.insumos import MovimientoInsumoViewSet, ProductoInsumoViewSet, VentaInsumoViewSet

router = DefaultRouter()
router.register("productos", ProductoInsumoViewSet, basename="productos-insumos")
router.register("movimientos", MovimientoInsumoViewSet, basename="movimientos-insumos")
router.register("ventas", VentaInsumoViewSet, basename="ventas-insumos")

urlpatterns = [path("insumos/", include(router.urls))]
