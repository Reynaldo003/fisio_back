import re
import unicodedata
from datetime import datetime, timedelta

from django.contrib.auth.models import User

from .models import BloqueoHorario, Cita, Clinica, Paciente


PUBLIC_DEFAULT_PRO_NAME = "l.f.t edgar mauricio medina cruz"
INTERFACES_SISTEMA = ["agenda", "pacientes", "ventas", "servicios", "comentarios", "equipo", "insumos", "perfil"]
ROLES_DINERO = {"admin", "fisioterapeuta", "recepcion"}
ROLES_TODAS_AGENDAS = {"admin", "fisioterapeuta", "recepcion"}

PERMISOS_BASE = {
    "admin": {
        "puede_ver_agenda": True,
        "puede_ver_pacientes": True,
        "puede_ver_contacto_paciente": True,
        "puede_ver_montos": True,
        "puede_modificar_montos": True,
        "puede_ver_finanzas": True,
        "puede_ver_servicios": True,
        "puede_ver_comentarios": True,
        "puede_ver_equipo": True,
        "puede_editar_equipo": True,
        "puede_ver_insumos": True,
        "puede_editar_insumos": True,
        "puede_ver_perfil": True,
        "interfaces": INTERFACES_SISTEMA,
    },
    "fisioterapeuta": {
        "puede_ver_agenda": True,
        "puede_ver_pacientes": True,
        "puede_ver_contacto_paciente": True,
        "puede_ver_montos": True,
        "puede_modificar_montos": True,
        "puede_ver_finanzas": True,
        "puede_ver_servicios": False,
        "puede_ver_comentarios": False,
        "puede_ver_equipo": False,
        "puede_editar_equipo": False,
        "puede_ver_insumos": False,
        "puede_editar_insumos": False,
        "puede_ver_perfil": True,
        "interfaces": ["agenda", "pacientes", "ventas", "perfil"],
    },
    "terapeuta": {
        "puede_ver_agenda": True,
        "puede_ver_pacientes": True,
        "puede_ver_contacto_paciente": True,
        "puede_ver_montos": False,
        "puede_modificar_montos": False,
        "puede_ver_finanzas": False,
        "puede_ver_servicios": False,
        "puede_ver_comentarios": False,
        "puede_ver_equipo": False,
        "puede_editar_equipo": False,
        "puede_ver_insumos": False,
        "puede_editar_insumos": False,
        "puede_ver_perfil": True,
        "interfaces": ["agenda", "pacientes", "perfil"],
    },
    "recepcion": {
        "puede_ver_agenda": True,
        "puede_ver_pacientes": False,
        "puede_ver_contacto_paciente": True,
        "puede_ver_montos": True,
        "puede_modificar_montos": True,
        "puede_ver_finanzas": True,
        "puede_ver_servicios": False,
        "puede_ver_comentarios": False,
        "puede_ver_equipo": False,
        "puede_editar_equipo": False,
        "puede_ver_insumos": False,
        "puede_editar_insumos": False,
        "puede_ver_perfil": True,
        "interfaces": ["agenda", "ventas", "perfil"],
    },
    "practicante": {
        "puede_ver_agenda": True,
        "puede_ver_pacientes": True,
        "puede_ver_contacto_paciente": False,
        "puede_ver_montos": False,
        "puede_modificar_montos": False,
        "puede_ver_finanzas": False,
        "puede_ver_servicios": False,
        "puede_ver_comentarios": False,
        "puede_ver_equipo": False,
        "puede_editar_equipo": False,
        "puede_ver_insumos": False,
        "puede_editar_insumos": False,
        "puede_ver_perfil": True,
        "interfaces": ["agenda", "pacientes", "perfil"],
    },
    "nutriologo": {
        "puede_ver_agenda": True,
        "puede_ver_pacientes": True,
        "puede_ver_contacto_paciente": True,
        "puede_ver_montos": False,
        "puede_modificar_montos": False,
        "puede_ver_finanzas": False,
        "puede_ver_servicios": False,
        "puede_ver_comentarios": False,
        "puede_ver_equipo": False,
        "puede_editar_equipo": False,
        "puede_ver_insumos": False,
        "puede_editar_insumos": False,
        "puede_ver_perfil": True,
        "interfaces": ["agenda", "pacientes", "perfil"],
    },
    "dentista": {
        "puede_ver_agenda": True,
        "puede_ver_pacientes": True,
        "puede_ver_contacto_paciente": True,
        "puede_ver_montos": False,
        "puede_modificar_montos": False,
        "puede_ver_finanzas": False,
        "puede_ver_servicios": False,
        "puede_ver_comentarios": False,
        "puede_ver_equipo": False,
        "puede_editar_equipo": False,
        "puede_ver_insumos": False,
        "puede_editar_insumos": False,
        "puede_ver_perfil": True,
        "interfaces": ["agenda", "pacientes", "perfil"],
    },
    "colaborador": {
        "puede_ver_agenda": True,
        "puede_ver_pacientes": False,
        "puede_ver_contacto_paciente": False,
        "puede_ver_montos": False,
        "puede_modificar_montos": False,
        "puede_ver_finanzas": False,
        "puede_ver_servicios": False,
        "puede_ver_comentarios": False,
        "puede_ver_equipo": False,
        "puede_editar_equipo": False,
        "puede_ver_insumos": False,
        "puede_editar_insumos": False,
        "puede_ver_perfil": True,
        "interfaces": ["agenda", "perfil"],
    },
}


def normalizar_nombre(valor):
    valor = (valor or "").strip().lower()
    valor = unicodedata.normalize("NFD", valor)
    return " ".join("".join(ch for ch in valor if unicodedata.category(ch) != "Mn").split())


def normalizar_telefono(valor):
    return "".join(ch for ch in str(valor or "") if ch.isdigit())


def nombre_completo_paciente(paciente):
    return " ".join(p.strip() for p in [paciente.nombres, paciente.apellido_pat, paciente.apellido_mat] if (p or "").strip()).strip()


def buscar_paciente_publico_similar(*, clinica, nombre, telefono):
    nombre_norm = normalizar_nombre(nombre)
    telefono_norm = normalizar_telefono(telefono)
    if not nombre_norm or not telefono_norm:
        return None
    candidatos = Paciente.objects.filter(clinica=clinica).only("id", "nombres", "apellido_pat", "apellido_mat", "telefono")
    for paciente in candidatos:
        if normalizar_telefono(paciente.telefono) != telefono_norm:
            continue
        nombre_completo = normalizar_nombre(nombre_completo_paciente(paciente))
        solo_nombres = normalizar_nombre(paciente.nombres)
        if nombre_completo == nombre_norm or solo_nombres == nombre_norm:
            return paciente
    return None


def rol_usuario(user):
    if not user or not user.is_authenticated:
        return None
    perfil_staff = getattr(user, "staff_profile", None)
    if perfil_staff and perfil_staff.rol:
        if perfil_staff.rol == "personalizado" and perfil_staff.rol_personalizado_id:
            return perfil_staff.rol_personalizado.slug
        return perfil_staff.rol
    if user.is_superuser or user.is_staff:
        return "admin"
    perfil = getattr(user, "perfil", None)
    if perfil and perfil.rol:
        return perfil.rol
    return "colaborador"

def permisos_usuario(user):
    if not user or not user.is_authenticated:
        return {**PERMISOS_BASE["colaborador"], "interfaces": []}

    staff = getattr(user, "staff_profile", None)

    if user.is_superuser:
        rol_actual = "admin"
        permisos = dict(PERMISOS_BASE["admin"])
        permisos["interfaces"] = list(permisos.get("interfaces") or [])

    elif staff and staff.rol == "personalizado" and staff.rol_personalizado_id and staff.rol_personalizado.activo:
        rol = staff.rol_personalizado
        rol_actual = rol.slug
        permisos = {
            "puede_ver_agenda": rol.puede_ver_agenda,
            "puede_ver_pacientes": rol.puede_ver_pacientes,
            "puede_ver_contacto_paciente": rol.puede_ver_contacto_paciente,
            "puede_ver_montos": rol.puede_ver_montos,
            "puede_modificar_montos": rol.puede_modificar_montos,
            "puede_ver_finanzas": rol.puede_ver_finanzas,
            "puede_ver_servicios": rol.puede_ver_servicios,
            "puede_ver_comentarios": rol.puede_ver_comentarios,
            "puede_ver_equipo": rol.puede_ver_equipo,
            "puede_editar_equipo": rol.puede_editar_equipo,
            "puede_ver_insumos": rol.puede_ver_insumos,
            "puede_editar_insumos": rol.puede_editar_insumos,
            "puede_ver_perfil": rol.puede_ver_perfil,
            "interfaces": list(rol.interfaces or []),
        }

    else:
        rol_actual = staff.rol if staff and staff.rol else rol_usuario(user)
        permisos = dict(PERMISOS_BASE.get(rol_actual, PERMISOS_BASE["colaborador"]))
        permisos["interfaces"] = list(permisos.get("interfaces") or [])

    if staff and staff.usar_interfaces_override:
        permisos["interfaces"] = [
            item for item in (staff.interfaces_override or [])
            if item in INTERFACES_SISTEMA
        ]

    # Seguridad dura de dinero.
    # Ningún rol personalizado puede brincarse esta regla.
    puede_dinero = rol_actual in ROLES_DINERO

    permisos["puede_ver_montos"] = puede_dinero
    permisos["puede_modificar_montos"] = puede_dinero
    permisos["puede_ver_finanzas"] = puede_dinero
    permisos["puede_ver_todas_agendas"] = rol_actual in ROLES_TODAS_AGENDAS

    if not puede_dinero:
        permisos["interfaces"] = [
            interfaz for interfaz in permisos["interfaces"]
            if interfaz != "ventas"
        ]

    return permisos

def interfaces_usuario(user):
    return permisos_usuario(user).get("interfaces", [])


def es_admin(rol_o_user):
    if hasattr(rol_o_user, "is_authenticated"):
        return permisos_usuario(rol_o_user).get("puede_editar_equipo", False) and rol_usuario(rol_o_user) == "admin"
    return rol_o_user == "admin"

def es_profesional(rol_o_user):
    if hasattr(rol_o_user, "is_authenticated"):
        rol_o_user = rol_usuario(rol_o_user)
    return rol_o_user in ("fisioterapeuta", "terapeuta", "practicante", "nutriologo", "dentista")

def puede_ver_todas_agendas(rol_o_user):
    if hasattr(rol_o_user, "is_authenticated"):
        rol_o_user = rol_usuario(rol_o_user)
    return rol_o_user in ROLES_TODAS_AGENDAS


def puede_ver_dinero(rol_o_user):
    if hasattr(rol_o_user, "is_authenticated"):
        rol_o_user = rol_usuario(rol_o_user)
    return rol_o_user in ROLES_DINERO


def puede_modificar_dinero(rol_o_user):
    if hasattr(rol_o_user, "is_authenticated"):
        rol_o_user = rol_usuario(rol_o_user)
    return rol_o_user in ROLES_DINERO


def puede_ver_finanzas(rol_o_user):
    if hasattr(rol_o_user, "is_authenticated"):
        rol_o_user = rol_usuario(rol_o_user)
    return rol_o_user in ROLES_DINERO


def puede_ver_contacto_paciente(user):
    return bool(permisos_usuario(user).get("puede_ver_contacto_paciente"))

def puede_gestionar_equipo(user):
    return bool(permisos_usuario(user).get("puede_editar_equipo"))


def puede_ver_insumos(user):
    return bool(permisos_usuario(user).get("puede_ver_insumos"))


def puede_editar_insumos(user):
    return bool(permisos_usuario(user).get("puede_editar_insumos"))


def primera_clinica():
    return Clinica.objects.first()


def clinica_usuario(user):
    perfil = getattr(user, "perfil", None)
    if perfil and getattr(perfil, "clinica_id", None):
        return perfil.clinica
    staff = getattr(user, "staff_profile", None)
    if staff:
        return primera_clinica()
    return primera_clinica()


def calcular_hora_termina(fecha_str, hora_inicio_str, duracion):
    dt = datetime.fromisoformat(f"{fecha_str}T{hora_inicio_str}")
    return (dt + (duracion or timedelta(minutes=60))).time()


def se_superponen(inicio_a, fin_a, inicio_b, fin_b):
    return inicio_a < fin_b and inicio_b < fin_a


def validar_conflicto_cita(*, profesional_id, fecha, hora_inicio, hora_termina, exclude_id=None):
    qs = Cita.objects.filter(profesional_id=profesional_id, fecha=fecha).exclude(estado="cancelado")
    if exclude_id:
        qs = qs.exclude(id=exclude_id)
    return any(se_superponen(hora_inicio, hora_termina, cita.hora_inicio, cita.hora_termina) for cita in qs.only("hora_inicio", "hora_termina"))


def profesional_publico_default(clinica):
    target = normalizar_nombre(PUBLIC_DEFAULT_PRO_NAME)
    for user in User.objects.filter(is_active=True, staff_profile__isnull=False).order_by("id"):
        full_name = normalizar_nombre(f"{user.first_name} {user.last_name}")
        username = normalizar_nombre(user.username)
        if full_name == target or username == target:
            return user
    return getattr(clinica, "propietario", None)


def password_fuerte(password):
    return bool(password and len(password) >= 8 and re.search(r"[A-Z]", password) and re.search(r"[a-z]", password) and re.search(r"[0-9]", password) and re.search(r"[^A-Za-z0-9]", password))
