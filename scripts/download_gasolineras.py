#!/usr/bin/env python3
"""
download_gasolineras.py (v3 — robusto, con caché + histórico)
----------------------------------------------------------------
Descarga precios de carburante país por país y genera gasolineras.json
para la app. Diseñado para que UN fallo puntual en un país (red caída,
feed roto, cambio de formato) NUNCA borre los datos de ese país del
resultado final — se sirve la última copia buena conocida, marcada como
"no fresca", en vez de dejar la app sin nada.

ARQUITECTURA
------------
cache_<PAIS>.json   -> última descarga que se consideró válida de ese país
                       (con fecha). Es la "red de seguridad".
historial_precios.json
                    -> por estación y combustible, un precio por día
                       (si hay varias descargas el mismo día, nos quedamos
                       con el PEOR precio del día, tal cual se pidió: así
                       el histórico nunca "esconde" una subida puntual).
                       Retención: RETENTION_DAYS días, se poda solo.
gasolineras.json    -> salida final para la app. Cada estación lleva:
                       - precios (los de hoy, frescos o de caché)
                       - tendencias (precio de ayer, delta, % y dirección)
                       además de un bloque "estado_paises" transparente:
                       qué país está fresco hoy y cuál se sirve de caché
                       (y desde cuándo), para que la app pueda avisar.

GUARDAS ANTI-DATOS-CORRUPTOS
-----------------------------
1) Si la descarga de un país falla (red) -> se usa la caché, se marca stale.
2) Si la descarga "funciona" pero devuelve 0 estaciones -> se trata como
   fallo (no se pisa la caché con un vacío).
3) Si la descarga devuelve MENOS DE LA MITAD de estaciones que la caché
   anterior -> se considera sospechosa (típico de un cambio de formato del
   feed que rompe el parser silenciosamente, como pasó con Italia) y se
   descarta también, preferimos la caché a un dataset roto a medias.

Uso:
  pip install requests --break-system-packages
  python3 download_gasolineras.py
"""

import csv
import io
import json
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET

import requests

CONFIG_FILE = "config_gasolineras.json"
OUTPUT_FILE = "gasolineras.json"
HISTORIAL_FILE = "historial_precios.json"
CACHE_FILE_TMPL = "cache_{pais}.json"

RETENTION_DAYS = 45          # cuántos días de histórico se conservan por estación/combustible
MIN_RATIO_VS_CACHE = 0.5     # si la descarga nueva trae menos de esta fracción de la caché, se descarta
TREND_EPSILON = 0.001        # por debajo de esto en € se considera "estable", no ruido de redondeo

NOT_AVAILABLE_YET = {
    "DE": "Tankerkönig exige API key personal y prohíbe descargar/espejar todas las "
          "estaciones; solo permite consultas puntuales por radio bajo acción del "
          "usuario. Requiere integración distinta (llamada en vivo desde el HTML "
          "con tu propia key), no un dump periódico como este script.",
    "AT": "E-Control (Spritpreisrechner) tiene API pero no se han confirmado "
          "condiciones de descarga masiva. Pendiente de investigar.",
    "CH": "No se ha encontrado fuente pública oficial de precios de carburante "
          "en Suiza con dataset descargable.",
    "AND": "No se ha encontrado fuente pública oficial de precios de carburante "
           "en Andorra con dataset descargable.",
}


def _num(raw):
    if raw is None:
        return None
    raw = str(raw).strip().replace(",", ".")
    if not raw:
        return None
    try:
        return round(float(raw), 3)
    except ValueError:
        return None


def today_str():
    return datetime.now(timezone.utc).date().isoformat()


# ============================================================
# ESPAÑA
# ============================================================
ES_URL = "https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/PreciosCarburantes/EstacionesTerrestres/"
ES_PRICE_FIELDS = {
    "Precio Gasolina 95 E5": "gasolina95",
    "Precio Gasoleo A": "diesel",
    "Precio Gasoleo Premium": "dieselPlus",
    "Precio Gases licuados del petróleo": "glp",
    "Precio Gas Natural Comprimido": "gnc",
}


def fetch_es():
    resp = requests.get(ES_URL, timeout=60, headers={"User-Agent": "OraculoVia/1.0"})
    resp.raise_for_status()
    stations = resp.json().get("ListaEESSPrecio", [])
    out = []
    for s in stations:
        lat, lon = _num(s.get("Latitud")), _num(s.get("Longitud (WGS84)") or s.get("Longitud"))
        if lat is None or lon is None:
            continue
        precios = {out_k: _num(s.get(src_k)) for src_k, out_k in ES_PRICE_FIELDS.items()}
        precios = {k: v for k, v in precios.items() if v is not None}
        if not precios:
            continue
        out.append({
            "pais": "ES", "id": f"ES-{s.get('IDEESS')}", "lat": lat, "lon": lon,
            "rotulo": (s.get("Rótulo") or "").strip().title(),
            "direccion": (s.get("Dirección") or "").strip().title(),
            "municipio": (s.get("Municipio") or "").strip().title(),
            "precios": precios,
        })
    return out


# ============================================================
# FRANCIA
# ============================================================
FR_URL = "https://donnees.roulez-eco.fr/opendata/instantane"
FR_FUEL_MAP = {"1": "diesel", "2": "gasolina95", "5": "gasolina95E10", "6": "gasolina98", "4": "glp", "3": "e85"}


def fetch_fr():
    resp = requests.get(FR_URL, timeout=90, headers={"User-Agent": "OraculoVia/1.0"})
    resp.raise_for_status()
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    xml_name = [n for n in zf.namelist() if n.lower().endswith(".xml")][0]
    root = ET.fromstring(zf.read(xml_name))

    out = []
    for pdv in root.findall("pdv"):
        try:
            lat = int(pdv.get("latitude")) / 100000.0
            lon = int(pdv.get("longitude")) / 100000.0
        except (TypeError, ValueError):
            continue
        precios = {}
        for prix in pdv.findall("prix"):
            code = prix.get("id")
            valeur = _num(prix.get("valeur"))
            if code in FR_FUEL_MAP and valeur is not None:
                precios[FR_FUEL_MAP[code]] = valeur
        if not precios:
            continue
        adresse_el = pdv.find("adresse")
        ville_el = pdv.find("ville")
        out.append({
            "pais": "FR", "id": f"FR-{pdv.get('id')}", "lat": lat, "lon": lon,
            "rotulo": (pdv.get("pop") or "").strip().title(),
            "direccion": (adresse_el.text or "").strip().title() if adresse_el is not None and adresse_el.text else "",
            "municipio": (ville_el.text or "").strip().title() if ville_el is not None and ville_el.text else "",
            "precios": precios,
        })
    return out


# ============================================================
# ITALIA
# ============================================================
IT_ANAGRAFICA_URL = "https://www.mimit.gov.it/images/exportCSV/anagrafica_impianti_attivi.csv"
IT_PREZZI_URL = "https://www.mimit.gov.it/images/exportCSV/prezzo_alle_8.csv"
IT_FUEL_MAP = {"benzina": "gasolina95", "gasolio": "diesel", "gpl": "glp", "metano": "gnc"}


def _detect_delimiter(sample_line):
    """El feed italiano ha cambiado de delimitador alguna vez sin avisar (fue lo que
    rompió la descarga a 0 estaciones). En vez de asumir '|' a ciegas, lo detectamos."""
    for delim in ("|", ";", ","):
        if sample_line.count(delim) >= 3:
            return delim
    return "|"


def fetch_it():
    ana_resp = requests.get(IT_ANAGRAFICA_URL, timeout=90, headers={"User-Agent": "OraculoVia/1.0"})
    ana_resp.raise_for_status()
    prz_resp = requests.get(IT_PREZZI_URL, timeout=90, headers={"User-Agent": "OraculoVia/1.0"})
    prz_resp.raise_for_status()

    ana_text = ana_resp.content.decode("utf-8", errors="ignore")
    prz_text = prz_resp.content.decode("utf-8", errors="ignore")
    ana_delim = _detect_delimiter(ana_text.split("\n", 1)[0])
    prz_delim = _detect_delimiter(prz_text.split("\n", 1)[0])

    ana_reader = csv.DictReader(io.StringIO(ana_text), delimiter=ana_delim)
    stations = {}
    for row in ana_reader:
        # los nombres de columna han variado de mayúsculas/minúsculas entre versiones del feed
        row = {k.strip().lower(): v for k, v in row.items() if k}
        idimp = row.get("idimpianto")
        lat, lon = _num(row.get("latitudine")), _num(row.get("longitudine"))
        if not idimp or lat is None or lon is None:
            continue
        stations[idimp] = {
            "pais": "IT", "id": f"IT-{idimp}", "lat": lat, "lon": lon,
            "rotulo": (row.get("bandiera") or "").strip().title(),
            "direccion": (row.get("indirizzo") or "").strip().title(),
            "municipio": (row.get("comune") or "").strip().title(),
            "precios": {},
        }

    prz_reader = csv.DictReader(io.StringIO(prz_text), delimiter=prz_delim)
    for row in prz_reader:
        row = {k.strip().lower(): v for k, v in row.items() if k}
        idimp = row.get("idimpianto")
        st = stations.get(idimp)
        if not st:
            continue
        carb = (row.get("desccarburante") or "").strip().lower()
        out_key = IT_FUEL_MAP.get(carb)
        precio = _num(row.get("prezzo"))
        if out_key and precio is not None:
            is_self = str(row.get("isself")) in ("1", "1.0", "true", "True")
            if out_key not in st["precios"] or is_self:
                st["precios"][out_key] = precio

    return [s for s in stations.values() if s["precios"]]


FETCHERS = {"ES": fetch_es, "FR": fetch_fr, "IT": fetch_it}


# ============================================================
# CAPA DE CACHÉ POR PAÍS (la red de seguridad)
# ============================================================
def cache_path(pais):
    return CACHE_FILE_TMPL.format(pais=pais)


def load_cache(pais):
    try:
        with open(cache_path(pais), "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        print(f"  [{pais}] caché corrupta, se ignora", file=sys.stderr)
        return None


def save_cache(pais, estaciones):
    payload = {"fecha": today_str(), "num_estaciones": len(estaciones), "estaciones": estaciones}
    with open(cache_path(pais), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))


def get_country_data(pais):
    """Devuelve (estaciones, meta) para un país, con toda la lógica de guardas.
    meta = {"fresco": bool, "fecha_datos": str, "motivo": str|None}"""
    cache = load_cache(pais)
    cache_estaciones = cache["estaciones"] if cache else []
    cache_fecha = cache["fecha"] if cache else None

    fetcher = FETCHERS.get(pais)
    if not fetcher:
        return [], {"fresco": False, "fecha_datos": None, "motivo": "país sin fetcher implementado"}

    try:
        nuevas = fetcher()
    except Exception as e:  # noqa: BLE001 - queremos capturar cualquier fallo de red/parseo y degradar con gracia
        print(f"  [{pais}] ERROR al descargar: {e}", file=sys.stderr)
        if cache_estaciones:
            print(f"  [{pais}] usando caché del {cache_fecha} ({len(cache_estaciones)} estaciones)")
            return cache_estaciones, {"fresco": False, "fecha_datos": cache_fecha, "motivo": f"error de red: {e}"}
        print(f"  [{pais}] sin caché previa disponible, país queda vacío este ciclo")
        return [], {"fresco": False, "fecha_datos": None, "motivo": f"error de red y sin caché previa: {e}"}

    if not nuevas:
        print(f"  [{pais}] la descarga devolvió 0 estaciones — se descarta como fallo transitorio")
        if cache_estaciones:
            return cache_estaciones, {"fresco": False, "fecha_datos": cache_fecha, "motivo": "descarga devolvió 0 estaciones"}
        return [], {"fresco": False, "fecha_datos": None, "motivo": "descarga devolvió 0 estaciones y sin caché previa"}

    if cache_estaciones and len(nuevas) < len(cache_estaciones) * MIN_RATIO_VS_CACHE:
        print(f"  [{pais}] descarga sospechosa: {len(nuevas)} estaciones vs {len(cache_estaciones)} en caché "
              f"(< {int(MIN_RATIO_VS_CACHE*100)}%) — probablemente el feed cambió de formato. Se descarta, se mantiene caché.")
        return cache_estaciones, {"fresco": False, "fecha_datos": cache_fecha,
                                   "motivo": f"descarga sospechosa ({len(nuevas)} vs {len(cache_estaciones)} en caché)"}

    print(f"  [{pais}] {len(nuevas)} estaciones válidas — caché actualizada")
    save_cache(pais, nuevas)
    return nuevas, {"fresco": True, "fecha_datos": today_str(), "motivo": None}


# ============================================================
# HISTÓRICO DE PRECIOS + TENDENCIA
# ============================================================
def load_historial():
    try:
        with open(HISTORIAL_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def prune_historial_entry(entries, cutoff):
    return [e for e in entries if e[0] >= cutoff]


def update_historial_and_get_trend(historial, station_id, field, price, today, cutoff):
    """Aplica la regla: si ya hay un registro de HOY para esta estación/combustible,
    nos quedamos con el peor precio (el más alto) del día en vez de sobreescribir.
    Devuelve la tendencia frente al día anterior registrado (no necesariamente ayer
    en el calendario, sino el último día distinto de hoy que tengamos)."""
    st_hist = historial.setdefault(station_id, {})
    entries = st_hist.setdefault(field, [])

    if entries and entries[-1][0] == today:
        entries[-1][1] = max(entries[-1][1], price)
    else:
        entries.append([today, price])

    entries[:] = prune_historial_entry(entries, cutoff)

    trend = None
    if len(entries) >= 2:
        prev_price = entries[-2][1]
        curr_price = entries[-1][1]
        delta = round(curr_price - prev_price, 3)
        pct = round((delta / prev_price) * 100, 2) if prev_price else None
        if delta > TREND_EPSILON:
            direccion = "sube"
        elif delta < -TREND_EPSILON:
            direccion = "baja"
        else:
            direccion = "estable"
        trend = {"anterior": prev_price, "fecha_anterior": entries[-2][0], "delta": delta, "pct": pct, "direccion": direccion}

    return trend


def cleanup_historial(historial):
    """Quita estaciones que ya no tienen ninguna serie de precios tras la poda
    (p.ej. llevan más de RETENTION_DAYS sin aparecer en ninguna descarga)."""
    dead = [sid for sid, fields in historial.items() if not any(fields.values())]
    for sid in dead:
        del historial[sid]


def save_historial(historial):
    with open(HISTORIAL_FILE, "w", encoding="utf-8") as f:
        json.dump(historial, f, ensure_ascii=False, separators=(",", ":"))


# ============================================================
# MAIN
# ============================================================
def load_config():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"No existe {CONFIG_FILE}, uso lista por defecto ES/FR/IT.")
        return {"paises_activos": ["ES", "FR", "IT"]}


def main():
    cfg = load_config()
    paises = cfg.get("paises_activos", [])
    today = today_str()
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=RETENTION_DAYS)).isoformat()

    historial = load_historial()

    todas = []
    estado_paises = {}
    no_disponibles = {}

    for pais in paises:
        if pais in FETCHERS:
            print(f"[{pais}] procesando...")
            estaciones, meta = get_country_data(pais)
            estado_paises[pais] = meta

            for s in estaciones:
                tendencias = {}
                for field, price in s["precios"].items():
                    trend = update_historial_and_get_trend(historial, s["id"], field, price, today, cutoff)
                    if trend:
                        tendencias[field] = trend
                s["tendencias"] = tendencias
                s["fecha_datos"] = meta["fecha_datos"]
                s["fresco"] = meta["fresco"]
                todas.append(s)

        elif pais in NOT_AVAILABLE_YET:
            no_disponibles[pais] = NOT_AVAILABLE_YET[pais]
            print(f"[{pais}] omitido: {NOT_AVAILABLE_YET[pais]}")
        else:
            print(f"[{pais}] país no reconocido, omitido")

    cleanup_historial(historial)
    save_historial(historial)

    payload = {
        "actualizado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "paises_incluidos": [p for p in paises if p in FETCHERS],
        "paises_no_disponibles": no_disponibles,
        "estado_paises": estado_paises,
        "num_estaciones": len(todas),
        "estaciones": todas,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    print(f"\nEscrito {OUTPUT_FILE}: {len(todas)} estaciones")
    for pais, meta in estado_paises.items():
        estado_txt = "FRESCO" if meta["fresco"] else f"CACHÉ ({meta['fecha_datos'] or 'sin datos'}) — {meta['motivo']}"
        print(f"  [{pais}] {estado_txt}")
    if no_disponibles:
        print(f"Pendientes sin fuente gratuita de bulk: {list(no_disponibles.keys())}")


if __name__ == "__main__":
    main()
