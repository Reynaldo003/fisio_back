from rest_framework.permissions import BasePermission, SAFE_METHODS

from core.utilidades import (
    permisos_usuario,
    puede_editar_insumos,
    puede_gestionar_equipo,
    puede_modificar_dinero,
    puede_ver_dinero,
    puede_ver_finanzas,
    puede_ver_insumos,
)


class IsAdminUserStrict(BasePermission):
    message = "Solo un administrador puede realizar esta operación."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and puede_gestionar_equipo(request.user))


class PuedeVerDinero(BasePermission):
    message = "Tu rol no tiene permiso para consultar información monetaria."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and puede_ver_dinero(request.user))


class PuedeModificarDinero(BasePermission):
    message = "Tu rol no tiene permiso para modificar cantidades monetarias."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and puede_modificar_dinero(request.user))


class PuedeVerFinanzas(BasePermission):
    message = "Tu rol no tiene acceso al módulo de finanzas."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and puede_ver_finanzas(request.user))


class PuedeVerInsumos(BasePermission):
    message = "Tu rol no tiene acceso al módulo de insumos."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and puede_ver_insumos(request.user))


class PuedeEditarInsumos(BasePermission):
    message = "Tu rol no tiene permiso para modificar insumos."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return puede_ver_insumos(request.user)
        return puede_editar_insumos(request.user)


class PuedeUsarInterfaz(BasePermission):
    interfaz = None
    message = "Tu rol no tiene acceso a esta interfaz."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        interfaz = getattr(view, "interfaz_requerida", None) or self.interfaz
        if not interfaz:
            return True
        return interfaz in permisos_usuario(request.user).get("interfaces", [])
