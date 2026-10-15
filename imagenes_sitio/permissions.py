from rest_framework.permissions import BasePermission

from core.utilidades import rol_usuario


class PuedeAdministrarImagenes(BasePermission):
    message = "Solo los administradores pueden administrar imágenes del sitio."

    def has_permission(self, request, view):
        usuario = request.user
        return bool(
            usuario
            and usuario.is_authenticated
            and usuario.is_active
            and (usuario.is_superuser or rol_usuario(usuario) == "admin")
        )
