from decimal import Decimal
from django.db.models import Sum
from rest_framework import serializers
from core.models import Pago


class PagoSerializer(serializers.ModelSerializer):
    paciente_nombre = serializers.SerializerMethodField(read_only=True); servicio_nombre = serializers.CharField(source="cita.servicio.nombre", read_only=True)
    profesional_id = serializers.IntegerField(source="cita.profesional_id", read_only=True); profesional_nombre = serializers.SerializerMethodField(read_only=True); fecha_cita = serializers.DateField(source="cita.fecha", read_only=True); restante = serializers.DecimalField(max_digits=8, decimal_places=2, read_only=True)

    class Meta:
        model = Pago
        fields = ["id", "cita", "fecha_pago", "comprobante", "monto_facturado", "metodo_pago", "descuento_porcentaje", "anticipo", "restante", "paciente_nombre", "servicio_nombre", "profesional_id", "profesional_nombre", "fecha_cita"]
        extra_kwargs = {"comprobante": {"required": False, "allow_blank": True}, "descuento_porcentaje": {"required": False}, "anticipo": {"required": False}}

    def get_paciente_nombre(self, obj):
        p = obj.cita.paciente; return f"{p.nombres} {p.apellido_pat} {p.apellido_mat or ''}".strip()

    def get_profesional_nombre(self, obj):
        u = obj.cita.profesional; full = f"{u.first_name or ''} {u.last_name or ''}".strip(); return full or u.username

    def validate(self, attrs):
        cita = attrs.get("cita") or getattr(self.instance, "cita", None)
        if not cita: return attrs
        if self.instance is not None and "cita" in attrs and attrs["cita"].pk != self.instance.cita_id: raise serializers.ValidationError({"cita": "No se puede mover un pago a otra cita."})
        anticipo = Decimal(attrs.get("anticipo") or getattr(self.instance, "anticipo", 0) or 0)
        if anticipo < 0: raise serializers.ValidationError({"anticipo": "El anticipo no puede ser negativo."})
        monto_facturado = Decimal(attrs.get("monto_facturado", getattr(self.instance, "monto_facturado", cita.precio)) or cita.precio or 0)
        descuento_porcentaje = Decimal(attrs.get("descuento_porcentaje", getattr(self.instance, "descuento_porcentaje", cita.descuento_porcentaje)) or 0)
        total_con_descuento = max(monto_facturado - (monto_facturado * descuento_porcentaje) / Decimal("100"), Decimal("0"))
        qs_prev = cita.pagos.all()
        if self.instance is not None: qs_prev = qs_prev.exclude(pk=self.instance.pk)
        total_pagado_prev = qs_prev.aggregate(total=Sum("anticipo")).get("total") or Decimal("0"); restante_prev = max(total_con_descuento - total_pagado_prev, Decimal("0"))
        if self.instance is None:
            if restante_prev <= 0 and anticipo > 0: raise serializers.ValidationError({"anticipo": "La cita ya está liquidada; no se puede volver a sumar un pago."})
            if anticipo > restante_prev: raise serializers.ValidationError({"anticipo": f"El pago excede el saldo pendiente. Pendiente actual: ${restante_prev:.2f}"})
        else:
            anticipo_actual = Decimal(getattr(self.instance, "anticipo", 0) or 0); maximo_editable = restante_prev + anticipo_actual
            if anticipo > maximo_editable: raise serializers.ValidationError({"anticipo": f"El pago excede el total permitido para esta cita. Máximo: ${maximo_editable:.2f}"})
        return attrs

    def _calcular_saldos(self, *, cita, monto_facturado, descuento_porcentaje, anticipo_nuevo, excluir=None):
        monto = Decimal(monto_facturado or 0); desc_pct = Decimal(descuento_porcentaje or 0); anticipo_nuevo = Decimal(anticipo_nuevo or 0)
        total_con_descuento = max(monto - (monto * desc_pct) / Decimal("100"), Decimal("0")); qs_prev = cita.pagos.all()
        if excluir is not None: qs_prev = qs_prev.exclude(pk=excluir.pk)
        total_pagado_prev = qs_prev.aggregate(total=Sum("anticipo")).get("total") or Decimal("0"); total_pagado_actual = total_pagado_prev + anticipo_nuevo; restante = max(total_con_descuento - total_pagado_actual, Decimal("0"))
        return restante, total_con_descuento, total_pagado_actual

    def _actualizar_campos_cita(self, *, cita, descuento_porcentaje, total_con_descuento, total_pagado_actual, restante, metodo_pago):
        cita.descuento_porcentaje = descuento_porcentaje; cita.monto_final = total_con_descuento; cita.anticipo = total_pagado_actual; cita.pagado = restante <= 0
        if metodo_pago: cita.metodo_pago = metodo_pago
        cita.save(update_fields=["descuento_porcentaje", "monto_final", "anticipo", "pagado", "metodo_pago", "actualizado"])

    def create(self, validated_data):
        cita = validated_data["cita"]; monto_facturado = validated_data.get("monto_facturado") or cita.precio; descuento_porcentaje = validated_data.get("descuento_porcentaje", cita.descuento_porcentaje); anticipo = validated_data.get("anticipo") or 0; metodo_pago = validated_data.get("metodo_pago") or ""
        restante, total_con_descuento, total_pagado_actual = self._calcular_saldos(cita=cita, monto_facturado=monto_facturado, descuento_porcentaje=descuento_porcentaje, anticipo_nuevo=anticipo)
        validated_data["monto_facturado"] = monto_facturado; validated_data["descuento_porcentaje"] = descuento_porcentaje; validated_data["restante"] = restante
        pago = super().create(validated_data); self._actualizar_campos_cita(cita=cita, descuento_porcentaje=descuento_porcentaje, total_con_descuento=total_con_descuento, total_pagado_actual=total_pagado_actual, restante=restante, metodo_pago=metodo_pago)
        return pago

    def update(self, instance, validated_data):
        cita = instance.cita; monto_facturado = validated_data.get("monto_facturado", instance.monto_facturado or cita.precio); descuento_porcentaje = validated_data.get("descuento_porcentaje", instance.descuento_porcentaje or cita.descuento_porcentaje); anticipo = validated_data.get("anticipo", instance.anticipo or 0); metodo_pago = validated_data.get("metodo_pago", instance.metodo_pago or "")
        restante, total_con_descuento, total_pagado_actual = self._calcular_saldos(cita=cita, monto_facturado=monto_facturado, descuento_porcentaje=descuento_porcentaje, anticipo_nuevo=anticipo, excluir=instance)
        validated_data["monto_facturado"] = monto_facturado; validated_data["descuento_porcentaje"] = descuento_porcentaje; validated_data["restante"] = restante
        pago = super().update(instance, validated_data); self._actualizar_campos_cita(cita=cita, descuento_porcentaje=descuento_porcentaje, total_con_descuento=total_con_descuento, total_pagado_actual=total_pagado_actual, restante=restante, metodo_pago=metodo_pago)
        return pago
