# Hayako • v4 (Edición Unificada)

Sistema inteligente de optimización logística, monitoreo satelital en tiempo real y asistencia al chofer para la recolección de residuos en Santiago de los Caballeros, República Dominicana.

---

## 🔍 Comparativa entre las Versiones y Mejoras Implementadas

| Característica | Versión Anterior | Nueva Versión Unificada |
|---|---|---|
| **Arquitectura de Flota** | 1 solo camión | **Multivehículo (4 camiones simultáneos en 4 sectores de Santiago)** |
| **Renderizado del Mapa** | Capa única (podía fallar y verse en blanco) | **Multi-Capa ultra-resistente con Leaflet + OpenStreetMap + CartoDB + Satelital con recálculo automático de dimensiones** |
| **Selector de Camión** | Estático | **Selector interactivo con vuelo de cámara suave (`flyTo`) al vehículo elegido** |
| **Modelos de Datos (`models.py`)** | Campos básicos de coordenadas | **Soporte de zonas horarias (`timezone.utc`), hash seguro PBKDF2 para PIN, centroides de sectores y confirmaciones comunitarias** |
| **Algoritmo de Dijkstra** | Aislado en memoria | **Integrado en `optimizacion.py`: distancias viales mínimas, cálculo entre depósito y sectores, y endpoints administrativos** |
| **Algoritmo de la Mochila (Knapsack)** | 0/1 por peso | **Soporta tanto peso de residuos (kg) como minutos de turno de trabajo, priorizando sectores con más reportes comunitarios** |
| **Simulador GPS (`simulate.py`)** | Hilo básico en segundo plano | **Controlador interactivo con comandos REST (pausar, reanudar, velocidad 2x, forzar retrasos, reiniciar)** |
| **Consola del Chofer (CarPlay Mode)** | Vista preliminar | **Navegación paso a paso (*turn-by-turn*), botón táctil gigante para registrar recogidas, anillo de carga tipo Apple Watch** |

---

## 🍎 Experiencia Visual y de Usuario (Apple HIG)

1. **Vidrio Esmerilado Translúcido (*Frosted Glassmorphism 32px*)**:
   - Tarjetas flotantes con desenfoque de fondo profundo y saturación al 200%.
   - Bordes redondeados continuos (*squircles* con `border-radius: 20px-26px`).
2. **Dynamic Island Superior**:
   - Telemetría en vivo con indicador LED pulsante verde/ámbar, estado de la flota y reloj sincronizado.
3. **Consola del Conductor (Modo Chofer)**:
   - Tarjeta oscura de alto contraste diseñada para montarse en el tablero del camión.
   - Indicador de próxima parada, distancia del tramo y botón de un toque para avanzar al siguiente sector.
4. **Selector de Capas del Mapa**:
   - En la esquina inferior derecha se puede alternar instantáneamente entre **🗺️ Estándar**, **🏙️ Limpio** y **🛰️ Satélite**.

---

## 🧠 ¿Cómo Funcionan los Algoritmos?

### 1. Algoritmo de Dijkstra ("Distra")
- **Problema:** Encontrar la ruta más corta y rápida por las calles reales de Santiago entre el depósito central y cualquier sector.
- **Funcionamiento:** Modela la ciudad como un grafo donde los sectores son nodos y las calles son aristas ponderadas con la distancia geodésica (fórmula de Haversine corregida por curvatura vial). Emplea una cola de prioridad (*min-heap*) para expandir siempre el camino con menor kilometraje acumulado aplicando relajación de aristas:
  $$d(v) = \min(d(v), d(u) + w(u, v))$$

### 2. Algoritmo de la Mochila ("Knapsack 0/1")
- **Problema:** Dado que el camión tiene una capacidad limitada (ej. 6,000 kg o minutos de turno), decidir qué combinación de sectores recoger para maximizar el beneficio sanitario y comunitario.
- **Funcionamiento:** Usa Programación Dinámica evaluando recursivamente la matriz de beneficio $DP[i][c]$:
  $$DP[i][c] = \max\Big(DP[i-1][c],\; DP[i-1][c - \text{costo}_i] + \text{valor}_i\Big)$$
  Donde el valor $v_i$ integra los reportes ciudadanos y la urgencia comunitaria acumulada.

---

## 🚀 Cómo Correr el Proyecto

1. Ve a la carpeta del proyecto en tu terminal:
   ```bash
   cd /Users/a1kokim/Documents/basura-app-v4
   ```

2. Inicia el servidor Flask:
   ```bash
   ./venv/bin/python3 app.py
   ```

3. Abre en tu navegador:
   ```text
   http://localhost:5050
   ```
