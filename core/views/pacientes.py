#backend/core/views/pacientes.py
from datetime import date, timedelta
from django.db import transaction
from django.db.models import Count, Exists, IntegerField, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from core.models import Cita, DocumentoPaciente, Paciente, RegistroClinico
from core.serializers.agenda import CitaSerializer
from core.serializers.pacientes import DocumentoPacienteSerializer, PacienteListadoSerializer, PacienteSerializer, RegistroClinicoSerializer
from core.utilidades import es_profesional, primera_clinica, puede_ver_contacto_paciente, rol_usuario
from django.utils.dateparse import parse_date

class PaginacionPacientes(PageNumberPagination):
    page_size = 200
    page_size_query_param = None
    max_page_size = 200


def dias_hasta_cumple(fecha_nac, hoy=None):
    if not fecha_nac: return None
    hoy = hoy or date.today()
    try: proximo = fecha_nac.replace(year=hoy.year)
    except ValueError: proximo = date(hoy.year, 2, 28)
    if proximo < hoy:
        try: proximo = fecha_nac.replace(year=hoy.year + 1)
        except ValueError: proximo = date(hoy.year + 1, 2, 28)
    return (proximo - hoy).days


class PacienteViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = PaginacionPacientes
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def _base_queryset(self):
        qs = Paciente.objects.select_related("clinica").all(); rol = rol_usuario(self.request.user)
        if es_profesional(rol):
            qs = qs.annotate(_visible_profesional=Exists(Cita.objects.filter(paciente_id=OuterRef("pk"), profesional=self.request.user))).filter(_visible_profesional=True)
        return qs

    def get_queryset(self):
        qs = self._base_queryset()

        search = (self.request.query_params.get("search") or "").strip()
        profesional = self.request.query_params.get("profesional")
        servicio = self.request.query_params.get("servicio")
        estado_reserva = (self.request.query_params.get("estado_reserva") or "").strip().lower()
        estado_tratamiento = (self.request.query_params.get("estado_tratamiento") or "").strip().lower()
        clinica_nombre = (self.request.query_params.get("clinica_nombre") or "").strip()
        desde = self.request.query_params.get("registro_desde")
        hasta = self.request.query_params.get("registro_hasta")

        if search:
            filtro_busqueda = (
                Q(nombres__icontains=search) |
                Q(apellido_pat__icontains=search) |
                Q(apellido_mat__icontains=search)
            )

            if puede_ver_contacto_paciente(self.request.user):
                filtro_busqueda |= (
                    Q(correo__icontains=search) |
                    Q(telefono__icontains=search)
                )

            qs = qs.filter(filtro_busqueda)

        if clinica_nombre:
            qs = qs.filter(clinica__nombre__iexact=clinica_nombre)

        if estado_tratamiento in {"en_tratamiento", "alta"}:
            qs = qs.filter(estado_tratamiento=estado_tratamiento)

        if desde:
            qs = qs.filter(registro__gte=desde)

        if hasta:
            qs = qs.filter(registro__lte=hasta)

        citas_filtro = Cita.objects.filter(paciente_id=OuterRef("pk"))

        if profesional:
            try:
                qs = qs.annotate(
                    _filtro_profesional=Exists(
                        citas_filtro.filter(profesional_id=int(profesional))
                    )
                ).filter(_filtro_profesional=True)
            except (TypeError, ValueError):
                pass

        if servicio:
            try:
                filtro_servicio = citas_filtro.filter(servicio_id=int(servicio))
            except (TypeError, ValueError):
                filtro_servicio = citas_filtro.filter(servicio__nombre__iexact=servicio)

            qs = qs.annotate(
                _filtro_servicio=Exists(filtro_servicio)
            ).filter(_filtro_servicio=True)

        if estado_reserva in {"con", "con reservas"}:
            qs = qs.annotate(
                _tiene_citas=Exists(citas_filtro)
            ).filter(_tiene_citas=True)

        if estado_reserva in {"sin", "sin reservas"}:
            qs = qs.annotate(
                _tiene_citas=Exists(citas_filtro)
            ).filter(_tiene_citas=False)

        ultima = Cita.objects.filter(
            paciente_id=OuterRef("pk")
        ).order_by("-fecha", "-hora_inicio", "-id")

        conteo = (
            Cita.objects
            .filter(paciente_id=OuterRef("pk"))
            .values("paciente_id")
            .annotate(total=Count("id"))
            .values("total")[:1]
        )

        return qs.annotate(
            ultimo_servicio=Subquery(
                ultima.values("servicio__nombre")[:1]
            ),
            ultima_cita_fecha=Subquery(
                ultima.values("fecha")[:1]
            ),
            total_citas=Coalesce(
                Subquery(conteo, output_field=IntegerField()),
                Value(0),
            ),
        ).order_by(
            "apellido_pat",
            "apellido_mat",
            "nombres",
            "id",
        )

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        paciente = self.get_object()
        data = request.data.copy()

        # Un usuario sin permiso de contacto no puede sobrescribir,
        # borrar ni modificar teléfono/correo.
        if not puede_ver_contacto_paciente(request.user):
            data.pop("telefono", None)
            data.pop("correo", None)

        estado_anterior = paciente.estado_tratamiento
        estado_nuevo = data.get(
            "estado_tratamiento",
            estado_anterior,
        )

        pasa_a_alta = (
            estado_anterior != "alta" and
            estado_nuevo == "alta"
        )

        fecha_alta = paciente.fecha_alta

        if estado_nuevo == "alta":
            fecha_alta_raw = data.get("fecha_alta")

            if fecha_alta_raw:
                fecha_alta = parse_date(
                    str(fecha_alta_raw)
                )

                if not fecha_alta:
                    return Response(
                        {
                            "fecha_alta": (
                                "La fecha de alta no es válida."
                            )
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            else:
                fecha_alta = date.today()
                data["fecha_alta"] = (
                    fecha_alta.isoformat()
                )
        else:
            fecha_alta = None
            data["fecha_alta"] = None

        citas_posteriores = Cita.objects.none()
        total_citas_posteriores = 0

        if pasa_a_alta and fecha_alta:
            citas_posteriores = (
                paciente.citas
                .filter(fecha__gt=fecha_alta)
                .exclude(estado="cancelado")
                .order_by("fecha", "hora_inicio")
            )

            total_citas_posteriores = (
                citas_posteriores.count()
            )

        decision_raw = request.query_params.get(
            "eliminar_citas_posteriores"
        )

        decision_eliminar = None

        if decision_raw is not None:
            decision_eliminar = (
                str(decision_raw).strip().lower()
                in {"1", "true", "si", "sí", "yes"}
            )

        if (
            pasa_a_alta and
            total_citas_posteriores > 0 and
            decision_eliminar is None
        ):
            return Response(
                {
                    "detail": (
                        "El paciente tiene citas posteriores "
                        "a la fecha de alta."
                    ),
                    "requiere_confirmar_citas_posteriores": True,
                    "total_citas_posteriores": total_citas_posteriores,
                    "fecha_alta": fecha_alta.isoformat(),
                },
                status=status.HTTP_409_CONFLICT,
            )

        serializer = self.get_serializer(
            paciente,
            data=data,
            partial=partial,
        )
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            serializer.save()

            citas_eliminadas = 0

            if (
                pasa_a_alta and
                total_citas_posteriores > 0 and
                decision_eliminar is True
            ):
                citas_eliminadas = (
                    total_citas_posteriores
                )
                citas_posteriores.delete()

        response_data = dict(serializer.data)
        response_data[
            "citas_posteriores_eliminadas"
        ] = citas_eliminadas

        return Response(response_data)
    def get_serializer_class(self): return PacienteListadoSerializer if self.action == "list" else PacienteSerializer

    def perform_create(self, serializer):
        if serializer.validated_data.get("clinica"): serializer.save(); return
        clinica = getattr(getattr(self.request.user, "perfil", None), "clinica", None) or primera_clinica()
        if not clinica: raise ValueError("No existe clínica disponible para el usuario.")
        serializer.save(clinica=clinica)

    @action(detail=False, methods=["get"], url_path="resumen")
    def resumen(self, request):
        qs = self._base_queryset(); citas_qs = Cita.objects.filter(paciente__in=qs)
        if es_profesional(rol_usuario(request.user)): citas_qs = citas_qs.filter(profesional=request.user)
        return Response({"total": qs.count(), "en_tratamiento": qs.filter(estado_tratamiento="en_tratamiento").count(), "dados_alta": qs.filter(estado_tratamiento="alta").count(), "sesiones": citas_qs.count()})

    @action(detail=False, methods=["get"], url_path="cumpleanos")
    def cumpleanos(self, request):
        try: dias = max(0, min(int(request.query_params.get("dias", 5)), 31))
        except (TypeError, ValueError): dias = 5
        hoy = date.today(); fechas = [hoy + timedelta(days=i) for i in range(dias + 1)]; condicion = Q()
        for fecha in fechas: condicion |= Q(fecha_nac__month=fecha.month, fecha_nac__day=fecha.day)
        pacientes = list(self._base_queryset().select_related(None).filter(fecha_nac__isnull=False).filter(condicion).only("id", "uuid", "nombres", "apellido_pat", "apellido_mat", "fecha_nac", "foto"))
        pacientes.sort(key=lambda p: (dias_hasta_cumple(p.fecha_nac, hoy), p.apellido_pat, p.nombres)); data = []
        for paciente in pacientes:
            faltan = dias_hasta_cumple(paciente.fecha_nac, hoy)
            if faltan is None or faltan > dias: continue
            foto_url = request.build_absolute_uri(paciente.foto.url) if paciente.foto else None
            color = "verde" if faltan == 0 else "amarillo" if faltan <= 3 else "azul"
            data.append({"id": paciente.id, "uuid": str(paciente.uuid), "nombres": paciente.nombres, "apellido_pat": paciente.apellido_pat, "apellido_mat": paciente.apellido_mat, "fecha_nac": paciente.fecha_nac, "foto_url": foto_url, "dias_para_cumple": faltan, "color": color})
        return Response(data)

    @action(detail=True, methods=["get"], url_path="expediente")
    def expediente(self, request, pk=None):
        paciente = self.get_object(); citas = paciente.citas.select_related("servicio", "profesional").order_by("-fecha", "-hora_inicio", "-id")
        if es_profesional(rol_usuario(request.user)): citas = citas.filter(profesional=request.user)
        documentos = paciente.documentos.select_related("subido_por").all(); historial = paciente.registros_clinicos.select_related("profesional").all()
        return Response({"paciente": PacienteSerializer(paciente, context={"request": request}).data, "citas": CitaSerializer(citas, many=True, context={"request": request}).data, "documentos": DocumentoPacienteSerializer(documentos, many=True, context={"request": request}).data, "historial_clinico": RegistroClinicoSerializer(historial, many=True, context={"request": request}).data})

    @action(detail=True, methods=["post", "delete"], url_path="foto", parser_classes=[MultiPartParser, FormParser])
    def foto(self, request, pk=None):
        paciente = self.get_object()
        if request.method == "DELETE":
            if paciente.foto: paciente.foto.delete(save=False)
            paciente.foto = None; paciente.save(update_fields=["foto"])
            return Response(PacienteSerializer(paciente, context={"request": request}).data)
        archivo = request.FILES.get("foto")
        if not archivo: return Response({"foto": "Archivo requerido."}, status=400)
        if not (archivo.content_type or "").startswith("image/"): return Response({"foto": "Debe ser una imagen."}, status=400)
        if archivo.size > 5 * 1024 * 1024: return Response({"foto": "La imagen no puede superar 5 MB."}, status=400)
        if paciente.foto: paciente.foto.delete(save=False)
        paciente.foto = archivo; paciente.save(update_fields=["foto"])
        return Response(PacienteSerializer(paciente, context={"request": request}).data)

    @action(detail=True, methods=["get", "post"], url_path="documentos", parser_classes=[MultiPartParser, FormParser, JSONParser])
    def documentos(self, request, pk=None):
        paciente = self.get_object()
        if request.method == "GET": return Response(DocumentoPacienteSerializer(paciente.documentos.select_related("subido_por").all(), many=True, context={"request": request}).data)
        serializer = DocumentoPacienteSerializer(data=request.data, context={"request": request}); serializer.is_valid(raise_exception=True); archivo = serializer.validated_data["archivo"]
        obj = serializer.save(paciente=paciente, nombre_original=archivo.name, subido_por=request.user)
        return Response(DocumentoPacienteSerializer(obj, context={"request": request}).data, status=201)

    @action(detail=True, methods=["delete"], url_path=r"documentos/(?P<documento_id>\d+)")
    def eliminar_documento(self, request, pk=None, documento_id=None):
        paciente = self.get_object(); obj = paciente.documentos.filter(pk=documento_id).first()
        if not obj: return Response(status=404)
        if obj.archivo: obj.archivo.delete(save=False)
        obj.delete(); return Response(status=204)

    @action(detail=True, methods=["get", "post"], url_path="historial")
    def historial(self, request, pk=None):
        paciente = self.get_object()
        if request.method == "GET": return Response(RegistroClinicoSerializer(paciente.registros_clinicos.select_related("profesional").all(), many=True, context={"request": request}).data)
        serializer = RegistroClinicoSerializer(data=request.data, context={"request": request}); serializer.is_valid(raise_exception=True); obj = serializer.save(paciente=paciente, profesional=request.user)
        return Response(RegistroClinicoSerializer(obj, context={"request": request}).data, status=201)

    @action(detail=True, methods=["delete"], url_path=r"historial/(?P<registro_id>\d+)")
    def eliminar_historial(self, request, pk=None, registro_id=None):
        paciente = self.get_object(); obj = paciente.registros_clinicos.filter(pk=registro_id).first()
        if not obj: return Response(status=404)
        obj.delete(); return Response(status=204)

    def destroy(self, request, *args, **kwargs):
        paciente = self.get_object(); total_citas = paciente.citas.count(); eliminar_citas = str(request.query_params.get("eliminar_citas", "false")).lower() in {"1", "true", "si", "sí", "yes"}
        if total_citas and not eliminar_citas: return Response({"detail": "El paciente tiene citas asociadas.", "total_citas": total_citas, "requiere_eliminar_citas": True}, status=status.HTTP_409_CONFLICT)
        with transaction.atomic():
            for documento in paciente.documentos.all():
                if documento.archivo: documento.archivo.delete(save=False)
            if paciente.foto: paciente.foto.delete(save=False)
            paciente.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
