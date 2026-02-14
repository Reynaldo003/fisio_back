# core/views.py
from datetime import datetime, timedelta
from io import BytesIO
import unicodedata

from django.contrib.auth.models import User
from django.db.models import Q
from django.http import HttpResponse

from rest_framework import permissions, viewsets, status, mixins
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

from .models import Paciente, Comentario, Cita, Servicio, Clinica, Pago, StaffProfile
from .serializers import (
    PacienteSerializer,
    ComentarioSerializer,
    ComentarioPublicSerializer,
    CitaSerializer,
    ServicioSerializer,
    UserSerializer,
    CitaCreateSerializer,
    PagoSerializer,
    StaffUserSerializer,
)
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from .permissions import IsAdminUserStrict


# =========================
# Helpers
# =========================
PUBLIC_DEFAULT_PRO_NAME = "edgar mauricio medina cruz"


def _normalize_name(s: str) -> str:
    """
    Normaliza un nombre:
    - lower
    - sin acentos
    - espacios compactados
    """
    s = (s or "").strip().lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")  # quita acentos
    s = " ".join(s.split())
    return s


def _user_role(user):
    if not user or not user.is_authenticated:
        return None

    sp = getattr(user, "staff_profile", None)
    if sp and sp.rol:
        return sp.rol

    if user.is_superuser or user.is_staff:
        return "admin"
    return "colaborador"


def _is_admin_like(role: str) -> bool:
    return role in ("admin",)


def _can_see_all_agendas(role: str) -> bool:
    return role in ("admin", "recepcion")


def _is_professional_role(role: str) -> bool:
    return role in ("fisioterapeuta", "nutriologo", "dentista")


def _first_clinica():
    return Clinica.objects.first()


def _calc_hora_termina(fecha_str, hora_inicio_str, duracion_td):
    dt = datetime.fromisoformat(f"{fecha_str}T{hora_inicio_str}")
    dt_end = dt + (duracion_td or timedelta(minutes=60))
    return dt_end.time()


def _overlaps(startA, endA, startB, endB):
    return startA < endB and startB < endA


def _validar_conflicto_cita(*, profesional_id, fecha, hora_inicio, hora_termina, exclude_id=None):
    qs = Cita.objects.filter(
        profesional_id=profesional_id,
        fecha=fecha,
    ).exclude(estado="cancelado")

    if exclude_id:
        qs = qs.exclude(id=exclude_id)

    for c in qs.only("hora_inicio", "hora_termina"):
        if _overlaps(hora_inicio, hora_termina, c.hora_inicio, c.hora_termina):
            return True
    return False


def _default_public_professional(clinica: Clinica):
    """
    Regresa el usuario profesional default para la agenda pública.
    Reglas:
    1) Buscar un usuario activo con StaffProfile cuyo nombre completo normalizado sea
       "edgar mauricio medina cruz".
    2) Si no existe, fallback a clinica.propietario (como antes).
    """
    target = _normalize_name(PUBLIC_DEFAULT_PRO_NAME)

    qs = User.objects.filter(is_active=True, staff_profile__isnull=False).order_by("id")

    # dataset pequeño => lo hacemos en Python para que sea robusto (acentos/espacios)
    for u in qs:
        full = _normalize_name(f"{u.first_name} {u.last_name}")
        if full == target:
            return u

        # fallback extra: si el username ya trae el nombre
        if _normalize_name(u.username) == target:
            return u

    return getattr(clinica, "propietario", None)


# =========================
# Public / Staff endpoints
# =========================
@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def public_team(request):
    qs = User.objects.filter(is_active=True, staff_profile__isnull=False).order_by("-id")
    ser = StaffUserSerializer(qs, many=True, context={"request": request})
    return Response(ser.data)


class StaffUserViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = StaffUserSerializer
    permission_classes = [IsAdminUserStrict]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        return User.objects.filter(staff_profile__isnull=False).order_by("-id")


class ProfesionalViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = User.objects.filter(is_active=True, staff_profile__isnull=False).order_by(
        "first_name", "last_name", "username"
    )
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]


class PacienteViewSet(viewsets.ModelViewSet):
    serializer_class = PacienteSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        role = _user_role(self.request.user)
        qs = Paciente.objects.all()

        if _is_professional_role(role):
            qs = qs.filter(citas__profesional=self.request.user).distinct()

        return qs


class ComentarioViewSet(viewsets.ModelViewSet):
    queryset = Comentario.objects.all()

    def get_permissions(self):
        if self.action in ["create", "public_list"]:
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]

    def get_serializer_class(self):
        if self.action == "public_list":
            return ComentarioPublicSerializer
        return ComentarioSerializer

    def perform_create(self, serializer):
        serializer.save(aprobado=False, clinica=_first_clinica())

    @action(detail=False, methods=["get"], permission_classes=[permissions.AllowAny])
    def public_list(self, request):
        queryset = Comentario.objects.filter(aprobado=True).order_by("-creado")[:20]
        serializer = ComentarioPublicSerializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"], permission_classes=[permissions.IsAuthenticated])
    def pending(self, request):
        qs = Comentario.objects.filter(aprobado=False).order_by("-creado")
        ser = ComentarioSerializer(qs, many=True)
        return Response(ser.data)

    @action(detail=True, methods=["patch"], permission_classes=[permissions.IsAuthenticated])
    def moderate(self, request, pk=None):
        obj = self.get_object()
        estado = (request.data.get("estado") or "").lower().strip()

        if estado == "aprobado":
            obj.aprobado = True
            obj.save(update_fields=["aprobado"])
            return Response(ComentarioSerializer(obj).data)

        if estado == "rechazado":
            obj.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

        return Response({"detail": "estado inválido. Usa 'aprobado' o 'rechazado'."}, status=400)


class CitaViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        role = _user_role(self.request.user)
        qs = Cita.objects.select_related("paciente", "servicio", "profesional").order_by("fecha", "hora_inicio")

        if _is_professional_role(role):
            qs = qs.filter(profesional=self.request.user)

        return qs

    def get_serializer_class(self):
        if self.action == "create":
            data = self.request.data
            if isinstance(data.get("paciente"), dict):
                return CitaCreateSerializer
        return CitaSerializer

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["clinica"] = _first_clinica()
        return ctx

    def perform_create(self, serializer):
        data = self.request.data
        role = _user_role(self.request.user)

        servicio_id = data.get("servicio") or data.get("servicio_id")
        servicio = Servicio.objects.filter(id=servicio_id).first()

        fecha = data.get("fecha")
        hora_inicio = data.get("hora_inicio")
        hora_termina = data.get("hora_termina")

        if hora_inicio and len(hora_inicio) == 5:
            hora_inicio = f"{hora_inicio}:00"
        if hora_termina and len(hora_termina) == 5:
            hora_termina = f"{hora_termina}:00"

        if not hora_termina and servicio and fecha and hora_inicio:
            ht = _calc_hora_termina(fecha, hora_inicio, servicio.duracion)
            hora_termina = ht.strftime("%H:%M:%S")

        profesional_id_payload = data.get("profesional")
        if _can_see_all_agendas(role) and profesional_id_payload:
            profesional_id = int(profesional_id_payload)
        else:
            profesional_id = self.request.user.id

        if profesional_id and fecha and hora_inicio and hora_termina:
            hi = datetime.strptime(hora_inicio, "%H:%M:%S").time()
            ht = datetime.strptime(hora_termina, "%H:%M:%S").time()
            if _validar_conflicto_cita(
                profesional_id=int(profesional_id),
                fecha=fecha,
                hora_inicio=hi,
                hora_termina=ht,
                exclude_id=None,
            ):
                raise ValueError("Conflicto: horario ocupado para este profesional.")

        profesional_obj = User.objects.filter(id=profesional_id).first() or self.request.user

        serializer.save(
            profesional=profesional_obj,
            hora_termina=hora_termina,
        )

    def perform_update(self, serializer):
        data = self.request.data
        role = _user_role(self.request.user)
        instance = self.get_object()

        profesional_id = instance.profesional_id
        if _can_see_all_agendas(role) and data.get("profesional"):
            profesional_id = int(data.get("profesional"))

        fecha = data.get("fecha") or instance.fecha.isoformat()

        hora_inicio = data.get("hora_inicio")
        hora_termina = data.get("hora_termina")

        if hora_inicio and len(hora_inicio) == 5:
            hora_inicio = f"{hora_inicio}:00"
        if hora_termina and len(hora_termina) == 5:
            hora_termina = f"{hora_termina}:00"

        hi = instance.hora_inicio
        ht = instance.hora_termina
        if hora_inicio:
            hi = datetime.strptime(hora_inicio, "%H:%M:%S").time()
        if hora_termina:
            ht = datetime.strptime(hora_termina, "%H:%M:%S").time()

        if _validar_conflicto_cita(
            profesional_id=int(profesional_id),
            fecha=fecha,
            hora_inicio=hi,
            hora_termina=ht,
            exclude_id=instance.id,
        ):
            return

        if _can_see_all_agendas(role) and data.get("profesional"):
            serializer.save(profesional_id=profesional_id)
        else:
            serializer.save()

    def update(self, request, *args, **kwargs):
        partial = True
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        try:
            self.perform_update(serializer)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=400)

        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        try:
            self.perform_destroy(instance)
        except Exception as exc:
            print("[CITAS] Error al eliminar cita:", repr(exc))
        return Response(status=status.HTTP_204_NO_CONTENT)


class ServicioViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Servicio.objects.filter(activo=True)
    serializer_class = ServicioSerializer
    permission_classes = [permissions.AllowAny]


class PagoViewSet(viewsets.ModelViewSet):
    queryset = (
        Pago.objects.select_related("cita", "cita__paciente", "cita__servicio", "cita__profesional")
        .all()
        .order_by("-fecha_pago", "-id")
    )
    serializer_class = PagoSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        role = _user_role(self.request.user)
        qs = super().get_queryset()

        if _is_professional_role(role):
            qs = qs.filter(cita__profesional=self.request.user)

        return qs

    @action(detail=True, methods=["get"], url_path="ticket", permission_classes=[IsAuthenticated])
    def ticket_pdf(self, request, pk=None):
        pago = self.get_object()
        cita = pago.cita
        clinica = _first_clinica()

        paciente = cita.paciente
        paciente_nombre = f"{paciente.nombres} {paciente.apellido_pat} {paciente.apellido_mat or ''}".strip()

        prof = cita.profesional
        prof_nombre = f"{prof.first_name or ''} {prof.last_name or ''}".strip() or prof.username

        negocio = clinica.nombre if clinica else "Clínica"
        monto = float(pago.monto_facturado or 0)

        buffer = BytesIO()
        c = canvas.Canvas(buffer, pagesize=letter)
        w, h = letter

        y = h - 60
        c.setFont("Helvetica-Bold", 14)
        c.drawString(50, y, "Ticket / Factura")
        y -= 25

        c.setFont("Helvetica", 11)
        c.drawString(50, y, f"Negocio: {negocio}")
        y -= 18
        c.drawString(50, y, f"Paciente: {paciente_nombre}")
        y -= 18
        c.drawString(50, y, f"Profesional: {prof_nombre}")
        y -= 18
        c.drawString(50, y, f"Fecha pago: {pago.fecha_pago.isoformat()}")
        y -= 18
        c.drawString(50, y, f"Método pago: {pago.metodo_pago}")
        y -= 25

        c.setFont("Helvetica-Bold", 12)
        c.drawString(50, y, f"Total facturado: $ {monto:,.2f}")
        y -= 30

        c.setFont("Helvetica", 9)
        c.drawString(50, y, "Documento generado por el sistema.")
        y -= 14

        c.showPage()
        c.save()

        pdf = buffer.getvalue()
        buffer.close()

        filename = f"ticket_pago_{pago.id}.pdf"
        resp = HttpResponse(pdf, content_type="application/pdf")
        resp["Content-Disposition"] = f'attachment; filename="{filename}"'
        return resp


# =========================
# ====== PÚBLICO ==========
# =========================
@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def public_agenda(request):
    fecha = request.query_params.get("fecha")
    if not fecha:
        return Response({"detail": "fecha requerida"}, status=400)

    clinica = _first_clinica()
    if not clinica:
        return Response({"detail": "No existe clínica configurada."}, status=400)

    profesional = _default_public_professional(clinica)
    if not profesional:
        return Response({"detail": "No hay profesional configurado."}, status=400)

    qs = (
        Cita.objects.filter(fecha=fecha, profesional=profesional)
        .exclude(estado="cancelado")
        .only("hora_inicio")
    )
    data = [{"hora_inicio": c.hora_inicio.strftime("%H:%M:%S")} for c in qs]
    return Response(data)


@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def public_create_cita(request):
    clinica = _first_clinica()
    if not clinica:
        return Response({"detail": "No existe clínica configurada."}, status=400)

    nombre = (request.data.get("nombre") or "").strip()
    telefono = (request.data.get("telefono") or "").strip()
    servicio_id = request.data.get("servicio_id")
    fecha = request.data.get("fecha")
    hora_inicio = request.data.get("hora_inicio")

    if not (nombre and telefono and servicio_id and fecha and hora_inicio):
        return Response({"detail": "Faltan campos requeridos."}, status=400)

    servicio = Servicio.objects.filter(id=servicio_id, activo=True).first()
    if not servicio:
        return Response({"detail": "Servicio inválido."}, status=400)

    hora_inicio_full = f"{hora_inicio}:00" if len(hora_inicio) == 5 else hora_inicio

    paciente, _ = Paciente.objects.get_or_create(
        clinica=clinica,
        telefono=telefono,
        defaults={
            "nombres": nombre,
            "apellido_pat": "",
            "apellido_mat": "",
            "fecha_nac": None,
            "genero": "",
            "correo": "",
            "molestia": "",
            "notas": "",
        },
    )

    # ✅ PROFESIONAL DEFAULT: Edgar Mauricio Medina Cruz (fallback a clinica.propietario)
    profesional = _default_public_professional(clinica)
    if not profesional:
        return Response({"detail": "No hay profesional configurado."}, status=400)

    hora_termina = _calc_hora_termina(fecha, hora_inicio_full, servicio.duracion).strftime("%H:%M:%S")

    hi = datetime.strptime(hora_inicio_full, "%H:%M:%S").time()
    ht = datetime.strptime(hora_termina, "%H:%M:%S").time()

    if _validar_conflicto_cita(
        profesional_id=profesional.id,
        fecha=fecha,
        hora_inicio=hi,
        hora_termina=ht,
        exclude_id=None,
    ):
        return Response({"detail": "Horario ya ocupado."}, status=409)

    cita = Cita.objects.create(
        paciente=paciente,
        servicio=servicio,
        profesional=profesional,
        fecha=fecha,
        hora_inicio=hi,
        hora_termina=ht,
        precio=servicio.precio,
        estado="reservado",
        pagado=False,
    )

    return Response(CitaSerializer(cita).data, status=201)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request):
    u = request.user
    role = _user_role(u)
    full_name = (u.get_full_name() or "").strip() or u.username
    return Response(
        {
            "id": u.id,
            "email": u.email,
            "username": u.username,
            "full_name": full_name,
            "rol": role,
        }
    )
