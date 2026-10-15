from datetime import date, datetime, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.db.models import Count, Sum, Max, Q
from django.utils.dateparse import parse_date
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from control_operativo.models import OrigenCita, OrigenPaciente
from control_operativo.servicios import guardar_bitacora, snapshot_cita, sincronizar_comisiones_cita

from core.models import (
    BloqueoHorario,
    Cita,
    MetaDiariaConsulta,
    Paciente,
    Pago,
    Servicio,
)
from core.serializers.agenda import (
    BloqueoHorarioSerializer,
    CitaCreateSerializer,
    CitaSerializer,
)
from core.utilidades import (
    buscar_paciente_publico_similar,
    calcular_hora_termina,
    clinica_usuario,
    es_admin,
    primera_clinica,
    profesional_publico_default,
    puede_modificar_dinero,
    puede_ver_dinero,
    puede_ver_todas_agendas,
    permisos_usuario,
    rol_usuario,
    se_superponen,
    validar_conflicto_cita,
)


DEFAULT_DAILY_GOAL = 60
CAMPOS_DINERO_CITA = {
    "precio",
    "pagado",
    "metodo_pago",
    "descuento_porcentaje",
    "anticipo",
    "monto_final",
}


def nombre_usuario(user):
    if not user:
        return ""
    return (user.get_full_name() or "").strip() or user.username


def nombre_paciente(paciente):
    if not paciente:
        return ""
    return (
        f"{paciente.nombres} {paciente.apellido_pat} "
        f"{paciente.apellido_mat or ''}"
    ).strip()


def dias_hasta_cumple(fecha_nacimiento, referencia):
    if not fecha_nacimiento:
        return None

    try:
        proximo = fecha_nacimiento.replace(year=referencia.year)
    except ValueError:
        proximo = date(referencia.year, 2, 28)

    if proximo < referencia:
        try:
            proximo = fecha_nacimiento.replace(year=referencia.year + 1)
        except ValueError:
            proximo = date(referencia.year + 1, 2, 28)

    return (proximo - referencia).days


class CitaViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def _rol(self):
        return rol_usuario(self.request.user)

    def _profesional_filtro(self):
        rol = self._rol()

        if not puede_ver_todas_agendas(rol):
            return self.request.user

        profesional_id = self.request.query_params.get("profesional")
        if not profesional_id:
            return None

        try:
            profesional_id = int(profesional_id)
        except (TypeError, ValueError):
            return None

        return User.objects.filter(
            id=profesional_id,
            staff_profile__isnull=False,
        ).first()

    def _scope_citas(self, *, incluir_filtro_fecha=False):
        qs = Cita.objects.select_related(
            "paciente",
            "servicio",
            "profesional",
        )

        profesional = self._profesional_filtro()
        if profesional:
            qs = qs.filter(profesional=profesional)

        if incluir_filtro_fecha:
            fecha = self.request.query_params.get("fecha")
            if fecha:
                qs = qs.filter(fecha=fecha)

        return qs

    def get_queryset(self):
        return self._scope_citas(incluir_filtro_fecha=True).order_by(
            "fecha",
            "hora_inicio",
            "id",
        )

    def get_serializer_class(self):
        if (
            self.action == "create"
            and isinstance(self.request.data.get("paciente"), dict)
        ):
            return CitaCreateSerializer
        return CitaSerializer

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["clinica"] = clinica_usuario(self.request.user) or primera_clinica()
        return ctx

    def _resolver_profesional_guardado(self, instance=None):
        data = self.request.data
        rol = self._rol()
        profesional_payload = data.get("profesional")

        if puede_ver_todas_agendas(rol):
            if profesional_payload:
                try:
                    profesional_id = int(profesional_payload)
                except (TypeError, ValueError):
                    raise ValidationError({"profesional": "Profesional inválido."})

                if instance is not None and profesional_id == instance.profesional_id:
                    return instance.profesional

                profesional = User.objects.filter(
                    id=profesional_id,
                    is_active=True,
                    staff_profile__isnull=False,
                ).first()

                if not profesional:
                    raise ValidationError({"profesional": "El profesional está inactivo o no existe."})

                return profesional

            if instance is not None:
                return instance.profesional

        return self.request.user

    def _valores_financieros_servidor(self, servicio, instance=None):
        """
        Si el rol no puede ver dinero, tampoco puede modificarlo.

        En creación se usa el precio del servicio.
        En edición se conservan exactamente los valores actuales.
        """
        if puede_modificar_dinero(self.request.user):
            return {}

        if instance is not None:
            return {
                "precio": instance.precio,
                "pagado": instance.pagado,
                "metodo_pago": instance.metodo_pago,
                "descuento_porcentaje": instance.descuento_porcentaje,
                "anticipo": instance.anticipo,
                "monto_final": instance.monto_final,
            }

        precio = Decimal(servicio.precio or 0) if servicio else Decimal("0")
        return {
            "precio": precio,
            "pagado": False,
            "metodo_pago": "",
            "descuento_porcentaje": Decimal("0"),
            "anticipo": Decimal("0"),
            "monto_final": precio,
        }

    def perform_create(self, serializer):
        data = self.request.data
        servicio_id = data.get("servicio") or data.get("servicio_id")
        servicio = Servicio.objects.filter(id=servicio_id).first()

        if not servicio:
            raise ValidationError({"servicio": "Servicio inválido."})

        profesional = self._resolver_profesional_guardado()
        kwargs = {
            "profesional": profesional,
            **self._valores_financieros_servidor(servicio),
        }

        paciente_payload = data.get('paciente')
        paciente_nuevo = isinstance(paciente_payload, dict) and not any((
            paciente_payload.get('id'), paciente_payload.get('uuid'),
            data.get('paciente_id'), data.get('paciente_uuid'),
        ))
        cita = serializer.save(**kwargs)
        OrigenCita.objects.update_or_create(cita=cita, defaults={'agendada_por': self.request.user, 'rol_al_agendar': rol_usuario(self.request.user) or ''})
        if paciente_nuevo and rol_usuario(self.request.user) == 'recepcion':
            OrigenPaciente.objects.get_or_create(
                paciente=cita.paciente,
                defaults={'registrado_por': self.request.user,
                          'origen': data.get('origen', 'nuevo') if data.get('origen') in ('nuevo', 'recomendado', 'otro') else 'nuevo',
                          'rol_registro': 'recepcion'},
            )
        sincronizar_comisiones_cita(cita)
        guardar_bitacora(usuario=self.request.user, tipo='cita', objeto_id=cita.pk,
                         accion='crear', nuevo=snapshot_cita(cita))

    def perform_update(self, serializer):
        instance = serializer.instance
        profesional = self._resolver_profesional_guardado(instance=instance)
        kwargs = {
            "profesional": profesional,
            **self._valores_financieros_servidor(
                getattr(instance, "servicio", None),
                instance=instance,
            ),
        }
        anterior = snapshot_cita(instance)
        cita = serializer.save(**kwargs)
        despues = snapshot_cita(cita)
        if anterior != despues:
            guardar_bitacora(usuario=self.request.user, tipo='cita', objeto_id=cita.pk,
                             accion='editar', anterior=anterior, nuevo=despues)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        data = request.data.copy()

        if not puede_modificar_dinero(request.user):
            for field in CAMPOS_DINERO_CITA:
                data.pop(field, None)

        serializer = self.get_serializer(
            instance,
            data=data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        if not es_admin(request.user):
            return Response({'detail': 'Solo administración puede eliminar definitivamente citas. Usa cancelación si corresponde.'}, status=403)
        instance = self.get_object()
        if instance.pagos.exists():
            return Response({'detail': 'No puedes eliminar una cita con pagos. Cancélala para conservar el historial.'}, status=409)
        anterior = snapshot_cita(instance)
        guardar_bitacora(usuario=request.user, tipo='cita', objeto_id=instance.pk,
                         accion='eliminar', anterior=anterior)
        self.perform_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _meta_payload(self, profesional=None):
        clinica = clinica_usuario(self.request.user) or primera_clinica()
        if not clinica:
            return {
                "meta_general": DEFAULT_DAILY_GOAL,
                "meta_personal": None,
                "meta_efectiva": DEFAULT_DAILY_GOAL,
                "profesional": None,
            }

        general = MetaDiariaConsulta.objects.filter(
            clinica=clinica,
            profesional__isnull=True,
        ).first()

        if not general:
            general = MetaDiariaConsulta.objects.create(
                clinica=clinica,
                profesional=None,
                cantidad=DEFAULT_DAILY_GOAL,
            )

        personal = None
        if profesional:
            personal = MetaDiariaConsulta.objects.filter(
                clinica=clinica,
                profesional=profesional,
            ).first()

        return {
            "meta_general": general.cantidad,
            "meta_personal": personal.cantidad if personal else None,
            "meta_efectiva": personal.cantidad if personal else general.cantidad,
            "profesional": (
                {
                    "id": profesional.id,
                    "nombre": nombre_usuario(profesional),
                }
                if profesional
                else None
            ),
        }

    @action(
        detail=False,
        methods=["get", "put"],
        url_path="meta-diaria",
        permission_classes=[IsAuthenticated],
    )
    def meta_diaria(self, request):
        rol = rol_usuario(request.user)
        clinica = clinica_usuario(request.user) or primera_clinica()

        if not clinica:
            return Response(
                {"detail": "No existe clínica configurada."},
                status=400,
            )

        profesional = self._profesional_filtro()

        if request.method == "PUT":
            if not es_admin(request.user):
                return Response(
                    {"detail": "Solo el administrador puede modificar metas."},
                    status=403,
                )

            try:
                cantidad = int(request.data.get("cantidad"))
            except (TypeError, ValueError):
                return Response(
                    {"cantidad": "Escribe una cantidad válida."},
                    status=400,
                )

            if cantidad < 1 or cantidad > 1000:
                return Response(
                    {"cantidad": "La meta debe estar entre 1 y 1000."},
                    status=400,
                )

            profesional_id = request.data.get("profesional")
            target = None

            if profesional_id not in (None, "", 0, "0"):
                try:
                    target_id = int(profesional_id)
                except (TypeError, ValueError):
                    return Response(
                        {"profesional": "Profesional inválido."},
                        status=400,
                    )

                target = User.objects.filter(
                    id=target_id,
                    is_active=True,
                    staff_profile__isnull=False,
                ).first()

                if not target:
                    return Response(
                        {"profesional": "Profesional inválido."},
                        status=400,
                    )

            MetaDiariaConsulta.objects.update_or_create(
                clinica=clinica,
                profesional=target,
                defaults={"cantidad": cantidad},
            )

            profesional = target

        return Response(self._meta_payload(profesional))

    @action(
        detail=False,
        methods=["get"],
        url_path="panel",
        permission_classes=[IsAuthenticated],
    )
    def panel(self, request):
        referencia = parse_date(request.query_params.get("fecha") or "") or date.today()
        rol = rol_usuario(request.user)
        profesional = self._profesional_filtro()

        citas_dia = Cita.objects.select_related(
            "paciente",
            "servicio",
            "profesional",
        ).filter(fecha=referencia)

        scope_historico = Cita.objects.select_related(
            "paciente",
            "servicio",
            "profesional",
        )

        if profesional:
            citas_dia = citas_dia.filter(profesional=profesional)
            scope_historico = scope_historico.filter(profesional=profesional)
        elif not puede_ver_todas_agendas(rol):
            citas_dia = citas_dia.filter(profesional=request.user)
            scope_historico = scope_historico.filter(profesional=request.user)

        total = citas_dia.count()
        atendidas = citas_dia.filter(estado="completado").count()
        canceladas = citas_dia.filter(estado="cancelado").count()
        pendientes = citas_dia.exclude(
            estado__in=["completado", "cancelado"]
        ).count()

        no_asistencias = (
            scope_historico.filter(estado="cancelado")
            .values(
                "paciente_id",
                "paciente__nombres",
                "paciente__apellido_pat",
                "paciente__apellido_mat",
            )
            .annotate(total=Count("id"))
            .filter(total__gt=2)
            .order_by("-total", "paciente__apellido_pat")[:20]
        )

        # Pacientes activos que llevan más de tres días desde su última cita completada.
        clinica_alertas = clinica_usuario(request.user) or primera_clinica()
        pacientes_inactivos_qs = Paciente.objects.filter(estado_tratamiento='en_tratamiento')
        if clinica_alertas:
            pacientes_inactivos_qs = pacientes_inactivos_qs.filter(clinica=clinica_alertas)
        if profesional:
            pacientes_inactivos_qs = pacientes_inactivos_qs.filter(citas__profesional=profesional)
        elif not puede_ver_todas_agendas(rol):
            pacientes_inactivos_qs = pacientes_inactivos_qs.filter(citas__profesional=request.user)
        limite_inactividad = referencia - timedelta(days=3)
        pacientes_inactivos_qs = (pacientes_inactivos_qs
            .annotate(ultima_visita=Max('citas__fecha', filter=Q(citas__estado='completado')))
            .filter(ultima_visita__lt=limite_inactividad).order_by('ultima_visita')[:20])
        alertas_inactividad = [
            {'paciente_id': p.id, 'paciente': nombre_paciente(p),
             'ultima_visita': p.ultima_visita, 'dias_sin_venir': (referencia - p.ultima_visita).days}
            for p in pacientes_inactivos_qs
        ]

        alertas_no_asistencia = [
            {
                "paciente_id": row["paciente_id"],
                "paciente": (
                    f"{row['paciente__nombres']} "
                    f"{row['paciente__apellido_pat']} "
                    f"{row['paciente__apellido_mat'] or ''}"
                ).strip(),
                "total_no_asistencias": row["total"],
            }
            for row in no_asistencias
        ]

        pendientes_cobro_qs = (
            scope_historico.filter(
                pagado=False,
                fecha__lte=referencia,
            )
            .exclude(estado="cancelado")
            .order_by("fecha", "hora_inicio")[:30]
        )

        alertas_cobro = [
            {
                "cita_id": cita.id,
                "paciente_id": cita.paciente_id,
                "paciente": nombre_paciente(cita.paciente),
                "fecha": cita.fecha,
                "hora": cita.hora_inicio,
                "servicio": cita.servicio.nombre,
                "profesional_id": cita.profesional_id,
                "profesional": nombre_usuario(cita.profesional),
            }
            for cita in pendientes_cobro_qs
        ]

        clinica = clinica_usuario(request.user) or primera_clinica()
        pacientes = Paciente.objects.filter(fecha_nac__isnull=False)

        if clinica:
            pacientes = pacientes.filter(clinica=clinica)

        if profesional:
            pacientes = pacientes.filter(
                citas__profesional=profesional
            ).distinct()
        elif not puede_ver_todas_agendas(rol):
            pacientes = pacientes.filter(
                citas__profesional=request.user
            ).distinct()

        cumpleanos = []
        for paciente in pacientes.only(
            "id",
            "nombres",
            "apellido_pat",
            "apellido_mat",
            "fecha_nac",
        ):
            dias = dias_hasta_cumple(paciente.fecha_nac, referencia)
            if dias is None or dias > 5:
                continue

            cumpleanos.append(
                {
                    "paciente_id": paciente.id,
                    "paciente": nombre_paciente(paciente),
                    "fecha_nac": paciente.fecha_nac,
                    "dias_para_cumple": dias,
                }
            )

        cumpleanos.sort(
            key=lambda item: (
                item["dias_para_cumple"],
                item["paciente"],
            )
        )
        cumpleanos = cumpleanos[:30]

        finanzas = None
        if puede_ver_dinero(request.user):
            pagos = Pago.objects.select_related(
                "cita",
                "cita__profesional",
            ).filter(fecha_pago=referencia)

            if profesional:
                pagos = pagos.filter(cita__profesional=profesional)
            elif not puede_ver_todas_agendas(rol):
                pagos = pagos.filter(cita__profesional=request.user)

            cobrado = pagos.aggregate(total=Sum("anticipo")).get("total") or Decimal("0")
            finanzas = {
                "fecha_corte": referencia,
                "ingreso_cobrado": cobrado,
                "ingreso_esperado": cobrado,
                "pagos_registrados": pagos.count(),
                "criterio_fecha": "fecha_pago",
            }

        meta = self._meta_payload(profesional)
        meta_efectiva = max(1, int(meta["meta_efectiva"] or DEFAULT_DAILY_GOAL))

        return Response(
            {
                "fecha": referencia,
                "rol": rol,
                "puede_ver_dinero": puede_ver_dinero(request.user),
                "permisos": permisos_usuario(request.user),
                "profesional": (
                    {
                        "id": profesional.id,
                        "nombre": nombre_usuario(profesional),
                    }
                    if profesional
                    else None
                ),
                "metricas": {
                    "agendadas": total,
                    "atendidas": atendidas,
                    "pendientes": pendientes,
                    "canceladas": canceladas,
                    "porcentaje_meta": min(
                        100,
                        round(total * 100 / meta_efectiva),
                    ),
                },
                "meta_diaria": meta,
                "finanzas": finanzas,
                "alertas": {
                    "no_asistencias": alertas_no_asistencia,
                    "inactivos": alertas_inactividad,
                    "cumpleanos": cumpleanos,
                    "cobros_pendientes": alertas_cobro,
                },
            }
        )


class BloqueoHorarioViewSet(viewsets.ModelViewSet):
    queryset = BloqueoHorario.objects.select_related("profesional").all()
    serializer_class = BloqueoHorarioSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        rol = rol_usuario(self.request.user)
        qs = super().get_queryset()

        if not puede_ver_todas_agendas(rol):
            qs = qs.filter(profesional=self.request.user)
        else:
            profesional = self.request.query_params.get("profesional")
            if profesional:
                qs = qs.filter(profesional_id=profesional)

        fecha = self.request.query_params.get("fecha")
        if fecha:
            qs = qs.filter(fecha=fecha)

        return qs

    def perform_create(self, serializer):
        rol = rol_usuario(self.request.user)
        profesional = self.request.user

        if puede_ver_todas_agendas(rol):
            profesional_id = self.request.data.get("profesional")
            if profesional_id:
                profesional = User.objects.filter(
                    id=profesional_id,
                    is_active=True,
                    staff_profile__isnull=False,
                ).first()
                if not profesional:
                    raise ValidationError(
                        {"profesional": "Profesional inválido."}
                    )

        bloqueo = serializer.save(profesional=profesional)
        guardar_bitacora(usuario=self.request.user, tipo='bloqueo', objeto_id=bloqueo.pk,
                         accion='crear', nuevo={'fecha': str(bloqueo.fecha), 'inicio': str(bloqueo.hora_inicio),
                                                'fin': str(bloqueo.hora_termina), 'profesional_id': bloqueo.profesional_id})

    def perform_update(self, serializer):
        rol = rol_usuario(self.request.user)

        if puede_ver_todas_agendas(rol):
            profesional_id = self.request.data.get("profesional")
            if profesional_id:
                profesional = User.objects.filter(
                    id=profesional_id,
                    is_active=True,
                    staff_profile__isnull=False,
                ).first()
                if not profesional:
                    raise ValidationError(
                        {"profesional": "Profesional inválido."}
                    )
                anterior = {'fecha': str(serializer.instance.fecha), 'inicio': str(serializer.instance.hora_inicio),
                            'fin': str(serializer.instance.hora_termina)}
                bloqueo = serializer.save(profesional=profesional)
                guardar_bitacora(usuario=self.request.user, tipo='bloqueo', objeto_id=bloqueo.id,
                    accion='editar', anterior=anterior, nuevo={'fecha': str(bloqueo.fecha), 'inicio': str(bloqueo.hora_inicio), 'fin': str(bloqueo.hora_termina)})
                return

            bloqueo = serializer.save()
        else:
            bloqueo = serializer.save(profesional=self.request.user)
        guardar_bitacora(usuario=self.request.user, tipo='bloqueo', objeto_id=bloqueo.pk,
            accion='editar', nuevo={'fecha': str(bloqueo.fecha), 'inicio': str(bloqueo.hora_inicio), 'fin': str(bloqueo.hora_termina)})

    def perform_destroy(self, instance):
        guardar_bitacora(usuario=self.request.user, tipo='bloqueo', objeto_id=instance.pk,
            accion='eliminar', anterior={'fecha': str(instance.fecha), 'inicio': str(instance.hora_inicio), 'fin': str(instance.hora_termina)})
        instance.delete()


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def public_agenda(request):
    fecha = request.query_params.get("fecha")
    if not fecha:
        return Response({"detail": "fecha requerida"}, status=400)

    clinica = primera_clinica()
    if not clinica:
        return Response(
            {"detail": "No existe clínica configurada."},
            status=400,
        )

    profesional = profesional_publico_default(clinica)
    if not profesional:
        return Response(
            {"detail": "No hay profesional configurado."},
            status=400,
        )

    citas = (
        Cita.objects.filter(
            fecha=fecha,
            profesional=profesional,
        )
        .exclude(estado="cancelado")
        .only("hora_inicio", "hora_termina")
    )

    bloqueos = BloqueoHorario.objects.filter(
        fecha=fecha,
        profesional=profesional,
    ).only("hora_inicio", "hora_termina")

    data = [
        {
            "hora_inicio": cita.hora_inicio.strftime("%H:%M:%S"),
            "hora_termina": cita.hora_termina.strftime("%H:%M:%S"),
            "kind": "cita",
        }
        for cita in citas
    ]

    data += [
        {
            "hora_inicio": bloqueo.hora_inicio.strftime("%H:%M:%S"),
            "hora_termina": bloqueo.hora_termina.strftime("%H:%M:%S"),
            "kind": "bloqueo",
        }
        for bloqueo in bloqueos
    ]

    return Response(data)


@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def public_create_cita(request):
    clinica = primera_clinica()
    if not clinica:
        return Response(
            {"detail": "No existe clínica configurada."},
            status=400,
        )

    nombre = (request.data.get("nombre") or "").strip()
    telefono = (request.data.get("telefono") or "").strip()
    servicio_id = request.data.get("servicio_id")
    fecha = request.data.get("fecha")
    hora_inicio = request.data.get("hora_inicio")

    if not (nombre and telefono and servicio_id and fecha and hora_inicio):
        return Response(
            {"detail": "Faltan campos requeridos."},
            status=400,
        )

    servicio = Servicio.objects.filter(
        id=servicio_id,
        activo=True,
    ).first()

    if not servicio:
        return Response({"detail": "Servicio inválido."}, status=400)

    hora_inicio_full = (
        f"{hora_inicio}:00"
        if len(hora_inicio) == 5
        else hora_inicio
    )

    paciente = buscar_paciente_publico_similar(
        clinica=clinica,
        nombre=nombre,
        telefono=telefono,
    )

    if not paciente:
        paciente = Paciente.objects.create(
            clinica=clinica,
            nombres=nombre,
            apellido_pat="",
            apellido_mat="",
            fecha_nac=None,
            genero="",
            telefono=telefono,
            correo="",
            molestia="",
            notas="",
        )

    profesional = profesional_publico_default(clinica)
    if not profesional:
        return Response(
            {"detail": "No hay profesional configurado."},
            status=400,
        )

    hora_termina = calcular_hora_termina(
        fecha,
        hora_inicio_full,
        servicio.duracion,
    ).strftime("%H:%M:%S")

    hi = datetime.strptime(hora_inicio_full, "%H:%M:%S").time()
    ht = datetime.strptime(hora_termina, "%H:%M:%S").time()

    if validar_conflicto_cita(
        profesional_id=profesional.id,
        fecha=fecha,
        hora_inicio=hi,
        hora_termina=ht,
    ):
        return Response(
            {"detail": "Horario ya ocupado."},
            status=409,
        )

    for bloqueo in BloqueoHorario.objects.filter(
        fecha=fecha,
        profesional=profesional,
    ).only("hora_inicio", "hora_termina"):
        if se_superponen(
            hi,
            ht,
            bloqueo.hora_inicio,
            bloqueo.hora_termina,
        ):
            return Response(
                {"detail": "Horario no disponible."},
                status=409,
            )

    cita = Cita.objects.create(
        paciente=paciente,
        servicio=servicio,
        profesional=profesional,
        fecha=fecha,
        hora_inicio=hi,
        hora_termina=ht,
        precio=servicio.precio,
        monto_final=servicio.precio,
        estado="reservado",
        pagado=False,
    )

    guardar_bitacora(usuario=None, tipo='cita', objeto_id=cita.pk,
                     accion='crear_publica', nuevo=snapshot_cita(cita))
    return Response(CitaSerializer(cita).data, status=201)


