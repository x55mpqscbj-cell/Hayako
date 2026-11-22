"""
simulate.py
------------
Simulador GPS multitarea y multivehículo para la flota de recolección en Santiago, RD.
Controla el avance simultáneo de los camiones sobre sus sectores correspondientes,
con soporte interactivo de pausa, velocidad dinámica, alternancia de retrasos
y reinicio de rutas.
"""

import threading
import time
import random
from datetime import datetime, timezone

# Rutas predefinidas para cada uno de los sectores de Santiago de los Caballeros
RUTAS_SECTORES = [
    # 0. Los Jardines (Norte-Centro)
    [
        (19.4517, -70.6970),
        (19.4532, -70.6945),
        (19.4550, -70.6912),
        (19.4568, -70.6878),
        (19.4580, -70.6845),
        (19.4555, -70.6860),
        (19.4530, -70.6895),
        (19.4517, -70.6970),
    ],
    # 1. Cienfuegos (Oeste)
    [
        (19.4680, -70.7050),
        (19.4710, -70.7120),
        (19.4745, -70.7210),
        (19.4780, -70.7300),
        (19.4750, -70.7350),
        (19.4715, -70.7280),
        (19.4685, -70.7180),
        (19.4680, -70.7050),
    ],
    # 2. Pekín (Sur)
    [
        (19.4430, -70.6890),
        (19.4390, -70.6870),
        (19.4350, -70.6850),
        (19.4310, -70.6830),
        (19.4260, -70.6880),
        (19.4300, -70.6920),
        (19.4360, -70.6930),
        (19.4430, -70.6890),
    ],
    # 3. Reparto del Este (Este)
    [
        (19.4590, -70.6800),
        (19.4570, -70.6750),
        (19.4540, -70.6710),
        (19.4510, -70.6750),
        (19.4480, -70.6780),
        (19.4520, -70.6810),
        (19.4560, -70.6820),
        (19.4590, -70.6800),
    ],
]


def obtener_rutas_serializadas():
    """Retorna las coordenadas de cada ruta en formato JSON para Leaflet."""
    return [
        {
            "sector_indice": i,
            "coordenadas": [{"lat": lat, "lng": lng} for lat, lng in ruta],
        }
        for i, ruta in enumerate(RUTAS_SECTORES)
    ]


def obtener_centroide_ruta(indice):
    """Calcula el centro geográfico aproximado de una ruta."""
    if 0 <= indice < len(RUTAS_SECTORES):
        ruta = RUTAS_SECTORES[indice]
        lat_prom = sum(p[0] for p in ruta) / len(ruta)
        lng_prom = sum(p[1] for p in ruta) / len(ruta)
        return (round(lat_prom, 6), round(lng_prom, 6))
    return (19.4517, -70.6970)


class ControladorSimulacion:
    """Administrador interactivo del motor de simulación."""

    def __init__(self):
        self.pausado = False
        self.velocidad = 1.0  # Multiplicador (1.0 = normal, 2.0 = rápido)
        self.intervalo_base = 4.0  # Segundos por salto
        self.camiones_retrasados_forzados = set()
        self.rutas_personalizadas = {}  # {camion_id: lista_coordenadas}

    def obtener_estado(self):
        return {
            "pausado": self.pausado,
            "velocidad": self.velocidad,
            "intervalo_segundos": round(self.intervalo_base / max(0.1, self.velocidad), 1),
            "retrasados_forzados": list(self.camiones_retrasados_forzados),
        }

    def pausar(self):
        self.pausado = True
        return self.obtener_estado()

    def reanudar(self):
        self.pausado = False
        return self.obtener_estado()

    def set_velocidad(self, multiplicador):
        self.velocidad = max(0.25, min(5.0, float(multiplicador)))
        return self.obtener_estado()

    def toggle_retraso(self, camion_id):
        if camion_id in self.camiones_retrasados_forzados:
            self.camiones_retrasados_forzados.remove(camion_id)
        else:
            self.camiones_retrasados_forzados.add(camion_id)
        return self.obtener_estado()

    def inyectar_ruta_optimizada(self, camion_id, lista_coords):
        if lista_coords and len(lista_coords) >= 2:
            self.rutas_personalizadas[camion_id] = list(lista_coords)


controlador_simulacion = ControladorSimulacion()


def reiniciar_simulacion(app, db, Camion):
    """Reinicia la posición de todos los camiones al primer punto de su ruta."""
    with app.app_context():
        camiones = Camion.query.all()
        for idx, camion in enumerate(camiones):
            ruta = controlador_simulacion.rutas_personalizadas.get(
                camion.id, RUTAS_SECTORES[idx % len(RUTAS_SECTORES)]
            )
            camion.lat_actual = ruta[0][0]
            camion.lng_actual = ruta[0][1]
            camion.ruta_indice = 0
            camion.estado = "en_ruta"
            camion.ultima_actualizacion = datetime.now(timezone.utc)
        db.session.commit()


def iniciar_simulacion(app, db, Camion):
    """
    Inicia el hilo daemon en segundo plano para mover los camiones en tiempo real.
    """
    def bucle_simulacion():
        while True:
            # Cálculo del tiempo de descanso según velocidad
            sleep_time = max(0.5, controlador_simulacion.intervalo_base / max(0.1, controlador_simulacion.velocidad))
            time.sleep(sleep_time)

            if controlador_simulacion.pausado:
                continue

            with app.app_context():
                try:
                    camiones = Camion.query.order_by(Camion.id).all()
                    if not camiones:
                        continue

                    for idx, camion in enumerate(camiones):
                        # Seleccionar la ruta asignada al camión
                        ruta = controlador_simulacion.rutas_personalizadas.get(
                            camion.id, RUTAS_SECTORES[idx % len(RUTAS_SECTORES)]
                        )
                        if not ruta:
                            continue

                        nuevo_indice = ((camion.ruta_indice or 0) + 1) % len(ruta)
                        camion.lat_actual = ruta[nuevo_indice][0]
                        camion.lng_actual = ruta[nuevo_indice][1]
                        camion.ruta_indice = nuevo_indice
                        camion.ultima_actualizacion = datetime.now(timezone.utc)

                        # Manejo de estados (retrasado / en ruta)
                        if camion.id in controlador_simulacion.camiones_retrasados_forzados:
                            camion.estado = "retrasado"
                        else:
                            # 5% de probabilidad de tráfico temporal
                            if random.random() < 0.05:
                                camion.estado = "retrasado"
                            else:
                                camion.estado = "en_ruta"

                    db.session.commit()
                except Exception as e:
                    print(f"[SIMULADOR AVISO] {e}")

    hilo = threading.Thread(target=bucle_simulacion, daemon=True)
    hilo.start()
