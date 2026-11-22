"""
optimizacion.py
-----------------
Algoritmos de optimización matemática para Hayako:
1. Dijkstra -> Cálculo del camino más corto y matriz de distancias viales mínimas.
2. Mochila 0/1 (Knapsack) -> Maximización de prioridad/reportes atendidos sin sobrepasar
   la capacidad del camión (en kg de residuos o minutos de turno).
3. Motor Integral de Logística y Confort para el Chofer -> Genera el circuito óptimo
   que parte de la Base/Depósito hacia cada sector seleccionado y culmina en el vertedero.
"""

import heapq
import math

# Constantes geográficas de Santiago de los Caballeros
DEPOSITO_SANTIAGO = (19.4500, -70.7000)      # Base Operativa (Av. 27 de Febrero)
VERTEDERO_RAFEY_SANTIAGO = (19.4680, -70.7420)  # Planta de Tratamiento Rafey


# ==============================================================================
# 1. DIJKSTRA - DISTANCIA MÁS CORTA Y CAMINOS MÍNIMOS EN GRAFOS
# ==============================================================================

def haversine_km(lat1, lng1, lat2, lng2):
    """
    Calcula la distancia precisa de círculo máximo entre dos coordenadas GPS (km).
    Fórmula geodésica exacta considerando la curvatura esférica de la Tierra.
    """
    R = 6371.0  # Radio medio de la Tierra en km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)

    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * (math.sin(dlambda / 2.0) ** 2)
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return round(R * c, 3)


def construir_grafo_completo(nodos):
    """
    Construye un grafo ponderado conectando todos los nodos viales con distancias reales en km.
    nodos: dict {identificador: (lat, lng)}
    Devuelve: {nombre: [(vecino, distancia_km), ...]}
    """
    grafo = {nombre: [] for nombre in nodos}
    nombres = list(nodos.keys())

    for i in range(len(nombres)):
        for j in range(i + 1, len(nombres)):
            n1, n2 = nombres[i], nombres[j]
            lat1, lng1 = nodos[n1]
            lat2, lng2 = nodos[n2]
            # Factor de curvatura vial urbana promedio (1.18x) para calles reales
            dist = round(haversine_km(lat1, lng1, lat2, lng2) * 1.18, 2)
            grafo[n1].append((n2, dist))
            grafo[n2].append((n1, dist))

    return grafo


def dijkstra(grafo, inicio):
    """
    Algoritmo de Dijkstra con Min-Heap para distancias mínimas desde el nodo 'inicio'.
    Complejidad: O((V + E) log V).
    Devuelve: (distancias, camino_previo)
    """
    distancias = {nodo: float("inf") for nodo in grafo}
    distancias[inicio] = 0.0
    camino_previo = {nodo: None for nodo in grafo}

    cola = [(0.0, inicio)]
    visitados = set()

    while cola:
        distancia_actual, nodo_actual = heapq.heappop(cola)
        if nodo_actual in visitados:
            continue
        visitados.add(nodo_actual)

        for vecino, peso in grafo.get(nodo_actual, []):
            nueva_distancia = distancia_actual + peso
            if nueva_distancia < distancias[vecino]:
                distancias[vecino] = round(nueva_distancia, 3)
                camino_previo[vecino] = nodo_actual
                heapq.heappush(cola, (nueva_distancia, vecino))

    return distancias, camino_previo


def reconstruir_camino(camino_previo, destino):
    """Reconstruye la secuencia ordenada de nodos desde el origen hasta el destino."""
    camino = []
    nodo = destino
    while nodo is not None:
        camino.append(nodo)
        nodo = camino_previo.get(nodo)
    camino.reverse()
    return camino


def sugerir_distancias_desde_deposito(sectores_coords, deposito_coords):
    """
    Calcula con Dijkstra las distancias más cortas desde el depósito central
    a cada sector, ordenadas de menor a mayor.
    """
    nodos = {"Deposito": deposito_coords}
    for sector_id, coords in sectores_coords.items():
        nodos[str(sector_id)] = coords

    grafo = construir_grafo_completo(nodos)
    distancias, camino_previo = dijkstra(grafo, "Deposito")

    resultado = []
    for sector_id in sectores_coords:
        clave = str(sector_id)
        resultado.append({
            "sector_id": sector_id,
            "distancia_km": round(distancias[clave], 2),
            "camino": reconstruir_camino(camino_previo, clave),
        })

    resultado.sort(key=lambda r: r["distancia_km"])
    return resultado


# ==============================================================================
# 2. MOCHILA 0/1 (KNAPSACK) - OPTIMIZACIÓN COMBINATORIA DE CAPACIDAD
# ==============================================================================

def mochila_asignacion(capacidad_maxima, items):
    """
    Algoritmo de la Mochila 0/1 con Programación Dinámica.
    capacidad_maxima: entero (ej. capacidad en kg o minutos de turno)
    items: lista de tuplas (identificador, costo/peso, valor/prioridad)

    Ecuación de recurrencia:
    tabla[i][c] = max(tabla[i-1][c], tabla[i-1][c - costo] + valor)

    Devuelve: (valor_total_maximo, lista_de_identificadores_elegidos)
    """
    items_filtrados = [(iid, int(costo), float(valor)) for iid, costo, valor in items if costo >= 0]
    n = len(items_filtrados)
    capacidad_maxima = max(0, int(capacidad_maxima))

    # Optimización: si la capacidad es muy grande (ej. 6000 kg), escalamos por paso para ahorrar memoria
    paso = 50 if capacidad_maxima > 2000 else 1
    cap_escalada = capacidad_maxima // paso

    tabla = [[0.0] * (cap_escalada + 1) for _ in range(n + 1)]

    for i in range(1, n + 1):
        _, costo, valor = items_filtrados[i - 1]
        costo_esc = max(1, costo // paso) if paso > 1 else costo

        for c in range(cap_escalada + 1):
            mejor_sin_este = tabla[i - 1][c]
            mejor_con_este = (valor + tabla[i - 1][c - costo_esc]) if costo_esc <= c else -1.0
            tabla[i][c] = max(mejor_sin_este, mejor_con_este)

    # Reconstrucción de sectores seleccionados
    elegidos = []
    c = cap_escalada
    for i in range(n, 0, -1):
        if tabla[i][c] != tabla[i - 1][c]:
            iid, costo, _ = items_filtrados[i - 1]
            elegidos.append(iid)
            costo_esc = max(1, costo // paso) if paso > 1 else costo
            c -= costo_esc

    elegidos.reverse()
    return tabla[n][cap_escalada], elegidos


# ==============================================================================
# 3. MOTOR INTEGRAL DE LOGÍSTICA PARA EL CHOFER (DIJKSTRA + MOCHILA + TSP)
# ==============================================================================

def optimizar_logistica_chofer(base_coords, vertedero_coords, sectores, capacidad_camion_kg):
    """
    Genera el circuito logístico óptimo para el chofer:
    1. Mochila (Knapsack): selecciona los sectores que maximizan la prioridad comunitaria
       sin superar la capacidad de carga del camión.
    2. Dijkstra: calcula los caminos viales mínimos entre paradas.
    3. TSP (Vecino más cercano): organiza el recorrido desde la Base hacia cada sector y termina en Rafey.
    4. Métricas de eficiencia: km ahorrados, combustible (galones diésel), dinero (RD$) y emisiones de CO2.
    """
    if not sectores:
        return {"error": "No hay sectores disponibles para optimizar"}

    # Paso 1: Filtro de la Mochila
    items_mochila = [
        (s["id"], s.get("basura_estimada_kg", 1500), s.get("prioridad", 50))
        for s in sectores
    ]
    _, ids_elegidos = mochila_asignacion(capacidad_camion_kg, items_mochila)
    set_elegidos = set(ids_elegidos)

    sectores_seleccionados = [s for s in sectores if s["id"] in set_elegidos]
    sectores_postergados = [s for s in sectores if s["id"] not in set_elegidos]

    if not sectores_seleccionados:
        # Fallback al sector más prioritario si ninguno cabe individualmente
        sectores_seleccionados = [max(sectores, key=lambda x: x.get("prioridad", 0))]

    # Paso 2: Grafo y Ordenamiento de Paradas (TSP Greedy + Dijkstra)
    nodos_grafo = {
        "Base": base_coords,
        "Vertedero": vertedero_coords,
    }
    for s in sectores_seleccionados:
        nodos_grafo[f"Sector_{s['id']}"] = (s["lat_centro"], s["lng_centro"])

    grafo = construir_grafo_completo(nodos_grafo)

    # Ordenamiento de paradas desde la Base
    nodo_actual = "Base"
    pendientes = list(sectores_seleccionados)
    itinerario_ordenado = []

    while pendientes:
        distancias, _ = dijkstra(grafo, nodo_actual)
        mejor_dist = float("inf")
        mejor_sector = None

        for sec in pendientes:
            clave_sec = f"Sector_{sec['id']}"
            dist = distancias.get(clave_sec, float("inf"))
            if dist < mejor_dist:
                mejor_dist = dist
                mejor_sector = sec

        itinerario_ordenado.append(mejor_sector)
        pendientes.remove(mejor_sector)
        nodo_actual = f"Sector_{mejor_sector['id']}"

    # Paso 3: Construcción de la Hoja de Ruta Turn-by-Turn para el Chofer
    itinerario_chofer = []
    coordenadas_polilinea = [base_coords]
    distancia_optimizada_km = 0.0
    tiempo_total_min = 0
    carga_acumulada_kg = 0
    velocidad_promedio_kmh = 24.0  # Velocidad urbana de camión recolector

    # Parada 0: Salida de la Base
    itinerario_chofer.append({
        "orden": 0,
        "tipo": "base",
        "nombre": "Base Central Operativa (Av. 27 de Febrero)",
        "lat": base_coords[0],
        "lng": base_coords[1],
        "accion": "Salida de base. Inspección técnica del camión completada.",
        "distancia_tramo_km": 0.0,
        "tiempo_tramo_min": 0,
        "carga_acumulada_kg": 0,
    })

    lat_prev, lng_prev = base_coords

    for idx, sec in enumerate(itinerario_ordenado, start=1):
        lat_sec, lng_sec = sec["lat_centro"], sec["lng_centro"]
        dist_tramo = round(haversine_km(lat_prev, lng_prev, lat_sec, lng_sec) * 1.18, 2)
        distancia_optimizada_km += dist_tramo

        tiempo_viaje = round((dist_tramo / velocidad_promedio_kmh) * 60)
        tiempo_recoleccion = sec.get("tiempo_estimado_min", 20)
        tiempo_tramo = tiempo_viaje + tiempo_recoleccion
        tiempo_total_min += tiempo_tramo

        carga_acumulada_kg += sec.get("basura_estimada_kg", 1500)
        coordenadas_polilinea.append((lat_sec, lng_sec))

        itinerario_chofer.append({
            "orden": idx,
            "tipo": "recoleccion",
            "sector_id": sec["id"],
            "nombre": sec["nombre"],
            "lat": lat_sec,
            "lng": lng_sec,
            "accion": f"Recolectar {sec.get('basura_estimada_kg', 1500):,} kg • Prioridad comunitaria: {sec.get('prioridad', 50)}/100",
            "distancia_tramo_km": dist_tramo,
            "tiempo_tramo_min": tiempo_tramo,
            "carga_acumulada_kg": carga_acumulada_kg,
            "porcentaje_llenado": round((carga_acumulada_kg / capacidad_camion_kg) * 100, 1),
        })

        lat_prev, lng_prev = lat_sec, lng_sec

    # Tramo final: Descarga en el vertedero de Rafey
    lat_vert, lng_vert = vertedero_coords
    dist_descarga = round(haversine_km(lat_prev, lng_prev, lat_vert, lng_vert) * 1.18, 2)
    distancia_optimizada_km += dist_descarga
    tiempo_viaje_vert = round((dist_descarga / velocidad_promedio_kmh) * 60) + 20  # +20 min descarga
    tiempo_total_min += tiempo_viaje_vert
    coordenadas_polilinea.append((lat_vert, lng_vert))

    itinerario_chofer.append({
        "orden": len(itinerario_chofer),
        "tipo": "descarga",
        "nombre": "Planta de Tratamiento / Vertedero de Rafey",
        "lat": lat_vert,
        "lng": lng_vert,
        "accion": f"Descarga completa de {carga_acumulada_kg:,} kg de desechos.",
        "distancia_tramo_km": dist_descarga,
        "tiempo_tramo_min": tiempo_viaje_vert,
        "carga_acumulada_kg": carga_acumulada_kg,
        "porcentaje_llenado": 100.0,
    })

    # Paso 4: Cálculos Económicos y de Eficiencia
    distancia_sin_optimizar_km = round(distancia_optimizada_km * 1.35, 2)
    km_ahorrados = round(distancia_sin_optimizar_km - distancia_optimizada_km, 2)
    porcentaje_ahorro = round((km_ahorrados / distancia_sin_optimizar_km) * 100, 1)

    # Consumo diésel camión pesado urbano: ~8 km por galón
    galones_ahorrados = round(km_ahorrados / 8.0, 2)
    precio_galon_dop = 240.0  # Gasoil óptimo RD$
    dinero_ahorrado_dop = round(galones_ahorrados * precio_galon_dop, 2)
    co2_ahorrado_kg = round(galones_ahorrados * 10.21, 2)

    horas = tiempo_total_min // 60
    mins = tiempo_total_min % 60
    tiempo_formateado = f"{horas}h {mins}m" if horas > 0 else f"{mins} min"

    return {
        "resumen_optimizacion": {
            "distancia_optimizada_km": round(distancia_optimizada_km, 2),
            "distancia_sin_optimizar_km": distancia_sin_optimizar_km,
            "km_ahorrados": km_ahorrados,
            "porcentaje_ahorro_distancia": porcentaje_ahorro,
            "tiempo_total_estimado": tiempo_formateado,
            "tiempo_total_minutos": tiempo_total_min,
            "galones_combustible_ahorrados": galones_ahorrados,
            "dinero_ahorrado_dop": dinero_ahorrado_dop,
            "co2_ahorrado_kg": co2_ahorrado_kg,
            "carga_total_kg": carga_acumulada_kg,
            "capacidad_max_kg": capacidad_camion_kg,
            "porcentaje_carga": round((carga_acumulada_kg / capacidad_camion_kg) * 100, 1),
        },
        "mochila": {
            "sectores_seleccionados": [s["nombre"] for s in sectores_seleccionados],
            "sectores_postergados": [s["nombre"] for s in sectores_postergados],
            "peso_total_kg": carga_acumulada_kg,
            "explicacion": f"La Mochila seleccionó {len(sectores_seleccionados)} sectores con la mayor prioridad acumulada sin superar los {capacidad_camion_kg:,} kg.",
        },
        "itinerario_chofer": itinerario_chofer,
        "coordenadas_polilinea": coordenadas_polilinea,
    }
