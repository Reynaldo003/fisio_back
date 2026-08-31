#backend/core/utilidades.py
import re
import unicodedata
from datetime import datetime, timedelta
from django.contrib.auth.models import User
from .models import BloqueoHorario, Cita, Clinica, Paciente

PUBLIC_DEFAULT_PRO_NAME = "l.f.t edgar mauricio medina cruz"


def normalizar_nombre(valor):
    valor = (valor or "").strip().lower(); valor = unicodedata.normalize("NFD", valor)
    return " ".join("".join(ch for ch in valor if unicodedata.category(ch) != "Mn").split())


def normalizar_telefono(valor): return "".join(ch for ch in str(valor or "") if ch.isdigit())


def nombre_completo_paciente(paciente): return " ".join(p.strip() for p in [paciente.nombres, paciente.apellido_pat, paciente.apellido_mat] if (p or "").strip()).strip()


def buscar_paciente_publico_similar(*, clinica, nombre, telefono):
    nombre_norm = normalizar_nombre(nombre); telefono_norm = normalizar_telefono(telefono)
    if not nombre_norm or not telefono_norm: return None
    candidatos = Paciente.objects.filter(clinica=clinica).only("id", "nombres", "apellido_pat", "apellido_mat", "telefono")
    for paciente in candidatos:
        if normalizar_telefono(paciente.telefono) != telefono_norm: continue
        if normalizar_nombre(nombre_completo_paciente(paciente)) == nombre_norm or normalizar_nombre(paciente.nombres) == nombre_norm: return paciente
    return None


def rol_usuario(user):
    if not user or not user.is_authenticated: return None
    perfil_staff = getattr(user, "staff_profile", None)
    if perfil_staff and perfil_staff.rol: return perfil_staff.rol
    if user.is_superuser or user.is_staff: return "admin"
    return "colaborador"


def es_admin(rol): return rol == "admin"
def puede_ver_todas_agendas(rol): return rol in ("admin", "recepcion")
def es_profesional(rol): return rol in ("fisioterapeuta", "nutriologo", "dentista")
def primera_clinica(): return Clinica.objects.first()


def calcular_hora_termina(fecha_str, hora_inicio_str, duracion):
    dt = datetime.fromisoformat(f"{fecha_str}T{hora_inicio_str}"); return (dt + (duracion or timedelta(minutes=60))).time()


def se_superponen(inicio_a, fin_a, inicio_b, fin_b): return inicio_a < fin_b and inicio_b < fin_a


def validar_conflicto_cita(*, profesional_id, fecha, hora_inicio, hora_termina, exclude_id=None):
    qs = Cita.objects.filter(profesional_id=profesional_id, fecha=fecha).exclude(estado="cancelado")
    if exclude_id: qs = qs.exclude(id=exclude_id)
    return any(se_superponen(hora_inicio, hora_termina, c.hora_inicio, c.hora_termina) for c in qs.only("hora_inicio", "hora_termina"))


def profesional_publico_default(clinica):
    target = normalizar_nombre(PUBLIC_DEFAULT_PRO_NAME)
    for user in User.objects.filter(is_active=True, staff_profile__isnull=False).order_by("id"):
        if normalizar_nombre(f"{user.first_name} {user.last_name}") == target or normalizar_nombre(user.username) == target: return user
    return getattr(clinica, "propietario", None)


def password_fuerte(password):
    return bool(password and len(password) >= 8 and re.search(r"[A-Z]", password) and re.search(r"[a-z]", password) and re.search(r"[0-9]", password) and re.search(r"[^A-Za-z0-9]", password))
