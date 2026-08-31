from decimal import Decimal
from io import BytesIO
from pathlib import Path
from django.conf import settings
from django.db import models
from django.http import HttpResponse
from django.utils import timezone
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from core.models import Cita, Pago
from core.serializers.finanzas import PagoSerializer
from core.utilidades import es_profesional, primera_clinica, rol_usuario


class PagoViewSet(viewsets.ModelViewSet):
    queryset = Pago.objects.select_related("cita", "cita__paciente", "cita__servicio", "cita__profesional").all().order_by("-fecha_pago", "-id")
    serializer_class = PagoSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        rol = rol_usuario(self.request.user); qs = super().get_queryset()
        if es_profesional(rol): qs = qs.filter(cita__profesional=self.request.user)
        cita_id = self.request.query_params.get("cita")
        if cita_id: qs = qs.filter(cita_id=cita_id)
        return qs

    def _recalcular_cita(self, cita):
        pagos_qs = cita.pagos.all(); total_pagado = pagos_qs.aggregate(total=models.Sum("anticipo")).get("total") or Decimal("0"); pago_base = pagos_qs.order_by("-fecha_pago", "-id").first()
        if pago_base: monto_facturado = Decimal(pago_base.monto_facturado or 0); descuento_porcentaje = Decimal(pago_base.descuento_porcentaje or 0)
        else: monto_facturado = Decimal(cita.monto_final or cita.precio or 0); descuento_porcentaje = Decimal(cita.descuento_porcentaje or 0)
        total_con_descuento = max(monto_facturado - (monto_facturado * descuento_porcentaje) / Decimal("100"), Decimal("0")); restante = max(total_con_descuento - total_pagado, Decimal("0"))
        cita.descuento_porcentaje = descuento_porcentaje; cita.monto_final = total_con_descuento; cita.anticipo = total_pagado; cita.pagado = restante <= 0 and total_con_descuento > 0
        cita.save(update_fields=["descuento_porcentaje", "monto_final", "anticipo", "pagado", "actualizado"])

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object(); cita = getattr(instance, "cita", None); instance.delete()
        if cita:
            try: self._recalcular_cita(cita)
            except Exception as exc: print("[PAGOS] Error recalculando cita tras eliminar pago:", repr(exc))
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["get"], url_path="ticket", permission_classes=[IsAuthenticated])
    def ticket_pdf(self, request, pk=None):
        pago = self.get_object(); cita = pago.cita; clinica = primera_clinica(); RFC_FIJO = "MECE000513F74"

        def media_path(filename):
            try: return Path(settings.MEDIA_ROOT) / filename
            except Exception: return None

        logo_path = media_path("fisionerv.png"); qr_path = media_path("qr.png")
        def up(s): return (s or "").strip().upper()
        def safe_str(s): return (s or "").strip()
        def money(x):
            try: return f"$ {Decimal(x or 0):,.2f}".upper()
            except Exception: return "$ 0.00"
        def split_chunks(text, width_chars):
            t = up(text); out = []
            while len(t) > width_chars: out.append(t[:width_chars]); t = t[width_chars:]
            if t: out.append(t)
            return out
        def draw_center(pdf, y, text, font="Helvetica", size=8.5):
            pdf.setFont(font, size); t = up(text); w = pdf.stringWidth(t, font, size); pdf.drawString(max(2 * mm, (ticket_width - w) / 2), y, t)
        def draw_lr(pdf, y, left, right, font="Helvetica", size=8.5):
            pdf.setFont(font, size); l = up(left); r = up(right); x_left = 4 * mm; x_right = ticket_width - 4 * mm; pdf.drawString(x_left, y, l); pdf.drawString(x_right - pdf.stringWidth(r, font, size), y, r)

        negocio = safe_str(getattr(clinica, "nombre", "")) or "FISIONERV"; direccion = safe_str(getattr(clinica, "direccion", "")) or "DIRECCION NO CONFIGURADA"
        paciente = cita.paciente; paciente_nombre = f"{paciente.nombres} {paciente.apellido_pat} {paciente.apellido_mat or ''}".strip(); prof = cita.profesional; prof_nombre = f"{prof.first_name or ''} {prof.last_name or ''}".strip() or prof.username
        costo_servicio = Decimal(cita.precio or 0); monto_facturado = Decimal(cita.monto_final or 0) if Decimal(cita.monto_final or 0) > 0 else Decimal(pago.monto_facturado or 0); descuento_pct = Decimal(cita.descuento_porcentaje or 0); base_desc = Decimal(pago.monto_facturado or costo_servicio); descuento_monto = (base_desc * descuento_pct) / Decimal("100")
        total_a_pagar = Decimal(cita.monto_final or 0)
        if total_a_pagar <= 0: total_a_pagar = max(base_desc - descuento_monto, Decimal("0"))
        pagos_qs = cita.pagos.all(); total_pagado = pagos_qs.aggregate(total=models.Sum("anticipo")).get("total") or Decimal("0"); restante = max(total_a_pagar - Decimal(total_pagado), Decimal("0")); by_method = pagos_qs.values("metodo_pago").annotate(total=models.Sum("anticipo")).order_by("metodo_pago")
        now = timezone.now(); fecha_emision = now.strftime("%Y-%m-%d"); hora_emision = now.strftime("%H:%M:%S"); venta_no = f"{cita.id}"; ticket_no = f"{pago.id}"; servicio_nombre = safe_str(getattr(cita.servicio, "nombre", "")) or "SERVICIO"
        ticket_width = 80 * mm; line_h = 4.0 * mm; top_pad = 8 * mm; bottom_pad = 8 * mm; sep = "-" * 32
        header_lines = [up(negocio), up(f"RFC: {RFC_FIJO}")] + split_chunks(direccion, 32); cliente_lines = [up("CLIENTE")] + split_chunks(paciente_nombre, 32); prof_lines = [up("PROFESIONAL")] + split_chunks(prof_nombre, 32)
        pagos_lines = []
        if by_method:
            for row in by_method: pagos_lines.append({"efectivo": "EFECTIVO", "tarjeta": "TARJETA", "transferencia": "TRANSFERENCIA", "otro": "OTRO"}.get((row.get("metodo_pago") or "otro").strip(), up(row.get("metodo_pago") or "otro")))
        else: pagos_lines.append("SIN PAGOS REGISTRADOS")
        footer_lines = [up(sep), up("GRACIAS POR SU PREFERENCIA"), up("DOCUMENTO GENERADO POR EL SISTEMA")]
        qr_h = qr_w = logo_h = 0; has_qr = has_logo = False
        try:
            if qr_path and qr_path.exists(): has_qr = True; qr_w = qr_h = 18 * mm
            if logo_path and logo_path.exists(): has_logo = True; logo_h = 18 * mm
        except Exception: has_qr = has_logo = False
        total_text_lines = len(header_lines) + 1 + 2 + 1 + len(cliente_lines) + len(prof_lines) + 1 + 1 + 1 + 1 + 3 + 1 + 3 + 1 + 1 + max(1, len(pagos_lines)) + len(footer_lines)
        height = top_pad + bottom_pad + total_text_lines * line_h + logo_h + (qr_h if has_qr else 0) + 6 * mm
        buffer = BytesIO(); pdf = canvas.Canvas(buffer, pagesize=(ticket_width, height)); y = height - top_pad
        if has_logo:
            try:
                img = ImageReader(str(logo_path)); draw_w = 60 * mm; draw_h = 18 * mm; pdf.drawImage(img, (ticket_width - draw_w) / 2, y - draw_h, width=draw_w, height=draw_h, preserveAspectRatio=True, mask="auto"); y -= draw_h + 3 * mm
            except Exception: pass
        draw_center(pdf, y, negocio, "Helvetica-Bold", 9); y -= line_h; draw_center(pdf, y, f"RFC: {RFC_FIJO}"); y -= line_h
        for line in split_chunks(direccion, 32): draw_center(pdf, y, line); y -= line_h
        draw_center(pdf, y, sep); y -= line_h; draw_center(pdf, y, f"VENTA: {venta_no}  TICKET: {ticket_no}"); y -= line_h; draw_center(pdf, y, f"EMISION: {fecha_emision} {hora_emision}"); y -= line_h; draw_center(pdf, y, sep); y -= line_h
        draw_center(pdf, y, "CLIENTE", "Helvetica-Bold"); y -= line_h
        for line in split_chunks(paciente_nombre, 32): draw_center(pdf, y, line); y -= line_h
        y -= 1 * mm; draw_center(pdf, y, "PROFESIONAL", "Helvetica-Bold"); y -= line_h
        for line in split_chunks(prof_nombre, 32): draw_center(pdf, y, line); y -= line_h
        draw_center(pdf, y, sep); y -= line_h; draw_center(pdf, y, "DETALLE", "Helvetica-Bold"); y -= line_h
        for line in split_chunks(servicio_nombre[:64], 32): draw_center(pdf, y, line); y -= line_h
        draw_center(pdf, y, sep); y -= line_h; draw_lr(pdf, y, "COSTO", money(costo_servicio)); y -= line_h; draw_lr(pdf, y, f"DESC ({descuento_pct}%)", f"-{money(descuento_monto)}"); y -= line_h; draw_lr(pdf, y, "MONTO FACTURADO", money(monto_facturado)); y -= line_h
        draw_center(pdf, y, sep); y -= line_h; draw_lr(pdf, y, "TOTAL A PAGAR", money(total_a_pagar)); y -= line_h; draw_lr(pdf, y, "COBRADO", money(total_pagado)); y -= line_h; draw_lr(pdf, y, "RESTANTE", money(restante)); y -= line_h
        draw_center(pdf, y, sep); y -= line_h; draw_center(pdf, y, "PAGOS POR METODO", "Helvetica-Bold"); y -= line_h
        if by_method:
            for row in by_method:
                mp = (row.get("metodo_pago") or "otro").strip(); label = {"efectivo": "EFECTIVO", "tarjeta": "TARJETA", "transferencia": "TRANSFERENCIA", "otro": "OTRO"}.get(mp, up(mp)); draw_lr(pdf, y, label, money(row.get("total") or 0)); y -= line_h
        else: draw_center(pdf, y, "SIN PAGOS REGISTRADOS"); y -= line_h
        draw_center(pdf, y, sep); y -= line_h; draw_center(pdf, y, "GRACIAS POR SU PREFERENCIA", "Helvetica-Bold"); y -= line_h; draw_center(pdf, y, "DOCUMENTO GENERADO POR EL SISTEMA", "Helvetica", 8.0); y -= line_h
        if has_qr:
            try: pdf.drawImage(ImageReader(str(qr_path)), ticket_width - 4 * mm - qr_w, 4 * mm, width=qr_w, height=qr_h, preserveAspectRatio=True, mask="auto")
            except Exception: pass
        pdf.showPage(); pdf.save(); contenido = buffer.getvalue(); buffer.close(); filename = f"TICKET_VENTA_{venta_no}_PAGO_{ticket_no}.PDF"; response = HttpResponse(contenido, content_type="application/pdf"); response["Content-Disposition"] = f'attachment; filename="{filename}"'; return response

    @action(detail=False, methods=["delete"], url_path=r"by-cita/(?P<cita_id>\d+)")
    def delete_by_cita(self, request, cita_id=None):
        cita = Cita.objects.filter(id=cita_id).first()
        if not cita: return Response(status=status.HTTP_204_NO_CONTENT)
        try: cita.pagos.all().delete(); self._recalcular_cita(cita)
        except Exception as exc: print("[PAGOS] Error borrando pagos por cita:", repr(exc)); return Response({"detail": "No se pudo eliminar."}, status=400)
        return Response(status=status.HTTP_204_NO_CONTENT)
