"""
app.py
-------
Servidor principal y API REST de Hayako con soporte de:
- Autenticación segura de usuarios (PIN con hash PBKDF2)
- Telemetría en tiempo real multivehículo (4 camiones y sectores en Santiago)
- Motor de Simulación interactivo (pausa, velocidad, retrasos)
- Algoritmos matemáticos de optimización: Dijkstra y Mochila 0/1
- Reportes ciudadanos geolocalizados con confirmaciones vecinales
"""

import os
import re
import time
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, jsonify, render_template, request, session
from sqlalchemy import inspect, text

from models import db, Sector, Chofer, Camion, Usuario, Reporte
from simulate import (
    iniciar_simulacion,
    controlador_simulacion,
    reiniciar_simulacion,
    obtener_rutas_serializadas,
    obtener_centroide_ruta,
)
import optimizacion

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "basura-rd-apple-secret-key-2026")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///basura.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

# Constantes de configuración
DEPOSITO_LAT = 19.4500
DEPOSITO_LNG = -70.7000
VERTEDERO_LAT = 19.4680
VERTEDERO_LNG = -70.7420

CACHE_TTL_SEGUNDOS = 60
_CACHE_SECTORES_COORDS = {"datos": None, "timestamp": 0}

# Rate limiting simple en memoria
_LIMITES_PETICIONES = {}

# Estado global de la ruta optimizada activa para el chofer
ESTADO_RUTA_ACTIVA = {
    "optimizacion": None,
    "parada_actual_indice": 0,
    "camion_id": 1,
}


def obtener_ip_cliente():
    """Obtiene la dirección IP del cliente considerando proxies."""
    if request.headers.get("X-Forwarded-For"):
        return request.headers.get("X-Forwarded-For").split(",")[0].strip()
    return request.remote_addr or "127.0.0.1"


def verificar_rate_limit(clave: str, max_peticiones: int, ventana_segundos: int) -> bool:
    """Validador de límite de peticiones (Rate Limit)."""
    ahora = time.time()
    historial = _LIMITES_PETICIONES.get(clave, [])
    # Filtrar peticiones fuera de la ventana
    historial = [t for t in historial if ahora - t < ventana_segundos]
    if len(historial) >= max_peticiones:
        return False
    historial.append(ahora)
    _LIMITES_PETICIONES[clave] = historial
    return True


def requiere_admin(f):
    """
    Decorador para proteger rutas de administración.
    Permite acceso en desarrollo o mediante token / header 'X-Admin-Key'.
    """
    @wraps(f)
    def decorada(*args, **kwargs):
        admin_key = os.environ.get("ADMIN_KEY")
        # Si no hay clave configurada en entorno, permitimos para desarrollo fluido
        if not admin_key:
            return f(*args, **kwargs)

        header_key = request.headers.get("X-Admin-Key")
        query_key = request.args.get("admin_key")
        if header_key == admin_key or query_key == admin_key:
            return f(*args, **kwargs)

        return jsonify({"error": "Acceso no autorizado: se requiere clave administrativa"}), 403

    return decorada


def obtener_coords_sectores_cacheado():
    """Retorna las coordenadas centroidales de los sectores con caché en memoria."""
    ahora = time.time()
    if (
        _CACHE_SECTORES_COORDS["datos"] is not None
        and (ahora - _CACHE_SECTORES_COORDS["timestamp"]) < CACHE_TTL_SEGUNDOS
    ):
        return _CACHE_SECTORES_COORDS["datos"]

    sectores = Sector.query.filter(
        Sector.lat_centro.isnot(None), Sector.lng_centro.isnot(None)
    ).all()
    datos = {s.id: (s.lat_centro, s.lng_centro) for s in sectores}

    _CACHE_SECTORES_COORDS["datos"] = datos
    _CACHE_SECTORES_COORDS["timestamp"] = ahora
    return datos


# ==============================================================================
# MIGRACIÓN AUTOMÁTICA Y DATOS INICIALES
# ==============================================================================

def migrar_columnas_si_necesario():
    """Garantiza que la base de datos contenga las columnas requeridas sin romper datos existentes."""
    with app.app_context():
        try:
            inspector = inspect(db.engine)
            tablas = inspector.get_table_names()
            
            if "reportes" in tablas:
                cols_reportes = [c["name"] for c in inspector.get_columns("reportes")]
                with db.engine.connect() as conn:
                    if "lat" not in cols_reportes:
                        conn.execute(text("ALTER TABLE reportes ADD COLUMN lat FLOAT;"))
                    if "lng" not in cols_reportes:
                        conn.execute(text("ALTER TABLE reportes ADD COLUMN lng FLOAT;"))
                    if "estado" not in cols_reportes:
                        conn.execute(text("ALTER TABLE reportes ADD COLUMN estado VARCHAR(20) DEFAULT 'pendiente';"))
                    if "confirmaciones" not in cols_reportes:
                        conn.execute(text("ALTER TABLE reportes ADD COLUMN confirmaciones INTEGER DEFAULT 1;"))
                    conn.commit()

            if "usuarios" in tablas:
                cols_usuarios = [c["name"] for c in inspector.get_columns("usuarios")]
                with db.engine.connect() as conn:
                    if "pin_hash" not in cols_usuarios:
                        conn.execute(text("ALTER TABLE usuarios ADD COLUMN pin_hash VARCHAR(255);"))
                    if "fecha_registro" not in cols_usuarios:
                        conn.execute(text("ALTER TABLE usuarios ADD COLUMN fecha_registro DATETIME;"))
                    conn.commit()

            if "sectores" in tablas:
                cols_sectores = [c["name"] for c in inspector.get_columns("sectores")]
                columnas_nuevas = False
                with db.engine.connect() as conn:
                    if "lat_centro" not in cols_sectores:
                        conn.execute(text("ALTER TABLE sectores ADD COLUMN lat_centro FLOAT;"))
                        columnas_nuevas = True
                    if "lng_centro" not in cols_sectores:
                        conn.execute(text("ALTER TABLE sectores ADD COLUMN lng_centro FLOAT;"))
                        columnas_nuevas = True
                    if "basura_estimada_kg" not in cols_sectores:
                        conn.execute(text("ALTER TABLE sectores ADD COLUMN basura_estimada_kg INTEGER DEFAULT 1500;"))
                    if "tiempo_estimado_min" not in cols_sectores:
                        conn.execute(text("ALTER TABLE sectores ADD COLUMN tiempo_estimado_min INTEGER DEFAULT 20;"))
                    if "prioridad_base" not in cols_sectores:
                        conn.execute(text("ALTER TABLE sectores ADD COLUMN prioridad_base INTEGER DEFAULT 50;"))
                    conn.commit()

                if columnas_nuevas:
                    sectores_existentes = Sector.query.order_by(Sector.id).all()
                    for indice, sector in enumerate(sectores_existentes):
                        if sector.lat_centro is None or sector.lng_centro is None:
                            centroide = obtener_centroide_ruta(indice)
                            if centroide:
                                sector.lat_centro, sector.lng_centro = centroide
                    db.session.commit()

            if "camiones" in tablas:
                cols_camiones = [c["name"] for c in inspector.get_columns("camiones")]
                with db.engine.connect() as conn:
                    if "capacidad_max_kg" not in cols_camiones:
                        conn.execute(text("ALTER TABLE camiones ADD COLUMN capacidad_max_kg INTEGER DEFAULT 6000;"))
                    if "carga_actual_kg" not in cols_camiones:
                        conn.execute(text("ALTER TABLE camiones ADD COLUMN carga_actual_kg INTEGER DEFAULT 0;"))
                    if "ruta_indice" not in cols_camiones:
                        conn.execute(text("ALTER TABLE camiones ADD COLUMN ruta_indice INTEGER DEFAULT 0;"))
                    conn.commit()

        except Exception as e:
            print(f"[MIGRACION AVISO] {e}")


def crear_datos_de_ejemplo():
    """Inicializa sectores, choferes y camiones si la base está vacía."""
    if Sector.query.first() is not None:
        return

    datos_sectores = [
        {
            "sector": "Los Jardines",
            "chofer": "Pedro Martínez",
            "ayudantes": "Juan Pérez, Luis Díaz",
            "telefono_chofer": "809-555-0101",
            "placa": "L123456",
            "lat": 19.4550, "lng": -70.6912,
            "basura_kg": 1600, "prioridad": 85,
        },
        {
            "sector": "Cienfuegos",
            "chofer": "Ramona Durán",
            "ayudantes": "Carlos Núñez",
            "telefono_chofer": "809-555-0202",
            "placa": "L223344",
            "lat": 19.4745, "lng": -70.7210,
            "basura_kg": 2400, "prioridad": 95,
        },
        {
            "sector": "Pekín",
            "chofer": "Freddy Santos",
            "ayudantes": "Miguel Ozuna, Ana Vargas",
            "telefono_chofer": "809-555-0303",
            "placa": "L334455",
            "lat": 19.4350, "lng": -70.6850,
            "basura_kg": 1800, "prioridad": 80,
        },
        {
            "sector": "Reparto del Este",
            "chofer": "Yolanda Reyes",
            "ayudantes": "Tony Cabrera",
            "telefono_chofer": "809-555-0404",
            "placa": "L445566",
            "lat": 19.4540, "lng": -70.6710,
            "basura_kg": 1200, "prioridad": 65,
        },
    ]

    primer_sector = None

    for indice, datos in enumerate(datos_sectores):
        centroide = obtener_centroide_ruta(indice)
        sector = Sector(
            nombre=datos["sector"],
            ciudad="Santiago",
            lat_centro=centroide[0] if centroide else datos["lat"],
            lng_centro=centroide[1] if centroide else datos["lng"],
            basura_estimada_kg=datos.get("basura_kg", 1500),
            prioridad_base=datos.get("prioridad", 50),
        )
        db.session.add(sector)
        db.session.commit()

        if primer_sector is None:
            primer_sector = sector

        chofer = Chofer(
            nombre=datos["chofer"],
            ayudantes=datos["ayudantes"],
            telefono=datos["telefono_chofer"],
        )
        db.session.add(chofer)
        db.session.commit()

        camion = Camion(
            placa=datos["placa"],
            sector_id=sector.id,
            chofer_id=chofer.id,
            lat_actual=datos["lat"],
            lng_actual=datos["lng"],
            estado="en_ruta",
            ruta_indice=0,
            capacidad_max_kg=6000,
            carga_actual_kg=0,
        )
        db.session.add(camion)

    usuario = Usuario(
        nombre="Rosa Gómez",
        telefono="809-555-0202",
        direccion="Calle del Sol #45",
        sector_id=primer_sector.id,
    )
    usuario.establecer_pin("1234")
    db.session.add(usuario)
    db.session.commit()


def asegurar_flota_completa():
    """Garantiza que existan 4 camiones activos con sus choferes para la flota completa."""
    if Camion.query.count() >= 4:
        return

    flota_extra = [
        {"sector_nombre": "Cienfuegos", "chofer": "Ramona Durán", "ayudantes": "Carlos Núñez", "tel": "809-555-0202", "placa": "L223344", "lat": 19.4745, "lng": -70.7210},
        {"sector_nombre": "Los Jardines", "chofer": "Pedro Martínez", "ayudantes": "Juan Pérez, Luis Díaz", "tel": "809-555-0101", "placa": "L334455", "lat": 19.4550, "lng": -70.6912},
        {"sector_nombre": "Pekín", "chofer": "Freddy Santos", "ayudantes": "Miguel Ozuna, Ana Vargas", "tel": "809-555-0303", "placa": "L445566", "lat": 19.4350, "lng": -70.6850},
    ]

    for item in flota_extra:
        if not Camion.query.filter_by(placa=item["placa"]).first():
            sector = Sector.query.filter_by(nombre=item["sector_nombre"]).first() or Sector.query.first()
            chofer = Chofer(nombre=item["chofer"], ayudantes=item["ayudantes"], telefono=item["tel"])
            db.session.add(chofer)
            db.session.commit()

            camion = Camion(
                placa=item["placa"],
                sector_id=sector.id,
                chofer_id=chofer.id,
                lat_actual=item["lat"],
                lng_actual=item["lng"],
                capacidad_max_kg=6000,
                carga_actual_kg=0,
                estado="en_ruta",
            )
            db.session.add(camion)
    db.session.commit()


# ==============================================================================
# RUTAS DE LA APLICACIÓN WEB
# ==============================================================================

@app.route("/")
def index():
    """Página principal interactiva con mapa en tiempo real y UI Apple."""
    return render_template("index.html")


# ==============================================================================
# ENDPOINTS REST: TELEMETRÍA, CAMIONES Y RUTAS
# ==============================================================================

@app.route("/api/camiones")
def api_camiones():
    """Retorna todos los camiones activos con sus coordenadas, chofer y sector."""
    camiones = Camion.query.order_by(Camion.id).all()
    return jsonify([c.to_dict() for c in camiones])


@app.route("/api/camion")
def api_camion():
    """Retorna el primer camión registrado (o el seleccionado)."""
    camion_id = request.args.get("id", type=int)
    if camion_id:
        camion = db.session.get(Camion, camion_id)
    else:
        camion = Camion.query.first()

    if camion is None:
        return jsonify({"error": "No hay camiones registrados"}), 404

    data = camion.to_dict()
    data["simulacion_activa"] = not controlador_simulacion.pausado
    data["base_operativa"] = {"lat": DEPOSITO_LAT, "lng": DEPOSITO_LNG, "nombre": "Base Central Operativa"}
    data["vertedero_rafey"] = {"lat": VERTEDERO_LAT, "lng": VERTEDERO_LNG, "nombre": "Planta Rafey"}

    if ESTADO_RUTA_ACTIVA["optimizacion"]:
        itinerario = ESTADO_RUTA_ACTIVA["optimizacion"]["itinerario_chofer"]
        idx = ESTADO_RUTA_ACTIVA["parada_actual_indice"]
        if idx < len(itinerario):
            data["parada_actual"] = itinerario[idx]
        else:
            data["parada_actual"] = {"nombre": "Ruta Completada", "accion": "Descarga finalizada en Rafey"}
    else:
        data["parada_actual"] = {
            "nombre": camion.sector.nombre if camion.sector else "Base Central",
            "accion": "Recorriendo circuito habitual del sector",
        }

    return jsonify(data)


@app.route("/api/rutas")
def api_rutas():
    """Retorna las coordenadas geométricas de las rutas de cada sector para Leaflet."""
    return jsonify(obtener_rutas_serializadas())


@app.route("/api/sectores")
def api_sectores():
    """Retorna los sectores disponibles con estado de camión asignado."""
    sectores = Sector.query.all()
    data = []
    for s in sectores:
        item = s.to_dict()
        camion = s.camion
        item["camion_id"] = camion.id if camion else None
        item["camion_placa"] = camion.placa if camion else None
        item["camion_estado"] = camion.estado if camion else "sin_unidad"
        data.append(item)
    return jsonify(data)


# ==============================================================================
# ENDPOINTS REST: CONTROL INTERACTIVO DE SIMULACIÓN
# ==============================================================================

@app.route("/api/simulacion/estado")
def api_simulacion_estado():
    """Retorna el estado interactivo actual del motor de simulación."""
    return jsonify(controlador_simulacion.obtener_estado())


@app.route("/api/simulacion/control", methods=["POST"])
def api_simulacion_control():
    """
    Controla interactivamente la simulación:
    acciones: 'pausar', 'reanudar', 'velocidad', 'toggle_retraso', 'reiniciar'
    """
    if not request.is_json:
        return jsonify({"error": "Se requiere cuerpo JSON"}), 400

    data = request.get_json() or {}
    accion = data.get("accion")

    if accion == "pausar":
        estado = controlador_simulacion.pausar()
        return jsonify({"mensaje": "Simulación pausada", "estado": estado})

    elif accion == "reanudar":
        estado = controlador_simulacion.reanudar()
        return jsonify({"mensaje": "Simulación reanudada", "estado": estado})

    elif accion == "velocidad":
        multiplicador = data.get("multiplicador", 1.0)
        estado = controlador_simulacion.set_velocidad(multiplicador)
        return jsonify({"mensaje": f"Velocidad ajustada a {estado['velocidad']}x", "estado": estado})

    elif accion == "toggle_retraso":
        camion_id = data.get("camion_id") or 1
        estado = controlador_simulacion.toggle_retraso(camion_id)
        return jsonify({"mensaje": "Estado de retraso alternado", "estado": estado})

    elif accion == "reiniciar":
        reiniciar_simulacion(app, db, Camion)
        return jsonify({"mensaje": "Rutas reiniciadas al punto de origen", "estado": controlador_simulacion.obtener_estado()})

    return jsonify({"error": f"Acción desconocida '{accion}'"}), 400


# ==============================================================================
# ENDPOINTS REST: AUTENTICACIÓN Y CUENTAS DE USUARIO
# ==============================================================================

@app.route("/api/login", methods=["POST"])
def api_login():
    """Inicio de sesión seguro con protección anti fuerza bruta."""
    ip = obtener_ip_cliente()
    if not verificar_rate_limit(f"login_{ip}", max_peticiones=10, ventana_segundos=60):
        return jsonify({"error": "Demasiados intentos. Espera un momento antes de volver a intentar."}), 429

    if not request.is_json:
        return jsonify({"error": "Petición no válida (se espera JSON)"}), 400

    data = request.get_json() or {}
    nombre = (data.get("nombre") or "").strip()
    telefono = (data.get("telefono") or "").strip()
    pin = (data.get("pin") or "").strip()

    if not nombre or len(nombre) > 100:
        return jsonify({"error": "El nombre es obligatorio (máximo 100 caracteres)"}), 400

    telefono_limpio = re.sub(r"[^\d\-+()]", "", telefono)
    if not telefono_limpio or len(telefono_limpio) < 7 or len(telefono_limpio) > 20:
        return jsonify({"error": "El teléfono provisto no tiene un formato válido"}), 400

    usuario = Usuario.query.filter_by(telefono=telefono_limpio).first()

    if usuario is None:
        sector = Sector.query.first()
        usuario = Usuario(
            nombre=nombre,
            telefono=telefono_limpio,
            sector_id=sector.id if sector else 1,
        )
        if pin:
            if len(pin) < 4 or len(pin) > 20:
                return jsonify({"error": "El PIN debe tener entre 4 y 20 dígitos/caracteres"}), 400
            usuario.establecer_pin(pin)

        db.session.add(usuario)
        db.session.commit()
    else:
        if usuario.pin_hash:
            if not pin:
                return jsonify({"error": "Esta cuenta tiene un PIN de seguridad. Ingrésalo para continuar."}), 401
            if not usuario.verificar_pin(pin):
                return jsonify({"error": "El PIN ingresado es incorrecto."}), 401
        elif pin:
            usuario.establecer_pin(pin)

        usuario.nombre = nombre
        db.session.commit()

    session["usuario_id"] = usuario.id
    return jsonify(usuario.to_dict())


@app.route("/api/logout", methods=["POST"])
def api_logout():
    """Cierra la sesión actual del usuario."""
    session.pop("usuario_id", None)
    return jsonify({"mensaje": "Sesión cerrada correctamente"})


@app.route("/api/me")
def api_me():
    """Retorna los datos del usuario conectado en la sesión actual."""
    usuario_id = session.get("usuario_id")
    if not usuario_id:
        return jsonify(None)

    usuario = db.session.get(Usuario, usuario_id)
    if usuario is None:
        session.pop("usuario_id", None)
        return jsonify(None)

    return jsonify(usuario.to_dict())


@app.route("/api/usuario/preferencias", methods=["POST"])
def api_preferencias():
    """Actualiza preferencias del usuario."""
    usuario_id = session.get("usuario_id")
    if not usuario_id:
        return jsonify({"error": "Debes iniciar sesión para modificar preferencias"}), 401

    usuario = db.session.get(Usuario, usuario_id)
    if not usuario:
        return jsonify({"error": "Usuario no encontrado"}), 404

    data = request.get_json() or {}
    if "modo_accesibilidad" in data:
        usuario.modo_accesibilidad = bool(data["modo_accesibilidad"])
    if "sector_id" in data:
        sector = db.session.get(Sector, data["sector_id"])
        if sector:
            usuario.sector_id = sector.id

    db.session.commit()
    return jsonify(usuario.to_dict())


# ==============================================================================
# ENDPOINTS REST: REPORTES E INCIDENCIAS COMUNITARIAS
# ==============================================================================

TIPOS_REPORTES_VALIDOS = {
    "no_paso",
    "basura_acumulada",
    "contenedor_danado",
    "animal_muerto",
    "horario_incumplido",
    "otro",
}


@app.route("/api/reportar", methods=["POST"])
def api_reportar():
    """Registra una incidencia comunitaria."""
    ip = obtener_ip_cliente()
    if not verificar_rate_limit(f"reporte_{ip}", max_peticiones=8, ventana_segundos=120):
        return jsonify({"error": "Has enviado varios reportes recientemente. Por favor espera un momento."}), 429

    if not request.is_json:
        return jsonify({"error": "Formato de petición inválido"}), 400

    data = request.get_json() or {}
    tipo = str(data.get("tipo", "otro")).strip()
    if tipo not in TIPOS_REPORTES_VALIDOS:
        tipo = "otro"

    descripcion = str(data.get("descripcion", "")).strip()[:500]

    lat = data.get("lat")
    lng = data.get("lng")
    try:
        lat = float(lat) if lat is not None else None
        lng = float(lng) if lng is not None else None
        if lat is not None and not (-90 <= lat <= 90):
            lat = None
        if lng is not None and not (-180 <= lng <= 180):
            lng = None
    except (ValueError, TypeError):
        lat, lng = None, None

    usuario_id = session.get("usuario_id")
    usuario = db.session.get(Usuario, usuario_id) if usuario_id else None

    sector_id = data.get("sector_id")
    if not sector_id:
        if usuario:
            sector_id = usuario.sector_id
        else:
            primer_sector = Sector.query.first()
            sector_id = primer_sector.id if primer_sector else 1

    # Prevención anti-duplicados
    hace_2_min = datetime.now(timezone.utc).timestamp() - 120
    reporte_reciente = (
        Reporte.query.filter_by(sector_id=sector_id, tipo=tipo)
        .order_by(Reporte.fecha.desc())
        .first()
    )
    if reporte_reciente and reporte_reciente.fecha:
        ts = (
            reporte_reciente.fecha.replace(tzinfo=timezone.utc).timestamp()
            if reporte_reciente.fecha.tzinfo is None
            else reporte_reciente.fecha.timestamp()
        )
        if ts > hace_2_min:
            reporte_reciente.confirmaciones = (reporte_reciente.confirmaciones or 1) + 1
            db.session.commit()
            return jsonify({
                "mensaje": "Ya existe un reporte similar en tu zona. Hemos sumado tu confirmación.",
                "id": reporte_reciente.id,
                "confirmaciones": reporte_reciente.confirmaciones,
                "reporte": reporte_reciente.to_dict(),
            })

    nuevo_reporte = Reporte(
        usuario_id=usuario.id if usuario else None,
        sector_id=sector_id,
        tipo=tipo,
        descripcion=descripcion,
        lat=lat,
        lng=lng,
        estado="pendiente",
        confirmaciones=1,
    )
    db.session.add(nuevo_reporte)
    db.session.commit()

    return jsonify({
        "mensaje": "Reporte registrado correctamente. Gracias por colaborar con tu comunidad.",
        "id": nuevo_reporte.id,
        "reporte": nuevo_reporte.to_dict(),
    })


@app.route("/api/reportes")
def api_reportes():
    """Lista los reportes ciudadanos más recientes."""
    reportes = Reporte.query.order_by(Reporte.fecha.desc()).limit(50).all()
    return jsonify([r.to_dict() for r in reportes])


@app.route("/api/reportes/<int:reporte_id>/confirmar", methods=["POST"])
def api_confirmar_reporte(reporte_id):
    """Permite apoyar o confirmar un reporte comunitario (+1)."""
    ip = obtener_ip_cliente()
    clave_limite = f"confirmar_{ip}_{reporte_id}"
    if not verificar_rate_limit(clave_limite, max_peticiones=1, ventana_segundos=300):
        return jsonify({"error": "Ya has confirmado este reporte recientemente."}), 429

    reporte = db.session.get(Reporte, reporte_id)
    if not reporte:
        return jsonify({"error": "Reporte no encontrado"}), 404

    reporte.confirmaciones = (reporte.confirmaciones or 1) + 1
    db.session.commit()

    return jsonify({
        "mensaje": "Confirmación registrada",
        "id": reporte.id,
        "confirmaciones": reporte.confirmaciones,
    })


# ==============================================================================
# ENDPOINTS REST: OPTIMIZACIÓN LOGÍSTICA (DIJKSTRA Y MOCHILA)
# ==============================================================================

@app.route("/api/optimizar-ruta", methods=["POST"])
def api_optimizar_ruta():
    """
    Motor Central de Optimización para el Chofer y la Flota.
    1. Mochila (Knapsack): Selecciona los sectores más urgentes según capacidad del camión.
    2. Dijkstra + TSP: Genera el circuito vial de menor kilometraje partiendo desde la Base.
    3. Confort Chofer: Calcula tiempos, combustible, ahorro y el itinerario paso a paso.
    """
    req_data = request.get_json() or {}
    camion_id = req_data.get("camion_id", 1)
    camion = db.session.get(Camion, camion_id) or Camion.query.first()
    capacidad = req_data.get("capacidad_max_kg", camion.capacidad_max_kg if camion else 6000)

    sectores = [s.to_dict() for s in Sector.query.all()]

    resultado = optimizacion.optimizar_logistica_chofer(
        base_coords=(DEPOSITO_LAT, DEPOSITO_LNG),
        vertedero_coords=(VERTEDERO_LAT, VERTEDERO_LNG),
        sectores=sectores,
        capacidad_camion_kg=capacidad,
    )

    if "error" in resultado:
        return jsonify(resultado), 400

    ESTADO_RUTA_ACTIVA["optimizacion"] = resultado
    ESTADO_RUTA_ACTIVA["parada_actual_indice"] = 0
    ESTADO_RUTA_ACTIVA["camion_id"] = camion.id if camion else 1

    # Inyectar polilínea de coordenadas al simulador GPS
    coordenadas_gps = resultado["coordenadas_polilinea"]
    if camion:
        controlador_simulacion.inyectar_ruta_optimizada(camion.id, coordenadas_gps)
        camion.estado = "en_ruta"
        db.session.commit()

    return jsonify({
        "status": "success",
        "mensaje": "Ruta óptima calculada con éxito usando Dijkstra y Mochila.",
        "datos": resultado,
    })


@app.route("/api/chofer/siguiente-parada", methods=["POST"])
def api_chofer_siguiente_parada():
    """
    Acción táctil para el chofer:
    Marca la parada actual completada, incrementa la carga y pasa a la siguiente.
    """
    if not ESTADO_RUTA_ACTIVA["optimizacion"]:
        return jsonify({"error": "No hay ninguna ruta optimizada activa"}), 400

    itinerario = ESTADO_RUTA_ACTIVA["optimizacion"]["itinerario_chofer"]
    idx = ESTADO_RUTA_ACTIVA["parada_actual_indice"]

    if idx >= len(itinerario):
        return jsonify({"mensaje": "La ruta ya ha sido completada en su totalidad."})

    parada_completada = itinerario[idx]
    camion = db.session.get(Camion, ESTADO_RUTA_ACTIVA["camion_id"]) or Camion.query.first()

    # Si fue un sector de recolección, actualizamos la base de datos
    if parada_completada.get("sector_id") and camion:
        sector = db.session.get(Sector, parada_completada["sector_id"])
        if sector:
            camion.carga_actual_kg = min(
                camion.capacidad_max_kg,
                camion.carga_actual_kg + sector.basura_estimada_kg,
            )
            db.session.commit()

    ESTADO_RUTA_ACTIVA["parada_actual_indice"] += 1
    nuevo_idx = ESTADO_RUTA_ACTIVA["parada_actual_indice"]

    if nuevo_idx < len(itinerario):
        proxima = itinerario[nuevo_idx]
        return jsonify({
            "mensaje": f"Parada '{parada_completada['nombre']}' completada.",
            "completada": parada_completada,
            "proxima_parada": proxima,
            "terminada": False,
        })
    else:
        if camion:
            camion.estado = "en_base"
            camion.carga_actual_kg = 0  # Descarga en Rafey
            db.session.commit()
        return jsonify({
            "mensaje": "¡Ruta finalizada! Carga descargada exitosamente en el vertedero de Rafey.",
            "completada": parada_completada,
            "proxima_parada": None,
            "terminada": True,
        })


@app.route("/api/admin/distancias-sectores")
@requiere_admin
def api_admin_distancias_sectores():
    """Calcula con Dijkstra las distancias mínimas desde el depósito a todos los sectores."""
    coords_sectores = obtener_coords_sectores_cacheado()
    if not coords_sectores:
        return jsonify({"error": "No hay sectores con coordenadas definidas"}), 404

    resultado = optimizacion.sugerir_distancias_desde_deposito(
        coords_sectores, (DEPOSITO_LAT, DEPOSITO_LNG)
    )

    nombres = {s.id: s.nombre for s in Sector.query.all()}
    for r in resultado:
        r["sector_nombre"] = nombres.get(r["sector_id"], "Desconocido")

    return jsonify({
        "deposito": {"lat": DEPOSITO_LAT, "lng": DEPOSITO_LNG},
        "sectores_ordenados_por_distancia": resultado,
    })


@app.route("/api/admin/asignar-turno", methods=["POST"])
@requiere_admin
def api_admin_asignar_turno():
    """Asignación de sectores a un turno mediante el Algoritmo de la Mochila."""
    if not request.is_json:
        return jsonify({"error": "Se requiere cuerpo JSON"}), 400

    data = request.get_json() or {}
    capacidad = data.get("capacidad_minutos")
    sectores_input = data.get("sectores")

    if not isinstance(capacidad, (int, float)) or capacidad <= 0:
        return jsonify({"error": "capacidad_minutos debe ser un número positivo"}), 400
    if not isinstance(sectores_input, list) or not sectores_input:
        return jsonify({"error": "sectores debe ser una lista no vacía"}), 400

    items = []
    for s in sectores_input:
        sector_id = s.get("sector_id")
        costo = s.get("costo_minutos")
        if sector_id is None or not isinstance(costo, (int, float)) or costo < 0:
            return jsonify({"error": f"Entrada de sector inválida: {s}"}), 400

        valor = s.get("valor")
        if valor is None:
            reportes_pendientes = Reporte.query.filter_by(
                sector_id=sector_id, estado="pendiente"
            ).count()
            valor = reportes_pendientes + 1

        items.append((sector_id, int(costo), float(valor)))

    valor_total, elegidos_ids = optimizacion.mochila_asignacion(int(capacidad), items)
    nombres = {s.id: s.nombre for s in Sector.query.all()}
    minutos_usados = sum(c for sid, c, v in items if sid in elegidos_ids)

    return jsonify({
        "capacidad_minutos": capacidad,
        "minutos_usados": minutos_usados,
        "valor_total_servido": valor_total,
        "sectores_elegidos": [
            {"sector_id": sid, "sector_nombre": nombres.get(sid, "Desconocido")}
            for sid in elegidos_ids
        ],
    })


# ==============================================================================
# MANEJADOR DE ERRORES GLOBAL
# ==============================================================================

@app.errorhandler(404)
def error_404(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Recurso no encontrado"}), 404
    return render_template("index.html"), 404


@app.errorhandler(500)
def error_500(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Error interno del servidor"}), 500
    return render_template("index.html"), 500


# ==============================================================================
# INICIALIZACIÓN Y ARRANQUE
# ==============================================================================

with app.app_context():
    db.create_all()
    migrar_columnas_si_necesario()
    crear_datos_de_ejemplo()
    asegurar_flota_completa()

iniciar_simulacion(app, db, Camion)

if __name__ == "__main__":
    puerto = int(os.environ.get("PORT", 5050))
    app.run(debug=True, host="0.0.0.0", port=puerto)
