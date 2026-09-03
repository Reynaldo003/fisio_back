from decimal import Decimal

from rest_framework import serializers

from core.models import MovimientoInsumo, ProductoInsumo, VentaInsumo


class ProductoInsumoSerializer(serializers.ModelSerializer):
    valor_stock = serializers.SerializerMethodField()
    stock_bajo = serializers.SerializerMethodField()

    class Meta:
        model = ProductoInsumo
        fields = ["id", "clinica", "nombre", "categoria", "sku", "descripcion", "stock_actual", "stock_minimo", "precio_compra", "precio_venta", "valor_stock", "stock_bajo", "activo", "creado", "actualizado"]
        read_only_fields = ["id", "clinica", "valor_stock", "stock_bajo", "creado", "actualizado"]

    def get_valor_stock(self, obj):
        return Decimal(obj.stock_actual or 0) * Decimal(obj.precio_compra or 0)

    def get_stock_bajo(self, obj):
        return Decimal(obj.stock_actual or 0) <= Decimal(obj.stock_minimo or 0)


class MovimientoInsumoSerializer(serializers.ModelSerializer):
    producto_nombre = serializers.CharField(source="producto.nombre", read_only=True)
    total = serializers.SerializerMethodField()
    registrado_por_nombre = serializers.SerializerMethodField()

    class Meta:
        model = MovimientoInsumo
        fields = ["id", "producto", "producto_nombre", "tipo", "cantidad", "costo_unitario", "total", "fecha", "motivo", "registrado_por", "registrado_por_nombre", "creado"]
        read_only_fields = ["id", "total", "registrado_por", "registrado_por_nombre", "creado"]

    def get_total(self, obj):
        return obj.total

    def get_registrado_por_nombre(self, obj):
        if not obj.registrado_por:
            return None
        return (obj.registrado_por.get_full_name() or "").strip() or obj.registrado_por.username

    def validate_cantidad(self, value):
        if value <= 0:
            raise serializers.ValidationError("La cantidad debe ser mayor a cero.")
        return value


class VentaInsumoSerializer(serializers.ModelSerializer):
    producto_nombre = serializers.CharField(source="producto.nombre", read_only=True)
    total = serializers.SerializerMethodField()
    paciente_nombre = serializers.SerializerMethodField()
    registrado_por_nombre = serializers.SerializerMethodField()

    class Meta:
        model = VentaInsumo
        fields = ["id", "producto", "producto_nombre", "paciente", "paciente_nombre", "nombre_cliente", "cantidad", "precio_unitario", "total", "metodo_pago", "fecha_pago", "comprobante", "notas", "registrado_por", "registrado_por_nombre", "creado"]
        read_only_fields = ["id", "total", "registrado_por", "registrado_por_nombre", "creado"]

    def get_total(self, obj):
        return obj.total

    def get_paciente_nombre(self, obj):
        if not obj.paciente:
            return obj.nombre_cliente or "Mostrador"
        return f"{obj.paciente.nombres} {obj.paciente.apellido_pat} {obj.paciente.apellido_mat or ''}".strip()

    def get_registrado_por_nombre(self, obj):
        if not obj.registrado_por:
            return None
        return (obj.registrado_por.get_full_name() or "").strip() or obj.registrado_por.username

    def validate_cantidad(self, value):
        if value <= 0:
            raise serializers.ValidationError("La cantidad debe ser mayor a cero.")
        return value

    def validate_precio_unitario(self, value):
        if value < 0:
            raise serializers.ValidationError("El precio no puede ser negativo.")
        return value
