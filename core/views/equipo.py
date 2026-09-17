from django.contrib.auth.models import User
from rest_framework import mixins, permissions, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.models import RolPersonalizado
from core.permissions import IsAdminUserStrict
from core.serializers.equipo import RolPersonalizadoSerializer, StaffUserSerializer, UserSerializer
from core.utilidades import interfaces_usuario, password_fuerte, permisos_usuario, rol_usuario
from django.db.models import Q

ROLES_CON_AGENDA = [
    "admin",
    "fisioterapeuta",
    "terapeuta",
    "practicante",
    "nutriologo",
    "dentista",
]

@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def public_team(request):
    qs = User.objects.filter(is_active=True, staff_profile__isnull=False).select_related("staff_profile", "staff_profile__rol_personalizado").order_by("-id")
    return Response(StaffUserSerializer(qs, many=True, context={"request": request}).data)


class StaffUserViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = StaffUserSerializer
    permission_classes = [IsAdminUserStrict]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        return User.objects.filter(staff_profile__isnull=False).select_related("staff_profile", "staff_profile__rol_personalizado").order_by("-id")


class RolPersonalizadoViewSet(viewsets.ModelViewSet):
    queryset = RolPersonalizado.objects.all().order_by("nombre")
    serializer_class = RolPersonalizadoSerializer
    permission_classes = [IsAdminUserStrict]

class ProfesionalViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return (
            User.objects
            .filter(
                is_active=True,
                staff_profile__isnull=False,
            )
            .filter(
                Q(
                    staff_profile__rol__in=ROLES_CON_AGENDA
                )
                |
                Q(
                    staff_profile__rol="personalizado",
                    staff_profile__rol_personalizado__activo=True,
                    staff_profile__rol_personalizado__puede_ver_agenda=True,
                )
            )
            .select_related(
                "staff_profile",
                "staff_profile__rol_personalizado",
            )
            .distinct()
            .order_by(
                "first_name",
                "last_name",
                "username",
            )
        )

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request):
    user = request.user
    profile = getattr(user, "staff_profile", None)
    full_name = (user.get_full_name() or "").strip() or user.username
    permisos = permisos_usuario(user)
    return Response(
        {
            "id": user.id,
            "email": user.email,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "full_name": full_name,
            "rol": rol_usuario(user),
            "rol_base": profile.rol if profile else None,
            "permisos": permisos,
            "interfaces": interfaces_usuario(user),
            "puede_ver_dinero": bool(permisos.get("puede_ver_montos")),
            "puede_modificar_dinero": bool(permisos.get("puede_modificar_montos")),
            "puede_ver_finanzas": bool(permisos.get("puede_ver_finanzas")),
            "puede_ver_contacto_paciente": bool(permisos.get("puede_ver_contacto_paciente")),
            "foto_url": request.build_absolute_uri(profile.foto.url) if profile and profile.foto else None,
        }
    )


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def me_update(request):
    user = request.user
    username = (request.data.get("username") if "username" in request.data else user.username) or ""
    first_name = (request.data.get("first_name") if "first_name" in request.data else user.first_name) or ""
    last_name = (request.data.get("last_name") if "last_name" in request.data else user.last_name) or ""
    email = (request.data.get("email") if "email" in request.data else user.email) or ""
    username = username.strip()
    first_name = first_name.strip()
    last_name = last_name.strip()
    email = email.strip()

    if not username:
        return Response({"detail": "username requerido."}, status=400)
    if not email:
        return Response({"detail": "email requerido."}, status=400)
    if User.objects.exclude(pk=user.pk).filter(username__iexact=username).exists():
        return Response({"detail": "Ese nombre de usuario ya está en uso."}, status=400)
    if User.objects.exclude(pk=user.pk).filter(email__iexact=email).exists():
        return Response({"detail": "Ese correo ya está en uso."}, status=400)

    new_password = request.data.get("new_password") or ""
    current_password = request.data.get("current_password") or ""
    if new_password:
        if not current_password:
            return Response({"detail": "Escribe tu contraseña actual para cambiarla."}, status=400)
        if not user.check_password(current_password):
            return Response({"detail": "La contraseña actual es incorrecta."}, status=400)
        if not password_fuerte(new_password):
            return Response({"detail": "La nueva contraseña no cumple requisitos (8+, mayúscula, minúscula, número, símbolo)."}, status=400)
        user.set_password(new_password)

    user.username = username
    user.first_name = first_name
    user.last_name = last_name
    user.email = email
    user.save()

    foto = request.FILES.get("foto")
    profile = getattr(user, "staff_profile", None)
    if profile and foto:
        profile.foto = foto
        profile.save(update_fields=["foto"])

    permisos = permisos_usuario(user)
    full_name = (user.get_full_name() or "").strip() or user.username
    return Response(
        {
            "id": user.id,
            "email": user.email,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "full_name": full_name,
            "rol": rol_usuario(user),
            "permisos": permisos,
            "interfaces": interfaces_usuario(user),
            "puede_ver_dinero": bool(permisos.get("puede_ver_montos")),
            "puede_modificar_dinero": bool(permisos.get("puede_modificar_montos")),
            "puede_ver_finanzas": bool(permisos.get("puede_ver_finanzas")),
            "puede_ver_contacto_paciente": bool(permisos.get("puede_ver_contacto_paciente")),
            "foto_url": request.build_absolute_uri(profile.foto.url) if profile and profile.foto else None,
        }
    )


@api_view(["PATCH"])
@permission_classes([IsAdminUserStrict])
def configuracion_interfaces_usuario(request, user_id):
    user = User.objects.filter(pk=user_id, staff_profile__isnull=False).select_related("staff_profile").first()
    if not user:
        return Response({"detail": "Usuario no encontrado."}, status=404)
    profile = user.staff_profile
    if "usar_interfaces_override" in request.data:
        profile.usar_interfaces_override = bool(request.data.get("usar_interfaces_override"))
    if "interfaces_override" in request.data or "interfaces" in request.data:
        profile.interfaces_override = list(request.data.get("interfaces_override", request.data.get("interfaces")) or [])
    profile.save(update_fields=["usar_interfaces_override", "interfaces_override"])
    return Response({"user_id": user.id, "interfaces": interfaces_usuario(user), "permisos": permisos_usuario(user)})
