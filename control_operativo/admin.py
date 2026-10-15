from django.contrib import admin
from .models import ConfiguracionFinanciera, MetaPaciente, OrigenPaciente, OrigenCita, ComisionPago, ComisionVentaInsumo, BitacoraAgenda

admin.site.register(ConfiguracionFinanciera)
admin.site.register(MetaPaciente)
admin.site.register(OrigenPaciente)
admin.site.register(OrigenCita)
admin.site.register(ComisionPago)
admin.site.register(ComisionVentaInsumo)
admin.site.register(BitacoraAgenda)
