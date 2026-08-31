from django.contrib.auth.models import User
from rest_framework import mixins, permissions, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from core.permissions import IsAdminUserStrict
from core.serializers.equipo import StaffUserSerializer, UserSerializer
from core.utilidades import password_fuerte, rol_usuario


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def public_team(request):
    qs = User.objects.filter(is_active=True, staff_profile__isnull=False).order_by("-id"); return Response(StaffUserSerializer(qs, many=True, context={"request": request}).data)


class StaffUserViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    serializer_class = StaffUserSerializer; permission_classes = [IsAdminUserStrict]; parser_classes = [MultiPartParser, FormParser, JSONParser]
    def get_queryset(self): return User.objects.filter(staff_profile__isnull=False).order_by("-id")


class ProfesionalViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = User.objects.filter(is_active=True, staff_profile__isnull=False).order_by("first_name", "last_name", "username"); serializer_class = UserSerializer; permission_classes = [permissions.IsAuthenticated]


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request):
    user = request.user; full_name = (user.get_full_name() or "").strip() or user.username
    return Response({"id": user.id, "email": user.email, "username": user.username, "full_name": full_name, "rol": rol_usuario(user)})


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def me_update(request):
    user = request.user; username = (request.data.get("username") or "").strip(); first_name = (request.data.get("first_name") or "").strip(); last_name = (request.data.get("last_name") or "").strip(); email = (request.data.get("email") or "").strip()
    if not username: return Response({"detail": "username requerido."}, status=400)
    if not email: return Response({"detail": "email requerido."}, status=400)
    new_password = request.data.get("new_password") or ""; current_password = request.data.get("current_password") or ""
    if new_password:
        if not current_password: return Response({"detail": "Escribe tu contraseña actual para cambiarla."}, status=400)
        if not user.check_password(current_password): return Response({"detail": "La contraseña actual es incorrecta."}, status=400)
        if not password_fuerte(new_password): return Response({"detail": "La nueva contraseña no cumple requisitos (8+, mayúscula, minúscula, número, símbolo)."}, status=400)
        user.set_password(new_password)
    user.username = username; user.first_name = first_name; user.last_name = last_name; user.email = email; user.save()
    foto = request.FILES.get("foto", None); profile = getattr(user, "staff_profile", None)
    if profile and foto: profile.foto = foto; profile.save(update_fields=["foto"])
    full_name = (user.get_full_name() or "").strip() or user.username
    return Response({"id": user.id, "email": user.email, "username": user.username, "first_name": user.first_name, "last_name": user.last_name, "full_name": full_name, "rol": rol_usuario(user), "foto_url": request.build_absolute_uri(profile.foto.url) if profile and profile.foto else None})
