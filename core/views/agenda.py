from datetime import datetime
from django.contrib.auth.models import User
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from core.models import BloqueoHorario, Cita, Paciente, Servicio
from core.serializers.agenda import BloqueoHorarioSerializer, CitaCreateSerializer, CitaSerializer
from core.utilidades import buscar_paciente_publico_similar, calcular_hora_termina, es_profesional, primera_clinica, profesional_publico_default, puede_ver_todas_agendas, rol_usuario, se_superponen, validar_conflicto_cita


class CitaViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        rol = rol_usuario(self.request.user); qs = Cita.objects.select_related("paciente", "servicio", "profesional").order_by("fecha", "hora_inicio")
        if es_profesional(rol): qs = qs.filter(profesional=self.request.user)
        return qs

    def get_serializer_class(self):
        if self.action == "create" and isinstance(self.request.data.get("paciente"), dict): return CitaCreateSerializer
        return CitaSerializer

    def get_serializer_context(self):
        ctx = super().get_serializer_context(); ctx["clinica"] = primera_clinica(); return ctx

    def perform_create(self, serializer):
        data = self.request.data; rol = rol_usuario(self.request.user); servicio_id = data.get("servicio") or data.get("servicio_id"); servicio = Servicio.objects.filter(id=servicio_id).first()
        fecha = data.get("fecha"); hora_inicio = data.get("hora_inicio"); hora_termina = data.get("hora_termina")
        if hora_inicio and len(hora_inicio) == 5: hora_inicio = f"{hora_inicio}:00"
        if hora_termina and len(hora_termina) == 5: hora_termina = f"{hora_termina}:00"
        if not hora_termina and servicio and fecha and hora_inicio: hora_termina = calcular_hora_termina(fecha, hora_inicio, servicio.duracion).strftime("%H:%M:%S")
        profesional_payload = data.get("profesional"); profesional_id = int(profesional_payload) if puede_ver_todas_agendas(rol) and profesional_payload else self.request.user.id
        profesional = User.objects.filter(id=profesional_id).first()
        if not profesional: raise ValidationError({"profesional": "Profesional inválido."})
        serializer.save(profesional=profesional)

    def perform_update(self, serializer):
        data = self.request.data; rol = rol_usuario(self.request.user); profesional_payload = data.get("profesional")
        if puede_ver_todas_agendas(rol) and profesional_payload:
            profesional = User.objects.filter(id=int(profesional_payload)).first()
            if not profesional: raise ValidationError({"profesional": "Profesional inválido."})
            serializer.save(profesional=profesional); return
        serializer.save()

    def update(self, request, *args, **kwargs):
        instance = self.get_object(); serializer = self.get_serializer(instance, data=request.data, partial=True); serializer.is_valid(raise_exception=True)
        try: self.perform_update(serializer)
        except Exception as exc: return Response({"detail": str(exc)}, status=400)
        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        try: self.perform_destroy(instance)
        except Exception as exc: print("[CITAS] Error al eliminar cita:", repr(exc))
        return Response(status=status.HTTP_204_NO_CONTENT)


class BloqueoHorarioViewSet(viewsets.ModelViewSet):
    queryset = BloqueoHorario.objects.select_related("profesional").all(); serializer_class = BloqueoHorarioSerializer; permission_classes = [IsAuthenticated]

    def get_queryset(self):
        rol = rol_usuario(self.request.user); qs = super().get_queryset()
        if es_profesional(rol): qs = qs.filter(profesional=self.request.user)
        return qs


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def public_agenda(request):
    fecha = request.query_params.get("fecha")
    if not fecha: return Response({"detail": "fecha requerida"}, status=400)
    clinica = primera_clinica()
    if not clinica: return Response({"detail": "No existe clínica configurada."}, status=400)
    profesional = profesional_publico_default(clinica)
    if not profesional: return Response({"detail": "No hay profesional configurado."}, status=400)
    citas = Cita.objects.filter(fecha=fecha, profesional=profesional).exclude(estado="cancelado").only("hora_inicio", "hora_termina")
    bloqueos = BloqueoHorario.objects.filter(fecha=fecha, profesional=profesional).only("hora_inicio", "hora_termina")
    data = [{"hora_inicio": c.hora_inicio.strftime("%H:%M:%S"), "hora_termina": c.hora_termina.strftime("%H:%M:%S"), "kind": "cita"} for c in citas]
    data += [{"hora_inicio": b.hora_inicio.strftime("%H:%M:%S"), "hora_termina": b.hora_termina.strftime("%H:%M:%S"), "kind": "bloqueo"} for b in bloqueos]
    return Response(data)


@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def public_create_cita(request):
    clinica = primera_clinica()
    if not clinica: return Response({"detail": "No existe clínica configurada."}, status=400)
    nombre = (request.data.get("nombre") or "").strip(); telefono = (request.data.get("telefono") or "").strip(); servicio_id = request.data.get("servicio_id"); fecha = request.data.get("fecha"); hora_inicio = request.data.get("hora_inicio")
    if not (nombre and telefono and servicio_id and fecha and hora_inicio): return Response({"detail": "Faltan campos requeridos."}, status=400)
    servicio = Servicio.objects.filter(id=servicio_id, activo=True).first()
    if not servicio: return Response({"detail": "Servicio inválido."}, status=400)
    hora_inicio_full = f"{hora_inicio}:00" if len(hora_inicio) == 5 else hora_inicio
    paciente = buscar_paciente_publico_similar(clinica=clinica, nombre=nombre, telefono=telefono)
    if not paciente: paciente = Paciente.objects.create(clinica=clinica, nombres=nombre, apellido_pat="", apellido_mat="", fecha_nac=None, genero="", telefono=telefono, correo="", molestia="", notas="")
    profesional = profesional_publico_default(clinica)
    if not profesional: return Response({"detail": "No hay profesional configurado."}, status=400)
    hora_termina = calcular_hora_termina(fecha, hora_inicio_full, servicio.duracion).strftime("%H:%M:%S"); hi = datetime.strptime(hora_inicio_full, "%H:%M:%S").time(); ht = datetime.strptime(hora_termina, "%H:%M:%S").time()
    if validar_conflicto_cita(profesional_id=profesional.id, fecha=fecha, hora_inicio=hi, hora_termina=ht): return Response({"detail": "Horario ya ocupado."}, status=409)
    for bloqueo in BloqueoHorario.objects.filter(fecha=fecha, profesional=profesional).only("hora_inicio", "hora_termina"):
        if se_superponen(hi, ht, bloqueo.hora_inicio, bloqueo.hora_termina): return Response({"detail": "Horario no disponible."}, status=409)
    cita = Cita.objects.create(paciente=paciente, servicio=servicio, profesional=profesional, fecha=fecha, hora_inicio=hi, hora_termina=ht, precio=servicio.precio, estado="reservado", pagado=False)
    return Response(CitaSerializer(cita).data, status=201)
