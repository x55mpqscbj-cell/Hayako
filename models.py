"""
models.py
----------
Definición de tablas de la base de datos usando SQLAlchemy.
Modelos optimizados con soporte de zonas horarias (Python 3.12+),
autenticación segura con PIN opcional, telemetría geográfica,
capacidad de carga en toneladas/kg y reportes comunitarios interactivos.
"""

from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


def obtener_tiempo_actual():
    """Retorna la fecha y hora actual en UTC."""
    return datetime.now(timezone.utc)


class Sector(db.Model):
    """Un sector/barrio de la ciudad, ej: 'Los Jardines', 'Cienfuegos'."""
    __tablename__ = "sectores"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, index=True)
    ciudad = db.Column(db.String(100), nullable=False, default="Santiago")

    # Coordenadas del centro aproximado del sector. Se usan para calcular
    # distancias con Dijkstra (ver optimizacion.py) -- no es la posición
    # del camión (eso cambia constantemente), es un punto fijo de referencia.
    lat_centro = db.Column(db.Float, nullable=True)
    lng_centro = db.Column(db.Float, nullable=True)

    # Métricas de recolección para algoritmos (Mochila y Dijkstra)
    basura_estimada_kg = db.Column(db.Integer, default=1500)
    tiempo_estimado_min = db.Column(db.Integer, default=20)
    prioridad_base = db.Column(db.Integer, default=50)

    # Relaciones
    usuarios = db.relationship("Usuario", backref="sector", lazy=True)
    reportes = db.relationship("Reporte", backref="sector", lazy=True)

    @property
    def camion(self):
        return Camion.query.filter_by(sector_id=self.id).first()

    def to_dict(self):
        reportes_activos = len([r for r in self.reportes if r.estado != "resuelto"])
        # La prioridad se calcula dinámicamente sumando la urgencia comunitaria por reportes
        prioridad_calculada = min(100, self.prioridad_base + (reportes_activos * 10))

        return {
            "id": self.id,
            "nombre": self.nombre,
            "ciudad": self.ciudad,
            "lat_centro": self.lat_centro,
            "lng_centro": self.lng_centro,
            "basura_estimada_kg": self.basura_estimada_kg,
            "tiempo_estimado_min": self.tiempo_estimado_min,
            "prioridad": prioridad_calculada,
            "reportes_activos": reportes_activos,
        }


class Chofer(db.Model):
    """Chofer y su ayudante(s) asignados a la unidad de recolección."""
    __tablename__ = "choferes"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    ayudantes = db.Column(db.String(200), default="")
    foto_url = db.Column(db.String(300), default="")
    telefono = db.Column(db.String(20), default="")

    def to_dict(self):
        return {
            "id": self.id,
            "nombre": self.nombre,
            "ayudantes": self.ayudantes,
            "foto_url": self.foto_url,
            "telefono": self.telefono,
        }


class Camion(db.Model):
    """Un camión de recolección con telemetría en tiempo real y capacidad de carga."""
    __tablename__ = "camiones"

    id = db.Column(db.Integer, primary_key=True)
    placa = db.Column(db.String(20), nullable=False, index=True)
    sector_id = db.Column(db.Integer, db.ForeignKey("sectores.id"), nullable=False)
    chofer_id = db.Column(db.Integer, db.ForeignKey("choferes.id"))

    # Ubicación actual (actualizada dinámicamente por la simulación o GPS)
    lat_actual = db.Column(db.Float, nullable=False)
    lng_actual = db.Column(db.Float, nullable=False)

    # Capacidad y carga útil para la Mochila (Knapsack)
    capacidad_max_kg = db.Column(db.Integer, default=6000)
    carga_actual_kg = db.Column(db.Integer, default=0)

    estado = db.Column(db.String(20), default="en_ruta")  # en_ruta, retrasado, en_pausa, finalizado
    ultima_actualizacion = db.Column(db.DateTime, default=obtener_tiempo_actual)

    # Índice de waypoint en la ruta
    ruta_indice = db.Column(db.Integer, default=0)

    # Relaciones
    sector = db.relationship("Sector", foreign_keys=[sector_id])
    chofer = db.relationship("Chofer", foreign_keys=[chofer_id])

    def to_dict(self):
        hora_str = ""
        if self.ultima_actualizacion:
            hora_str = self.ultima_actualizacion.strftime("%H:%M:%S")

        pct = round((self.carga_actual_kg / self.capacidad_max_kg) * 100, 1) if self.capacidad_max_kg else 0

        return {
            "id": self.id,
            "placa": self.placa,
            "lat": self.lat_actual,
            "lng": self.lng_actual,
            "capacidad_max_kg": self.capacidad_max_kg,
            "carga_actual_kg": self.carga_actual_kg,
            "porcentaje_carga": pct,
            "estado": self.estado,
            "ultima_actualizacion": hora_str,
            "ruta_indice": self.ruta_indice or 0,
            "chofer": self.chofer.to_dict() if self.chofer else {
                "nombre": "N/A", "ayudantes": "", "telefono": "", "foto_url": ""
            },
            "sector": self.sector.nombre if self.sector else "N/A",
            "sector_id": self.sector_id,
        }


class Usuario(db.Model):
    """Un residente que interactúa con la plataforma."""
    __tablename__ = "usuarios"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    telefono = db.Column(db.String(20), nullable=False, unique=True, index=True)
    pin_hash = db.Column(db.String(255), nullable=True)  # Hash seguro para PIN/contraseña
    direccion = db.Column(db.String(200), default="")
    sector_id = db.Column(db.Integer, db.ForeignKey("sectores.id"), nullable=False)
    modo_accesibilidad = db.Column(db.Boolean, default=False)
    fecha_registro = db.Column(db.DateTime, default=obtener_tiempo_actual)

    def establecer_pin(self, pin: str):
        """Genera un hash seguro para el PIN usando PBKDF2."""
        if pin:
            self.pin_hash = generate_password_hash(pin, method="pbkdf2:sha256")
        else:
            self.pin_hash = None

    def verificar_pin(self, pin: str) -> bool:
        """Verifica si el PIN provisto coincide con el hash."""
        if not self.pin_hash:
            return True  # Si la cuenta no tiene PIN configurado, permite acceso
        return check_password_hash(self.pin_hash, pin)

    def to_dict(self):
        return {
            "id": self.id,
            "nombre": self.nombre,
            "telefono": self.telefono,
            "direccion": self.direccion,
            "sector": self.sector.nombre if self.sector else None,
            "sector_id": self.sector_id,
            "modo_accesibilidad": self.modo_accesibilidad,
            "tiene_pin": self.pin_hash is not None,
        }


class Reporte(db.Model):
    """
    Reporte comunitario de incidencia: 'no pasó el camión',
    'basura acumulada', 'contenedor lleno', etc., con coordenadas opcionales
    y confirmaciones vecinales.
    """
    __tablename__ = "reportes"

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=True)  # Nullable para anonimato
    sector_id = db.Column(db.Integer, db.ForeignKey("sectores.id"), nullable=False)
    tipo = db.Column(db.String(50), nullable=False)  # no_paso, basura_acumulada, contenedor_danado, otro
    descripcion = db.Column(db.String(500), default="")

    # Coordenadas geográficas para colocar pines en el mapa interactivo
    lat = db.Column(db.Float, nullable=True)
    lng = db.Column(db.Float, nullable=True)

    # Estado del reporte
    estado = db.Column(db.String(20), default="pendiente")  # pendiente, en_revision, resuelto
    confirmaciones = db.Column(db.Integer, default=1)  # Votos/apoyos de vecinos afectados
    fecha = db.Column(db.DateTime, default=obtener_tiempo_actual)

    usuario = db.relationship("Usuario", backref="reportes")

    def to_dict(self):
        fecha_str = self.fecha.strftime("%d/%m/%Y %H:%M") if self.fecha else ""
        return {
            "id": self.id,
            "tipo": self.tipo,
            "descripcion": self.descripcion,
            "lat": self.lat,
            "lng": self.lng,
            "estado": self.estado,
            "confirmaciones": self.confirmaciones,
            "fecha": fecha_str,
            "sector_id": self.sector_id,
            "sector_nombre": self.sector.nombre if self.sector else "Santiago",
            "reportado_por": self.usuario.nombre if self.usuario else "Vecino anónimo",
        }
