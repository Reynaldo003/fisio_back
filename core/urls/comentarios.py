from rest_framework.routers import DefaultRouter
from core.views.comentarios import ComentarioViewSet

router = DefaultRouter(); router.register("comentarios", ComentarioViewSet, basename="comentarios")
urlpatterns = router.urls
