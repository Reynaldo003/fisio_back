from django.urls import path

from .views import ImagenesAdminView, ImagenesDetalleAdminView, ImagenesPublicasView

urlpatterns = [
    path("public/imagenes-sitio/", ImagenesPublicasView.as_view(), name="imagenes-sitio-publicas"),
    path("imagenes-sitio/", ImagenesAdminView.as_view(), name="imagenes-sitio-lista"),
    path("imagenes-sitio/<int:pk>/", ImagenesDetalleAdminView.as_view(), name="imagenes-sitio-detalle"),
]
