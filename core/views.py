# core/views.py
from datetime import datetime, timedelta
from io import BytesIO
import unicodedata

from decimal import Decimal
from django.conf import settings
from django.utils import timezone
from django.db import models
from decimal import Decimal
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from django.contrib.auth.models import User
from django.db.models import Q
from django.http import HttpResponse

from rest_framework import permissions, viewsets, status, mixins
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

from .models import Paciente, Comentario, Cita, Servicio, Clinica, Pago, StaffProfile,BloqueoHorario
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
    BloqueoHorarioSerializer,
)
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from .permissions import IsAdminUserStrict


# =========================
# Helpers
# =========================
PUBLIC_DEFAULT_PRO_NAME = "l.f.t edgar mauricio medina cruz"


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

# core/views.py (fragmento: dentro de CitaViewSet)
from rest_framework.exceptions import ValidationError

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

        profesional_obj = User.objects.filter(id=profesional_id).first()
        if not profesional_obj:
            raise ValidationError({"profesional": "Profesional inválido."})

        # ✅ HORA COMPARTIDA: NO VALIDAR CONFLICTO (permitimos múltiples citas en el mismo rango)
        serializer.save(profesional=profesional_obj)

    def perform_update(self, serializer):
        data = self.request.data
        role = _user_role(self.request.user)

        profesional_id_payload = data.get("profesional")
        if _can_see_all_agendas(role) and profesional_id_payload:
            profesional_obj = User.objects.filter(id=int(profesional_id_payload)).first()
            if not profesional_obj:
                raise ValidationError({"profesional": "Profesional inválido."})
            serializer.save(profesional=profesional_obj)
            return

        # profesional no admin-like: no permitir cambiar profesional
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

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx


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

        RFC_FIJO = "MECE000513F74"

        # =========================
        # Paths en MEDIA
        # =========================
        def media_path(filename: str):
            try:
                # settings.MEDIA_ROOT puede ser str o Path
                return (settings.MEDIA_ROOT / filename) if hasattr(settings, "MEDIA_ROOT") else None
            except Exception:
                return None

        logo_path = media_path("fisionerv.png")
        qr_path = media_path("qr.png")

        # =========================
        # Helpers
        # =========================
        def up(s: str) -> str:
            return (s or "").strip().upper()

        def safe_str(s) -> str:
            return (s or "").strip()

        def money(x) -> str:
            try:
                v = Decimal(x or 0)
                return f"$ {v:,.2f}".upper()
            except Exception:
                return "$ 0.00"

        def split_chunks(text: str, width_chars: int):
            """
            Parte texto en segmentos de longitud fija (simple y robusto para tickets).
            """
            t = up(text)
            if not t:
                return []
            out = []
            while len(t) > width_chars:
                out.append(t[:width_chars])
                t = t[width_chars:]
            if t:
                out.append(t)
            return out

        # Dibujo centrado (por ancho real del string)
        def draw_center(c, y, text, font="Helvetica", size=8.5):
            c.setFont(font, size)
            t = up(text)
            w = c.stringWidth(t, font, size)
            x = (ticket_width - w) / 2
            c.drawString(max(2 * mm, x), y, t)

        # Dibujo "label izquierda" y "valor derecha"
        def draw_lr(c, y, left, right, font="Helvetica", size=8.5):
            c.setFont(font, size)
            l = up(left)
            r = up(right)

            x_left = 4 * mm
            x_right = ticket_width - 4 * mm

            # Izquierda
            c.drawString(x_left, y, l)

            # Derecha (alineado a la derecha)
            rw = c.stringWidth(r, font, size)
            c.drawString(x_right - rw, y, r)

        # =========================
        # Datos negocio / personas
        # =========================
        negocio = safe_str(getattr(clinica, "nombre", "")) or "FISIONERV"
        direccion = safe_str(getattr(clinica, "direccion", "")) or "DIRECCION NO CONFIGURADA"

        paciente = cita.paciente
        paciente_nombre = f"{paciente.nombres} {paciente.apellido_pat} {paciente.apellido_mat or ''}".strip()

        prof = cita.profesional
        prof_nombre = (f"{prof.first_name or ''} {prof.last_name or ''}".strip() or prof.username)

        # =========================
        # Totales
        # =========================
        costo_servicio = Decimal(cita.precio or 0)

        monto_facturado = Decimal(cita.monto_final or 0) if Decimal(cita.monto_final or 0) > 0 else Decimal(pago.monto_facturado or 0)

        descuento_pct = Decimal(cita.descuento_porcentaje or 0)
        base_desc = Decimal(pago.monto_facturado or costo_servicio)
        descuento_monto = (base_desc * descuento_pct) / Decimal("100")

        total_a_pagar = Decimal(cita.monto_final or 0)
        if total_a_pagar <= 0:
            total_a_pagar = max(base_desc - descuento_monto, Decimal("0"))

        pagos_qs = cita.pagos.all()
        total_pagado = pagos_qs.aggregate(total=models.Sum("anticipo")).get("total") or Decimal("0")

        restante = max(total_a_pagar - Decimal(total_pagado), Decimal("0"))

        by_method = (
            pagos_qs.values("metodo_pago")
            .annotate(total=models.Sum("anticipo"))
            .order_by("metodo_pago")
        )

        # =========================
        # Ticket meta
        # =========================
        now = timezone.localtime(timezone.now())
        fecha_emision = now.strftime("%Y-%m-%d")
        hora_emision = now.strftime("%H:%M:%S")

        venta_no = f"{cita.id}"
        ticket_no = f"{pago.id}"

        servicio_nombre = safe_str(getattr(cita.servicio, "nombre", "")) or "SERVICIO"

        # =========================
        # Layout ticket (80mm)
        # =========================
        ticket_width = 80 * mm
        line_h = 4.0 * mm
        top_pad = 8 * mm
        bottom_pad = 8 * mm

        sep = "-" * 32  # visual

        # Calculamos alto aproximado por cantidad de líneas (incluyendo secciones extra)
        # Importante: aquí ya no usamos "lines" para render directo, pero sí para medir alto.
        header_lines = []
        header_lines.append(up(negocio))
        header_lines.append(up(f"RFC: {RFC_FIJO}"))
        header_lines += split_chunks(direccion, 32)

        ticket_info_lines = [
            up(f"VENTA: {venta_no}  TICKET: {ticket_no}"),
            up(f"EMISION: {fecha_emision} {hora_emision}"),
        ]

        cliente_lines = [up("CLIENTE")] + split_chunks(paciente_nombre, 32)
        prof_lines = [up("PROFESIONAL")] + split_chunks(prof_nombre, 32)

        detalle_lines = [
            up("DETALLE"),
            up(servicio_nombre[:32]),
            up(sep),
            "COSTO",
            f"DESC ({descuento_pct}%)",
            "MONTO FACTURADO",
            up(sep),
            "TOTAL A PAGAR",
            "COBRADO",
            "RESTANTE",
            up(sep),
            up("PAGOS POR METODO"),
        ]

        pagos_lines = []
        if by_method:
            for row in by_method:
                mp = (row.get("metodo_pago") or "otro").strip()
                mp_label = {
                    "efectivo": "EFECTIVO",
                    "tarjeta": "TARJETA",
                    "transferencia": "TRANSFERENCIA",
                    "otro": "OTRO",
                }.get(mp, up(mp))
                pagos_lines.append(mp_label)
        else:
            pagos_lines.append("SIN PAGOS REGISTRADOS")

        footer_lines = [
            up(sep),
            up("GRACIAS POR SU PREFERENCIA"),
            up("DOCUMENTO GENERADO POR EL SISTEMA"),
        ]

        # QR reserva de espacio (si existe)
        qr_h = 0
        qr_w = 0
        has_qr = False
        if qr_path:
            try:
                import os
                if os.path.exists(str(qr_path)):
                    has_qr = True
                    qr_w = 18 * mm
                    qr_h = 18 * mm
            except Exception:
                has_qr = False

        # Logo reserva
        logo_h = 0
        has_logo = False
        if logo_path:
            try:
                import os
                if os.path.exists(str(logo_path)):
                    has_logo = True
                    logo_h = 18 * mm
            except Exception:
                has_logo = False

        # Contamos líneas “reales” que se dibujan
        # + pagosl ines (cada método = 1 línea)
        total_text_lines = (
            len(header_lines)
            + 1  # sep
            + len(ticket_info_lines)
            + 1  # sep
            + len(cliente_lines)
            + len(prof_lines)
            + 1  # sep
            + 1  # DETALLE title (ya va en detalle_lines, pero contamos como texto)
            + 1  # servicio
            + 1  # sep
            + 3  # costo/desc/monto
            + 1  # sep
            + 3  # total/cobrado/restante
            + 1  # sep
            + 1  # PAGOS POR METODO
            + max(1, len(pagos_lines))
            + len(footer_lines)
        )

        # Alto final (dejamos espacio extra por QR para que no se “encime”)
        height = top_pad + bottom_pad + (total_text_lines * line_h) + logo_h + (qr_h if has_qr else 0) + (6 * mm)

        buffer = BytesIO()
        c = canvas.Canvas(buffer, pagesize=(ticket_width, height))

        y = height - top_pad

        # =========================
        # LOGO (centrado)
        # =========================
        if has_logo:
            try:
                img = ImageReader(str(logo_path))
                draw_w = 60 * mm
                draw_h = 18 * mm
                x = (ticket_width - draw_w) / 2
                c.drawImage(img, x, y - draw_h, width=draw_w, height=draw_h, preserveAspectRatio=True, mask="auto")
                y -= (draw_h + 3 * mm)
            except Exception:
                pass

        # =========================
        # HEADER CENTRADO
        # =========================
        c.setFont("Helvetica", 8.5)

        draw_center(c, y, negocio, "Helvetica-Bold", 9)
        y -= line_h

        draw_center(c, y, f"RFC: {RFC_FIJO}", "Helvetica", 8.5)
        y -= line_h

        for line in split_chunks(direccion, 32):
            draw_center(c, y, line, "Helvetica", 8.5)
            y -= line_h

        draw_center(c, y, sep, "Helvetica", 8.5)
        y -= line_h

        # =========================
        # DATOS TICKET CENTRADOS
        # =========================
        draw_center(c, y, f"VENTA: {venta_no}  TICKET: {ticket_no}", "Helvetica", 8.5)
        y -= line_h
        draw_center(c, y, f"EMISION: {fecha_emision} {hora_emision}", "Helvetica", 8.5)
        y -= line_h

        draw_center(c, y, sep, "Helvetica", 8.5)
        y -= line_h

        # =========================
        # CLIENTE / PROF CENTRADOS
        # =========================
        draw_center(c, y, "CLIENTE", "Helvetica-Bold", 8.5)
        y -= line_h
        for line in split_chunks(paciente_nombre, 32):
            draw_center(c, y, line, "Helvetica", 8.5)
            y -= line_h

        y -= (1 * mm)

        draw_center(c, y, "PROFESIONAL", "Helvetica-Bold", 8.5)
        y -= line_h
        for line in split_chunks(prof_nombre, 32):
            draw_center(c, y, line, "Helvetica", 8.5)
            y -= line_h

        draw_center(c, y, sep, "Helvetica", 8.5)
        y -= line_h

        # =========================
        # DETALLE (servicio centrado)
        # =========================
        draw_center(c, y, "DETALLE", "Helvetica-Bold", 8.5)
        y -= line_h

        for line in split_chunks(servicio_nombre[:64], 32):
            draw_center(c, y, line, "Helvetica", 8.5)
            y -= line_h

        draw_center(c, y, sep, "Helvetica", 8.5)
        y -= line_h

        # COSTOS: etiqueta izquierda / monto derecha
        draw_lr(c, y, "COSTO", money(costo_servicio))
        y -= line_h
        draw_lr(c, y, f"DESC ({descuento_pct}%)", f"-{money(descuento_monto)}")
        y -= line_h
        draw_lr(c, y, "MONTO FACTURADO", money(monto_facturado))
        y -= line_h

        draw_center(c, y, sep, "Helvetica", 8.5)
        y -= line_h

        draw_lr(c, y, "TOTAL A PAGAR", money(total_a_pagar))
        y -= line_h
        draw_lr(c, y, "COBRADO", money(total_pagado))
        y -= line_h
        draw_lr(c, y, "RESTANTE", money(restante))
        y -= line_h

        draw_center(c, y, sep, "Helvetica", 8.5)
        y -= line_h

        # =========================
        # PAGOS POR METODO (monto a la derecha)
        # =========================
        draw_center(c, y, "PAGOS POR METODO", "Helvetica-Bold", 8.5)
        y -= line_h

        if by_method:
            for row in by_method:
                mp = (row.get("metodo_pago") or "otro").strip()
                tot = row.get("total") or 0
                mp_label = {
                    "efectivo": "EFECTIVO",
                    "tarjeta": "TARJETA",
                    "transferencia": "TRANSFERENCIA",
                    "otro": "OTRO",
                }.get(mp, up(mp))

                draw_lr(c, y, mp_label, money(tot))
                y -= line_h
        else:
            draw_center(c, y, "SIN PAGOS REGISTRADOS", "Helvetica", 8.5)
            y -= line_h

        draw_center(c, y, sep, "Helvetica", 8.5)
        y -= line_h

        # =========================
        # FOOTER centrado
        # =========================
        draw_center(c, y, "GRACIAS POR SU PREFERENCIA", "Helvetica-Bold", 8.5)
        y -= line_h
        draw_center(c, y, "DOCUMENTO GENERADO POR EL SISTEMA", "Helvetica", 8.0)
        y -= line_h

        # =========================
        # QR abajo derecha
        # =========================
        if has_qr:
            try:
                img_qr = ImageReader(str(qr_path))
                # pos: abajo derecha con padding
                x_qr = ticket_width - 4 * mm - qr_w
                y_qr = 4 * mm
                c.drawImage(img_qr, x_qr, y_qr, width=qr_w, height=qr_h, preserveAspectRatio=True, mask="auto")
            except Exception:
                pass

        c.showPage()
        c.save()

        pdf = buffer.getvalue()
        buffer.close()

        filename = f"TICKET_VENTA_{venta_no}_PAGO_{ticket_no}.PDF"
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

class BloqueoHorarioViewSet(viewsets.ModelViewSet):
    queryset = BloqueoHorario.objects.select_related("profesional").all()
    serializer_class = BloqueoHorarioSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        role = _user_role(self.request.user)
        qs = super().get_queryset()

        # Profesional solo ve sus bloqueos
        if _is_professional_role(role):
            qs = qs.filter(profesional=self.request.user)

        return qs

class ServicioAdminViewSet(viewsets.ModelViewSet):
    serializer_class = ServicioSerializer
    permission_classes = [IsAdminUserStrict]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        # Admin ve todo (activos e inactivos)
        return Servicio.objects.all().order_by("-id")

    def perform_create(self, serializer):
        clinica = _first_clinica()
        if not clinica:
            raise ValidationError({"detail": "No existe clínica configurada."})
        serializer.save(clinica=clinica)

import re
from rest_framework.parsers import MultiPartParser, FormParser

def _password_fuerte(pw: str) -> bool:
    if not pw or len(pw) < 8:
        return False
    if not re.search(r"[A-Z]", pw):
        return False
    if not re.search(r"[a-z]", pw):
        return False
    if not re.search(r"[0-9]", pw):
        return False
    if not re.search(r"[^A-Za-z0-9]", pw):
        return False
    return True

@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def me_update(request):
    """
    Actualiza datos del usuario en sesión:
    - username, first_name, last_name, email
    - foto (StaffProfile)
    - cambio de contraseña opcional:
        requiere current_password + new_password fuerte
    """
    u = request.user

    username = (request.data.get("username") or "").strip()
    first_name = (request.data.get("first_name") or "").strip()
    last_name = (request.data.get("last_name") or "").strip()
    email = (request.data.get("email") or "").strip()

    if not username:
        return Response({"detail": "username requerido."}, status=400)
    if not email:
        return Response({"detail": "email requerido."}, status=400)

    # ✅ si manda new_password, aplicar validación fuerte
    new_password = request.data.get("new_password") or ""
    current_password = request.data.get("current_password") or ""

    if new_password:
        if not current_password:
            return Response({"detail": "Escribe tu contraseña actual para cambiarla."}, status=400)
        if not u.check_password(current_password):
            return Response({"detail": "La contraseña actual es incorrecta."}, status=400)
        if not _password_fuerte(new_password):
            return Response(
                {"detail": "La nueva contraseña no cumple requisitos (8+, mayúscula, minúscula, número, símbolo)."},
                status=400,
            )
        u.set_password(new_password)

    u.username = username
    u.first_name = first_name
    u.last_name = last_name
    u.email = email
    u.save()

    # ✅ foto en StaffProfile (si existe)
    foto = request.FILES.get("foto", None)
    sp = getattr(u, "staff_profile", None)
    if sp and foto:
        sp.foto = foto
        sp.save(update_fields=["foto"])

    role = _user_role(u)
    full_name = (u.get_full_name() or "").strip() or u.username

    # devolvemos lo que usa tu front
    return Response(
        {
            "id": u.id,
            "email": u.email,
            "username": u.username,
            "first_name": u.first_name,
            "last_name": u.last_name,
            "full_name": full_name,
            "rol": role,
            "foto_url": (request.build_absolute_uri(sp.foto.url) if (sp and sp.foto) else None),
        }
    )
