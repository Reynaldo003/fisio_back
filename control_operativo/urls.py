from django.urls import path
from . import views

urlpatterns = [
    path('control/sesiones/<int:paciente_id>/', views.sesiones_paciente),
    path('control/configuracion-financiera/', views.configuracion_financiera),
    path('control/comisiones/', views.resumen_comisiones),
    path('control/ocupacion/', views.ocupacion_historica),
    path('control/pacientes-inactivos/', views.pacientes_inactivos),
    path('control/bitacora/', views.bitacora_agenda),
    path('control/masivo/', views.operaciones_masivas),
]
