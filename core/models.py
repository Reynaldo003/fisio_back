import uuid
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.db import models


def ruta_documento_paciente(instance, filename):
    ext = Path(filename).suffix.lower()
    nombre = Path(filename).stem[:80]
    return f"pacientes/documentos/{instance.paciente.uuid}/{nombre}{ext}"


class StaffProfile(models.Model):
    ROLE_CHOICES = [
        ("fisioterapeuta", "Fisioterapeuta"),
        ("nutriologo", "Nutriólogo"),
        ("dentista", "Dentista"),
        ("recepcion", "Recepción"),
        ("terapeuta", "Terapeuta"),
        ("practicante", "Practicante"),
        ("personalizado", "Rol personalizado"),
        ("admin", "Administrador"),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="staff_profile")
    rol = models.CharField(max_length=20, choices=ROLE_CHOICES, default="fisioterapeuta")
    telefono = models.CharField(max_length=30, blank=True, default="")
    descripcion = models.TextField(blank=True, default="")
    foto = models.ImageField(upload_to="staff/", blank=True, null=True)
    rol_personalizado = models.ForeignKey(
        "RolPersonalizado", on_delete=models.SET_NULL, related_name="usuarios", null=True, blank=True
    )
    usar_interfaces_override = models.BooleanField(default=False)
    interfaces_override = models.JSONField(default=list, blank=True)
    creado = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} ({self.rol})"


class Clinica(models.Model):
    nombre = models.CharField(max_length=100)
    direccion = models.CharField(max_length=255)
    propietario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="clinicas",
    )

    def __str__(self):
        return self.nombre


class PerfilUsuario(models.Model):
    ROLES = [
        ("admin", "Administrador"),
        ("colaborador", "Colaborador"),
        ("recepcion", "Recepcionista"),
    ]
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="perfil",
    )
    clinica = models.ForeignKey(
        Clinica,
        on_delete=models.CASCADE,
        related_name="perfiles",
        null=True,
        blank=True,
    )
    rol = models.CharField(max_length=20, choices=ROLES, default="colaborador")
    titulo = models.CharField(max_length=30, blank=True)
    telefono = models.CharField(max_length=20, blank=True)
    foto = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"{self.user.username} ({self.rol})"


class HorarioDisponible(models.Model):
    DIA_SEMANA = [
        (0, "Lunes"),
        (1, "Martes"),
        (2, "Miércoles"),
        (3, "Jueves"),
        (4, "Viernes"),
        (5, "Sábado"),
        (6, "Domingo"),
    ]
    clinica = models.ForeignKey(Clinica, on_delete=models.CASCADE, related_name="horarios")
    dia = models.PositiveSmallIntegerField(choices=DIA_SEMANA)
    hora_apertura = models.TimeField()
    hora_cierre = models.TimeField()

    class Meta:
        unique_together = ("clinica", "dia")

    def __str__(self):
        return f"{self.get_dia_display()} {self.hora_apertura}-{self.hora_cierre}"


class Servicio(models.Model):
    clinica = models.ForeignKey(Clinica, on_delete=models.CASCADE, related_name="servicios")
    nombre = models.CharField(max_length=100)
    descripcion = models.CharField(max_length=150)
    duracion = models.DurationField()
    precio = models.DecimalField(max_digits=8, decimal_places=2)
    activo = models.BooleanField(default=True)
    imagen = models.ImageField(upload_to="servicios/", blank=True, null=True)

    def __str__(self):
        return f"{self.nombre} ({self.clinica.nombre})"


class Paciente(models.Model):
    ESTADO_TRATAMIENTO = [
        ("en_tratamiento", "En tratamiento"),
        ("alta", "Dado de alta"),
    ]
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)
    clinica = models.ForeignKey(Clinica, on_delete=models.CASCADE, related_name="pacientes")
    nombres = models.CharField(max_length=70)
    apellido_pat = models.CharField(max_length=40)
    apellido_mat = models.CharField(max_length=40, blank=True)
    fecha_nac = models.DateField(null=True, blank=True)
    genero = models.CharField(max_length=30, blank=True)
    telefono = models.CharField(max_length=20, blank=True, default="")
    correo = models.EmailField(max_length=100, blank=True)
    molestia = models.CharField(max_length=100, blank=True)
    notas = models.CharField(max_length=200, blank=True)
    foto = models.ImageField(upload_to="pacientes/fotos/%Y/%m/", blank=True, null=True)
    registro = models.DateField(auto_now_add=True)
    estado_tratamiento = models.CharField(
        max_length=20,
        choices=ESTADO_TRATAMIENTO,
        default="en_tratamiento",
    )
    fecha_alta = models.DateField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["clinica", "telefono"]),
            models.Index(fields=["clinica", "apellido_pat", "apellido_mat"]),
            models.Index(fields=["clinica", "nombres"]),
            models.Index(fields=["clinica", "fecha_nac"]),
            models.Index(fields=["clinica", "registro"]),
        ]
        ordering = ["-id"]

    def __str__(self):
        return f"{self.nombres} {self.apellido_pat}".strip()


class DocumentoPaciente(models.Model):
    TIPOS = [
        ("historia_clinica", "Historia clínica"),
        ("estudio", "Estudio"),
        ("consentimiento", "Consentimiento"),
        ("receta", "Receta"),
        ("otro", "Otro"),
    ]
    paciente = models.ForeignKey(Paciente, on_delete=models.CASCADE, related_name="documentos")
    archivo = models.FileField(upload_to=ruta_documento_paciente)
    nombre_original = models.CharField(max_length=255)
    tipo = models.CharField(max_length=30, choices=TIPOS, default="otro")
    descripcion = models.CharField(max_length=255, blank=True, default="")
    subido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documentos_pacientes_subidos",
    )
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creado", "-id"]
        indexes = [
            models.Index(fields=["paciente", "creado"]),
            models.Index(fields=["paciente", "tipo"]),
        ]

    def __str__(self):
        return self.nombre_original


class RegistroClinico(models.Model):
    paciente = models.ForeignKey(
        Paciente,
        on_delete=models.CASCADE,
        related_name="registros_clinicos",
    )
    fecha = models.DateField()
    titulo = models.CharField(max_length=120)
    descripcion = models.TextField()
    profesional = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="registros_clinicos_realizados",
    )
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-fecha", "-creado", "-id"]
        indexes = [models.Index(fields=["paciente", "fecha"])]

    def __str__(self):
        return f"{self.paciente} - {self.fecha} - {self.titulo}"


class Comentario(models.Model):
    clinica = models.ForeignKey(Clinica, on_delete=models.CASCADE, related_name="comentarios")
    descripcion = models.TextField()
    calificacion = models.IntegerField()
    aprobado = models.BooleanField(default=False)
    nombre_completo = models.CharField(max_length=100)
    creado = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.nombre_completo} ({self.calificacion})"


class Cita(models.Model):
    ESTADOS = [
        ("reservado", "Reservado"),
        ("confirmado", "Confirmado"),
        ("completado", "Completado"),
        ("cancelado", "Cancelado"),
    ]
    METODOS_PAGO = [
        ("efectivo", "Efectivo"),
        ("tarjeta", "Tarjeta"),
        ("transferencia", "Transferencia"),
        ("otro", "Otro"),
    ]
    paciente = models.ForeignKey(Paciente, on_delete=models.CASCADE, related_name="citas")
    servicio = models.ForeignKey(Servicio, on_delete=models.PROTECT, related_name="citas")
    profesional = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="citas_atendidas",
    )
    fecha = models.DateField()
    hora_inicio = models.TimeField()
    hora_termina = models.TimeField()
    precio = models.DecimalField(max_digits=8, decimal_places=2)
    pagado = models.BooleanField(default=False)
    metodo_pago = models.CharField(max_length=20, choices=METODOS_PAGO, blank=True)
    descuento_porcentaje = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    anticipo = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=0,
        help_text="Suma de todos los abonos registrados.",
    )
    monto_final = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=0,
        help_text="Total de la cita después de descuentos.",
    )
    estado = models.CharField(max_length=20, choices=ESTADOS, default="reservado")
    notas = models.CharField(max_length=200, blank=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-fecha", "-hora_inicio"]
        indexes = [
            models.Index(fields=["paciente", "fecha", "hora_inicio"]),
            models.Index(fields=["profesional", "fecha"]),
            models.Index(fields=["servicio", "fecha"]),
        ]

    def __str__(self):
        return f"{self.paciente} - {self.fecha} {self.hora_inicio}"


class Pago(models.Model):
    cita = models.ForeignKey(Cita, on_delete=models.CASCADE, related_name="pagos")
    fecha_pago = models.DateField()
    comprobante = models.CharField(max_length=100, blank=True)
    monto_facturado = models.DecimalField(max_digits=8, decimal_places=2)
    metodo_pago = models.CharField(max_length=20, choices=Cita.METODOS_PAGO)
    descuento_porcentaje = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    anticipo = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    restante = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fecha_pago", "-id"]
        indexes = [
            models.Index(fields=["cita", "fecha_pago"]),
            models.Index(fields=["fecha_pago"]),
        ]

    def __str__(self):
        return f"Pago #{self.id} - Cita {self.cita_id}"


class BloqueoHorario(models.Model):
    profesional = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="bloqueos_horario",
    )
    fecha = models.DateField()
    hora_inicio = models.TimeField()
    hora_termina = models.TimeField()
    motivo = models.CharField(max_length=200, blank=True, default="")
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fecha", "-hora_inicio"]
        indexes = [models.Index(fields=["profesional", "fecha"])]

    def __str__(self):
        return (
            f"Bloqueo {self.fecha} {self.hora_inicio}-{self.hora_termina} "
            f"({self.profesional_id})"
        )


class MetaDiariaConsulta(models.Model):
    """
    Meta de consultas por día.

    - profesional=None  -> meta general de la clínica.
    - profesional=user  -> meta específica de ese usuario/profesional.

    La meta específica tiene prioridad sobre la general.
    """

    clinica = models.ForeignKey(
        Clinica,
        on_delete=models.CASCADE,
        related_name="metas_diarias_consultas",
    )
    profesional = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="metas_diarias_consultas",
        null=True,
        blank=True,
    )
    cantidad = models.PositiveIntegerField(default=60)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["clinica_id", "profesional_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["clinica"],
                condition=models.Q(profesional__isnull=True),
                name="meta_consulta_general_unica_clinica",
            ),
            models.UniqueConstraint(
                fields=["clinica", "profesional"],
                condition=models.Q(profesional__isnull=False),
                name="meta_consulta_usuario_unica_clinica",
            ),
        ]
        indexes = [
            models.Index(fields=["clinica", "profesional"]),
        ]

    def __str__(self):
        if self.profesional_id:
            nombre = self.profesional.get_full_name() or self.profesional.username
            return f"Meta {self.clinica}: {nombre} = {self.cantidad}"
        return f"Meta general {self.clinica}: {self.cantidad}"




class RolPersonalizado(models.Model):
    slug = models.SlugField(max_length=50, unique=True)
    nombre = models.CharField(max_length=80)
    descripcion = models.CharField(max_length=255, blank=True, default="")
    puede_ver_agenda = models.BooleanField(default=True)
    puede_ver_pacientes = models.BooleanField(default=True)
    puede_ver_contacto_paciente = models.BooleanField(default=True)
    puede_ver_montos = models.BooleanField(default=False)
    puede_modificar_montos = models.BooleanField(default=False)
    puede_ver_finanzas = models.BooleanField(default=False)
    puede_ver_servicios = models.BooleanField(default=True)
    puede_ver_comentarios = models.BooleanField(default=True)
    puede_ver_equipo = models.BooleanField(default=False)
    puede_editar_equipo = models.BooleanField(default=False)
    puede_ver_insumos = models.BooleanField(default=False)
    puede_editar_insumos = models.BooleanField(default=False)
    puede_ver_perfil = models.BooleanField(default=True)
    interfaces = models.JSONField(default=list, blank=True)
    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class ProductoInsumo(models.Model):
    CATEGORIAS = [
        ("bebida", "Bebida"),
        ("snack", "Snack"),
        ("rehabilitacion", "Rehabilitación"),
        ("farmacia", "Farmacia"),
        ("consumible", "Consumible interno"),
        ("otro", "Otro"),
    ]
    clinica = models.ForeignKey(Clinica, on_delete=models.CASCADE, related_name="productos_insumos")
    nombre = models.CharField(max_length=120)
    categoria = models.CharField(max_length=30, choices=CATEGORIAS, default="otro")
    sku = models.CharField(max_length=60, blank=True, default="")
    descripcion = models.CharField(max_length=255, blank=True, default="")
    stock_actual = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    stock_minimo = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    precio_compra = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    precio_venta = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nombre"]
        constraints = [
            models.UniqueConstraint(fields=["clinica", "sku"], condition=~models.Q(sku=""), name="insumo_sku_unico_clinica")
        ]
        indexes = [models.Index(fields=["clinica", "activo", "categoria"])]

    def __str__(self):
        return self.nombre


class MovimientoInsumo(models.Model):
    TIPOS = [
        ("compra", "Compra"),
        ("entrada", "Entrada"),
        ("ajuste_entrada", "Ajuste de entrada"),
        ("merma", "Merma"),
        ("ajuste_salida", "Ajuste de salida"),
    ]
    producto = models.ForeignKey(ProductoInsumo, on_delete=models.PROTECT, related_name="movimientos")
    tipo = models.CharField(max_length=30, choices=TIPOS)
    cantidad = models.DecimalField(max_digits=10, decimal_places=2)
    costo_unitario = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    fecha = models.DateField()
    motivo = models.CharField(max_length=255, blank=True, default="")
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, related_name="movimientos_insumos", null=True, blank=True
    )
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fecha", "-id"]
        indexes = [models.Index(fields=["producto", "fecha"]), models.Index(fields=["fecha", "tipo"])]

    @property
    def total(self):
        return self.cantidad * self.costo_unitario

    def __str__(self):
        return f"{self.producto} - {self.tipo} - {self.cantidad}"


class VentaInsumo(models.Model):
    producto = models.ForeignKey(ProductoInsumo, on_delete=models.PROTECT, related_name="ventas")
    paciente = models.ForeignKey(Paciente, on_delete=models.SET_NULL, related_name="ventas_insumos", null=True, blank=True)
    nombre_cliente = models.CharField(max_length=160, blank=True, default="")
    cantidad = models.DecimalField(max_digits=10, decimal_places=2)
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    metodo_pago = models.CharField(max_length=20, choices=Cita.METODOS_PAGO)
    fecha_pago = models.DateField()
    comprobante = models.CharField(max_length=100, blank=True, default="")
    notas = models.CharField(max_length=255, blank=True, default="")
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, related_name="ventas_insumos_registradas", null=True, blank=True
    )
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fecha_pago", "-id"]
        indexes = [models.Index(fields=["fecha_pago"]), models.Index(fields=["producto", "fecha_pago"])]

    @property
    def total(self):
        return self.cantidad * self.precio_unitario

    def __str__(self):
        return f"Venta {self.producto} - {self.fecha_pago}"
