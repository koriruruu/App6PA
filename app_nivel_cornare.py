import os
import numpy as np
import pandas as pd
import requests
import streamlit as st
import urllib3
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
# Estilos CSS Personalizados (Gama de Verdes Ambiental - Sin tonos café)
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
        padding: 20px;
        text-align: center;
        box-shadow: 0 2px 6px rgba(0,0,0,0.1);
    }
    
    .card-metric-val {
        font-size: 32px;
        font-weight: bold;
        color: #A5D6A7;
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


# ------------------------------------------------------------------
# Encabezado Web con Logo y Título
# ------------------------------------------------------------------
col_logo, col_titulo = st.columns([1, 4])

with col_logo:
    if os.path.exists("logo.png"):
        st.image("logo.png", use_container_width=True)
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
# Barra de Filtro de Búsqueda (Estilo Web)
# ------------------------------------------------------------------
with st.container():
    col_f1, col_f2 = st.columns([3, 1])
    with col_f1:
        rango_fechas = st.date_input(
            "Rango de Fechas para Consulta:",
            value=(pd.to_datetime("2026-08-20"), pd.to_datetime("2026-08-25")),
            format="YYYY/MM/DD",
        )
    with col_f2:
        st.write("##")
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
# Renderizado Dashboard principal (Grid Tipo MARCO)
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

    st.markdown("---")

    # Fila Principal: Mapa, Galería y Tarjeta Promedio (Estilo Web MARCO)
    c_map, c_galeria, c_info = st.columns([1.2, 1.2, 0.8])

    with c_map:
        st.markdown("**📌 Ubicación Geográfica**")
        st.map(pd.DataFrame({"lat": [lat], "lon": [lon]}), zoom=12)
        st.caption("Latitud, Longitud: " + f"{lat}, {lon}")

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
            st.markdown(f"<p style='text-align:center; color:#4E3629; font-weight:bold;'>{st.session_state.img_idx + 1} / {len(lista_imagenes)}</p>", unsafe_allow_html=True)
        with b_der:
            if st.button("▶", key="next_img", use_container_width=True):
                st.session_state.img_idx = (st.session_state.img_idx + 1) % len(lista_imagenes)
                st.rerun()

    with c_info:
        st.markdown(f"""
        <div class="card-info">
            <h4 style="margin:0; color:#1E4D2B;">Estación #{CODIGO_ESTACION}</h4>
            <p style="margin:5px 0; font-size:13px; color:#555;"><b>Red:</b> Hidrológica Red Agua</p>
            <p style="margin:0; font-size:13px; color:#555;"><b>Lugar:</b> Guarne, Quebrada La Brizuela</p>
        </div>
        """, unsafe_allow_html=True)

        st.markdown(f"""
        <div class="card-metric">
            <div style="font-size:14px; text-transform:uppercase; letter-spacing:1px;">Nivel Promedio</div>
            <div class="card-metric-val">{df['nivel'].mean():.1f} cm</div>
        </div>
        """, unsafe_allow_html=True)

    # Fila Secundaria: Gráfico y Métricas de Calidad
    st.markdown("### 📈 Nivel Corriente de Agua")
    st.line_chart(df.set_index("fecha")["nivel"], color="#1E4D2B")

    # Detalles de Calidad y Descarga
    m1, m2, m3 = st.columns(3)
    m1.metric("Total Lecturas", len(df))
    m2.metric("Índice de Calidad", f"{indice_calidad} / 100")
    m3.metric("Outliers Detectados", n_outliers)

    with st.expander("Ver Datos Crudos y Exportar"):
        st.dataframe(df, use_container_width=True)
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Descargar CSV", csv, file_name=f"nivel_estacion_{CODIGO_ESTACION}.csv", mime="text/csv")

else:
    st.info("Selecciona el rango de fechas en la parte superior y haz clic en **Consultar Estación**.")
