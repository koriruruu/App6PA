import os
import numpy as np
import pandas as pd
import requests
import streamlit as st
import urllib3
import plotly.graph_objects as go
from PIL import Image

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ------------------------------------------------------------------
# Configuración inicial y constantes
# ------------------------------------------------------------------
NOMBRE_ESTUDIANTE = "Valery Ochoa"
CODIGO_ESTACION = "9"
CALIDAD_DEFECTO = 1

LAT_DEFECTO = 6.2773
LON_DEFECTO = -75.4475

API_BASE_URL = "https://marco.cornare.gov.co/api/v1/estaciones"

LLAVE_FECHA = "level_date"
LLAVE_VALOR = "level"
CANDIDATOS_LAT = ["lat", "latitude", "latitud"]
CANDIDATOS_LON = ["lng", "lon", "longitude", "longitud"]

st.set_page_config(page_title="MARCO 2.0 — Monitoreo de Ríos", page_icon="🌿", layout="wide")

# ------------------------------------------------------------------
# Estilos CSS Personalizados (Gama de Verdes Ambiental)
# ------------------------------------------------------------------
st.markdown("""
<style>
    /* Estilos globales y paleta de colores basada en verdes */
    :root {
        --verde-oscuro: #1E4D2B;
        --verde-principal: #2E7D32;
        --verde-claro: #E8F5E9;
        --verde-texto: #1B5E20;
    }
    
    .stApp {
        background-color: #F8F9F8;
    }

    /* Barra Superior de Navegación */
    .nav-bar {
        background-color: var(--verde-oscuro);
        padding: 12px 24px;
        border-radius: 10px;
        color: white;
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 20px;
    }
    
    .nav-title {
        font-size: 22px;
        font-weight: bold;
        color: #FFFFFF;
        margin: 0;
    }
    
    .nav-sub {
        font-size: 13px;
        color: #C8E6C9;
    }

    /* Badge para el nombre del estudiante */
    .student-badge {
        background-color: var(--verde-claro);
        color: var(--verde-texto);
        padding: 6px 14px;
        border-radius: 15px;
        font-size: 13px;
        font-weight: 600;
        border: 1px solid #A5D6A7;
    }

    /* Tarjetas tipo Dashboard */
    .card-info {
        background-color: #FFFFFF;
        border-left: 5px solid var(--verde-principal);
        border-radius: 8px;
        padding: 15px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.05);
        margin-bottom: 10px;
    }
    
    .card-metric {
        background-color: var(--verde-oscuro);
        color: white;
        border-radius: 8px;
        padding: 15px;
        text-align: center;
        box-shadow: 0 2px 6px rgba(0,0,0,0.1);
    }
    
    .card-metric-val {
        font-size: 28px;
        font-weight: bold;
        color: #A5D6A7;
    }

    /* Personalización del botón primario */
    div.stButton > button[kind="primary"] {
        background-color: var(--verde-oscuro) !important;
        color: #FFFFFF !important;
        border: none !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
        transition: all 0.2s ease-in-out !important;
    }

    div.stButton > button[kind="primary"]:hover {
        background-color: var(--verde-principal) !important;
        box-shadow: 0 4px 12px rgba(46, 125, 50, 0.25) !important;
    }
</style>
""", unsafe_allow_html=True)

# ------------------------------------------------------------------
# Funciones de consulta
# ------------------------------------------------------------------
def obtener_serie_nivel(codigo_estacion, desde, hasta, calidad=1, timeout=30):
    url = f"{API_BASE_URL}/{codigo_estacion}/nivel"
    params = {"desde": desde, "hasta": hasta, "calidad": calidad}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
    }
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=timeout, verify=False)
        if resp.status_code == 200:
            return resp.json(), None
        return None, f"HTTP {resp.status_code}"
    except requests.exceptions.RequestException as e:
        return None, f"Error de red: {e}"


def obtener_todas_las_paginas(datos_json, timeout=30):
    registros = list(datos_json.get("values", []))
    siguiente_url = datos_json.get("next")
    while siguiente_url:
        try:
            resp = requests.get(siguiente_url, timeout=timeout, verify=False)
        except requests.exceptions.RequestException:
            break
        if resp.status_code != 200:
            break
        pagina = resp.json()
        registros.extend(pagina.get("values", []))
        siguiente_url = pagina.get("next")
    return registros


def detectar_coordenadas(datos_json):
    if not isinstance(datos_json, dict):
        return LAT_DEFECTO, LON_DEFECTO, False

    lat = next((datos_json[k] for k in CANDIDATOS_LAT if k in datos_json), None)
    lon = next((datos_json[k] for k in CANDIDATOS_LON if k in datos_json), None)

    if lat is not None and lon is not None:
        try:
            return float(lat), float(lon), True
        except (TypeError, ValueError):
            pass
    return LAT_DEFECTO, LON_DEFECTO, False


def calcular_indice_calidad(df):
    if df.empty or len(df) < 2:
        return 0.0, 0, 0

    df_idx = df.set_index("fecha")
    frecuencia_tipica = df["fecha"].diff().dropna().mode()
    if len(frecuencia_tipica) == 0:
        return 0.0, 0, 0
    frecuencia_tipica = frecuencia_tipica[0]

    rango_completo = pd.date_range(start=df_idx.index.min(), end=df_idx.index.max(), freq=frecuencia_tipica)
    esperados = len(rango_completo)
    huecos = esperados - len(df_idx)
    completitud = max(0.0, 1 - (huecos / esperados)) if esperados > 0 else 0.0

    Q1, Q3 = df["nivel"].quantile(0.25), df["nivel"].quantile(0.75)
    IQR = Q3 - Q1
    lim_inf, lim_sup = Q1 - 1.5 * IQR, Q3 + 1.5 * IQR
    es_outlier = (df["nivel"] < lim_inf) | (df["nivel"] > lim_sup) | (df["nivel"] < 0)
    proporcion_outliers = es_outlier.mean()

    indice = (completitud * 0.7 + (1 - proporcion_outliers) * 0.3) * 100
    return round(indice, 1), int(huecos), int(es_outlier.sum())


def obtener_estado_semaforo(nivel_max, nivel_actual):
    UMBRAL_PREVENCION = 50.0
    UMBRAL_ALERTA = 80.0

    if nivel_max >= UMBRAL_ALERTA:
        return {
            "color": "#FFEBEE",
            "borde": "#D32F2F",
            "texto_color": "#C62828",
            "icono": "🚨",
            "titulo": "ALERTA ROJA — Riesgo de Desbordamiento",
            "mensaje": f"El nivel máximo registrado ({nivel_max:.1f} cm) ha superado el umbral crítico de {UMBRAL_ALERTA} cm. Se recomienda activar protocolos de monitoreo continuo en comunidades ribereñas.",
        }
    elif nivel_max >= UMBRAL_PREVENCION:
        return {
            "color": "#FFFDE7",
            "borde": "#FBC02D",
            "texto_color": "#F57F17",
            "icono": "⚠️",
            "titulo": "ALERTA AMARILLA — Nivel en Incremento",
            "mensaje": f"El nivel ha alcanzado los {nivel_max:.1f} cm, superando el nivel de prevención ({UMBRAL_PREVENCION} cm). Mantener observación por posibles precipitaciones en la cuenca alta de Guarne.",
        }
    else:
        return {
            "color": "#E8F5E9",
            "borde": "#2E7D32",
            "texto_color": "#1B5E20",
            "icono": "✅",
            "titulo": "ESTADO VERDE — Nivel Normal",
            "mensaje": f"La corriente se mantiene dentro del cauce habitualmente seguro. Nivel actual en {nivel_actual:.1f} cm y máximo registrado en {nivel_max:.1f} cm.",
        }


def obtener_interpretacion_humana(nivel):
    if nivel < 30:
        return "🚶 <b>Flujo Bajo:</b> El nivel del agua está bajo el estándar promedio. Sin ningún riesgo.", "#1B5E20"
    elif nivel < 50:
        return "💧 <b>Flujo Normal:</b> Nivel promedio seguro dentro del cauce natural de la quebrada.", "#2E7D32"
    elif nivel < 80:
        return "🌊 <b>Flujo Elevado:</b> El agua alcanza una altura de precaución. Monitorear orillas.", "#F57F17"
    else:
        return "🚨 <b>Flujo Crítico:</b> Riesgo alto. El agua supera zonas bajas y amenaza desbordamiento.", "#C62828"


def obtener_alerta_o_curiosidad(df, UMBRAL_ALERTA=80.0):
    df_alertas = df[df["nivel"] >= UMBRAL_ALERTA]
    
    if not df_alertas.empty:
        ultima_alerta = df_alertas.iloc[-1]
        fecha_str = ultima_alerta["fecha"].strftime("%d/%m %H:%M")
        nivel_critico = ultima_alerta["nivel"]
        
        return {
            "titulo": "🚨 Último Nivel Crítico",
            "valor": f"{nivel_critico:.1f} cm",
            "subtexto": f"Detectado el {fecha_str}",
            "color_borde": "#D32F2F",
            "color_texto": "#C62828"
        }
    else:
        return {
            "titulo": "💡 Dato Curioso de la Cuenca",
            "valor": "Sin Alertas",
            "subtexto": "La quebrada La Brizuela es un afluente clave del río Negro en Guarne.",
            "color_borde": "#2E7D32",
            "color_texto": "#1E4D2B"
        }

# ------------------------------------------------------------------
# Encabezado Web con Logo y Título
# ------------------------------------------------------------------
col_logo, col_titulo = st.columns([1, 4])

with col_logo:
    if os.path.exists("imagenes/logo.png"):
        st.image("imagenes/logo.png", use_container_width=True)
    else:
        st.markdown("<div style='background-color:#E8F5E9; padding:20px; border-radius:8px; text-align:center; color:#1E4D2B;'><b>[Logo aquí]</b></div>", unsafe_allow_html=True)

with col_titulo:
    st.markdown(f"""
    <div class="nav-bar">
        <div>
            <div class="nav-title">🌿 MARCO 2.0 <span style="font-size:14px; font-weight:normal; opacity:0.8;">by Valo</span></div>
            <div class="nav-sub">Sistema de Monitoreo Ambiental de Ríos y Quebradas — CORNARE</div>
        </div>
        <div style="text-align:right;">
            <span class="student-badge">Estudiante: {NOMBRE_ESTUDIANTE}</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

# ------------------------------------------------------------------
# Barra de Filtro de Búsqueda
# ------------------------------------------------------------------
col_fechas, col_btn = st.columns([3.8, 1.2], vertical_alignment="bottom")

with col_fechas:
    rango_fechas = st.date_input(
        "📅 Selecciona el Rango de Fechas para Consulta:",
        value=(pd.to_datetime("2026-08-20"), pd.to_datetime("2026-08-25")),
        format="YYYY/MM/DD",
    )

with col_btn:
    consultar = st.button("🔍 Consultar Estación", type="primary", use_container_width=True)

# Manejo de consulta
if consultar:
    if isinstance(rango_fechas, tuple) and len(rango_fechas) == 2:
        fecha_desde = rango_fechas[0].strftime("%Y-%m-%d")
        fecha_hasta = rango_fechas[1].strftime("%Y-%m-%d")

        with st.spinner("Conectando con la red de estaciones..."):
            datos_crudos, error = obtener_serie_nivel(CODIGO_ESTACION, fecha_desde, fecha_hasta, CALIDAD_DEFECTO)

        if error:
            st.session_state["error"] = error
            st.session_state["df"] = None
        else:
            registros = obtener_todas_las_paginas(datos_crudos)
            if not registros:
                st.session_state["error"] = "No se encontraron registros para la fecha seleccionada."
                st.session_state["df"] = None
            else:
                df = pd.DataFrame(registros)
                df = df.rename(columns={LLAVE_FECHA: "fecha", LLAVE_VALOR: "nivel"})
                df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
                df["nivel"] = pd.to_numeric(df["nivel"], errors="coerce")
                df = df.dropna(subset=["fecha", "nivel"]).sort_values("fecha").reset_index(drop=True)

                lat, lon, coords_reales = detectar_coordenadas(datos_crudos)
                indice_calidad, huecos, n_outliers = calcular_indice_calidad(df)

                st.session_state["df"] = df
                st.session_state["lat"] = lat
                st.session_state["lon"] = lon
                st.session_state["coords_reales"] = coords_reales
                st.session_state["indice_calidad"] = indice_calidad
                st.session_state["huecos"] = huecos
                st.session_state["n_outliers"] = n_outliers
                st.session_state["error"] = None

# ------------------------------------------------------------------
# Renderizado Dashboard principal
# ------------------------------------------------------------------
if st.session_state.get("error"):
    st.error(f"❌ {st.session_state['error']}")

elif st.session_state.get("df") is not None:
    df = st.session_state["df"]
    lat = st.session_state["lat"]
    lon = st.session_state["lon"]
    coords_reales = st.session_state["coords_reales"]
    indice_calidad = st.session_state["indice_calidad"]
    huecos = st.session_state["huecos"]
    n_outliers = st.session_state["n_outliers"]

    nivel_actual = df["nivel"].iloc[-1]
    nivel_maximo = df["nivel"].max()
    nivel_minimo = df["nivel"].min()
    semaforo = obtener_estado_semaforo(nivel_maximo, nivel_actual)

    st.markdown("---")

    # 🚦 Semáforo Hidrológico
    st.markdown(
        f"""
    <div style="background-color:{semaforo['color']}; border-left:6px solid {semaforo['borde']}; padding:15px 20px; border-radius:10px; margin-bottom:20px;">
        <h4 style="margin:0; color:{semaforo['texto_color']};">{semaforo['icono']} {semaforo['titulo']}</h4>
        <p style="margin:5px 0 0 0; color:#333333; font-size:14px;">{semaforo['mensaje']}</p>
    </div>
    """,
        unsafe_allow_html=True,
    )

    # Fila Principal: Mapa, Galería y Tarjetas
    c_map, c_galeria, c_info = st.columns([1.2, 1.2, 0.8])

    with c_map:
        st.markdown("**📌 Ubicación Geográfica**")
        st.map(pd.DataFrame({"lat": [lat], "lon": [lon]}), zoom=12)
        st.caption(f"Latitud, Longitud: {lat}, {lon}")

    with c_galeria:
        st.markdown("**📷 Desliza para ver la ubicación física del sensor**")
        lista_imagenes = [
            "imagenes/img1.png",
            "imagenes/img2.png",
            "imagenes/img3.png",
            "imagenes/img4.png",
        ]

        if "img_idx" not in st.session_state:
            st.session_state.img_idx = 0

        ruta_img = lista_imagenes[st.session_state.img_idx]
        if os.path.exists(ruta_img):
            img = Image.open(ruta_img)
            st.image(img, use_container_width=True)
        else:
            st.info(f"Imagen en `{ruta_img}` lista para cargarse.")

        b_izq, b_cnt, b_der = st.columns([1, 2, 1])
        with b_izq:
            if st.button("◀", key="prev_img", use_container_width=True):
                st.session_state.img_idx = (st.session_state.img_idx - 1) % len(lista_imagenes)
                st.rerun()
        with b_cnt:
            st.markdown(
                f"<p style='text-align:center; color:#1B5E20; font-weight:bold;'>{st.session_state.img_idx + 1} / {len(lista_imagenes)}</p>",
                unsafe_allow_html=True,
            )
        with b_der:
            if st.button("▶", key="next_img", use_container_width=True):
                st.session_state.img_idx = (st.session_state.img_idx + 1) % len(lista_imagenes)
                st.rerun()

    with c_info:
        # Tarjeta 1: Info Estación
        st.markdown(
            f"""
        <div class="card-info">
            <h4 style="margin:0; color:#1E4D2B;">Estación #{CODIGO_ESTACION}</h4>
            <p style="margin:5px 0; font-size:13px; color:#555;"><b>Red:</b> Hidrológica Red Agua</p>
            <p style="margin:0; font-size:13px; color:#555;"><b>Lugar:</b> Guarne, Quebrada La Brizuela</p>
        </div>
        """,
            unsafe_allow_html=True,
        )

        # Tarjeta 2: Nivel Promedio
        st.markdown(
            f"""
        <div class="card-metric" style="margin-bottom: 10px;">
            <div style="font-size:12px; text-transform:uppercase; letter-spacing:1px;">Nivel Promedio</div>
            <div class="card-metric-val">{df['nivel'].mean():.1f} cm</div>
        </div>
        """,
            unsafe_allow_html=True,
        )

        # Tarjeta 3: Nueva Tarjeta Dinámica (Alerta Máxima / Dato Curioso)
        info_extra = obtener_alerta_o_curiosidad(df)
        st.markdown(
            f"""
        <div style="background-color: #FFFFFF; border-left: 4px solid {info_extra['color_borde']}; border-radius: 8px; padding: 12px; box-shadow: 0 2px 5px rgba(0,0,0,0.05); margin-bottom: 10px;">
            <div style="font-size:11px; text-transform:uppercase; font-weight:bold; color:{info_extra['color_texto']};">{info_extra['titulo']}</div>
            <div style="font-size:18px; font-weight:bold; color:#333; margin-top:2px;">{info_extra['valor']}</div>
            <div style="font-size:11px; color:#666; margin-top:2px;">{info_extra['subtexto']}</div>
        </div>
        """,
            unsafe_allow_html=True,
        )

        # Cálculo dinámico de tendencia
        if len(df) >= 2:
            diferencia = df["nivel"].iloc[-1] - df["nivel"].iloc[-2]
            if diferencia > 1.5:
                estado_flujo = "📈 Creciente (En ascenso)"
                color_flujo = "#C62828"
            elif diferencia < -1.5:
                estado_flujo = "📉 Recesión (Descendiendo)"
                color_flujo = "#1565C0"
            else:
                estado_flujo = "➡️ Estable"
                color_flujo = "#2E7D32"
            var_texto = f"{diferencia:+.1f} cm respecto a lectura previa"
        else:
            estado_flujo = "➡️ Estable"
            color_flujo = "#2E7D32"
            var_texto = "Sin suficientes datos"

        # Tarjeta 4: Comportamiento Reciente
        st.markdown(
            f"""
        <div style="background-color: #FFFFFF; border: 1px solid #E0E7E1; border-radius: 8px; padding: 12px; text-align: center; box-shadow: 0 2px 5px rgba(0,0,0,0.05);">
            <div style="font-size:11px; text-transform:uppercase; letter-spacing:1px; color:#555; font-weight:600;">Tendencia Actual</div>
            <div style="font-size:14px; font-weight:bold; color:{color_flujo}; margin-top:3px;">{estado_flujo}</div>
            <div style="font-size:10px; color:#777; margin-top:2px;">{var_texto}</div>
        </div>
        """,
            unsafe_allow_html=True,
        )

    # ------------------------------------------------------------------
    # Fila Secundaria: Gráficos y Métricas Unificadas (Sin Redundancia)
    # ------------------------------------------------------------------
    st.markdown("### 📊 Monitoreo Detallado del Nivel de Agua")

    col_plot_line, col_plot_gauge = st.columns([2.2, 1])

    with col_plot_line:
        max_y = max(100.0, float(df["nivel"].max()) + 15.0)
        fig_line = go.Figure()

        # Zonas de Control y Riesgo
        fig_line.add_hrect(
            y0=0, y1=50,
            fillcolor="rgba(46, 125, 50, 0.12)", line_width=0,
            annotation_text="Normal", annotation_position="top left"
        )
        fig_line.add_hrect(
            y0=50, y1=80,
            fillcolor="rgba(251, 192, 45, 0.15)", line_width=0,
            annotation_text="Prevención", annotation_position="top left"
        )
        fig_line.add_hrect(
            y0=80, y1=max_y,
            fillcolor="rgba(211, 47, 47, 0.12)", line_width=0,
            annotation_text="Alerta Crítica", annotation_position="top left"
        )

        # Serie Temporal
        fig_line.add_trace(go.Scatter(
            x=df["fecha"], y=df["nivel"], mode="lines", name="Nivel (cm)",
            line=dict(color="#1E4D2B", width=2.5),
            hovertemplate="<b>Fecha:</b> %{x|%d/%m %H:%M}<br><b>Nivel:</b> %{y:.1f} cm<extra></extra>"
        ))

        fig_line.update_layout(
            title="Serie Temporal con Umbrales de Control",
            xaxis_title="Fecha y Hora", yaxis_title="Nivel (cm)",
            yaxis=dict(range=[0, max_y]), margin=dict(l=10, r=10, t=40, b=10),
            hovermode="x unified", template="plotly_white", height=300
        )
        st.plotly_chart(fig_line, use_container_width=True)

    with col_plot_gauge:
        # Tacómetro para Nivel Actual
        fig_gauge = go.Figure(go.Indicator(
            mode="gauge+number+delta",
            value=nivel_actual,
            title={'text': "Nivel Actual (cm)", 'font': {'size': 14, 'color': "#1E4D2B"}},
            delta={'reference': df["nivel"].mean(), 'increasing': {'color': "#C62828"}, 'decreasing': {'color': "#1565C0"}},
            gauge={
                'axis': {'range': [0, max(100.0, float(nivel_maximo) + 10.0)]},
                'bar': {'color': "#1E4D2B"},
                'steps': [
                    {'range': [0, 50], 'color': '#E8F5E9'},
                    {'range': [50, 80], 'color': '#FFFDE7'},
                    {'range': [80, 150], 'color': '#FFEBEE'}
                ],
                'threshold': {'line': {'color': "red", 'width': 3}, 'thickness': 0.75, 'value': 80}
            }
        ))
        fig_gauge.update_layout(margin=dict(l=15, r=15, t=30, b=0), height=220, template="plotly_white")
        st.plotly_chart(fig_gauge, use_container_width=True)

        # Interpretación Unificada debajo del tacómetro
        texto_humano, color_humano = obtener_interpretacion_humana(nivel_actual)
        st.markdown(
            f"""
            <div style="background-color: #FFFFFF; border-left: 4px solid {color_humano}; padding: 8px 12px; border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
                <span style="font-size:12px; color:#333;">{texto_humano}</span>
            </div>
            """,
            unsafe_allow_html=True
        )

    # Métricas de Resumen Limpias
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Nivel Máximo", f"{nivel_maximo:.1f} cm")
    m2.metric("Nivel Mínimo", f"{nivel_minimo:.1f} cm")
    m3.metric("Calidad de Datos", f"{indice_calidad} / 100")
    m4.metric("Registros Leídos", f"{len(df)} datos")

    with st.expander("❓ ¿Cómo interpretar estos indicadores?"):
        st.markdown("""
        * **Tacómetro:** Muestra el valor en tiempo real comparado contra el promedio del período (variación Delta).
        * **Zonas de Control:** Verde (Seguro), Amarillo (Atención por lluvias), Rojo (Riesgo de desbordamiento).
        * **Índice de Calidad:** Evalúa la continuidad de los datos enviados por la estación hidrológica de CORNARE.
        """)

    with st.expander("Ver Datos Crudos y Exportar"):
        st.dataframe(df, use_container_width=True)
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇️ Descargar CSV",
            csv,
            file_name=f"nivel_estacion_{CODIGO_ESTACION}.csv",
            mime="text/csv",
        )

else:
    st.info("Selecciona el rango de fechas en la parte superior y haz clic en **Consultar Estación**.")
