#!/usr/bin/env python3
"""
download_peajes.py
-------------------
Descarga la UBICACIÓN de los peajes (barreras físicas y pórticos de flujo
libre) de ES/FR/IT desde OpenStreetMap vía Overpass API, y genera peajes.json
para la app.

IMPORTANTE — qué es y qué NO es este dato:
  - SÍ es real: la posición de cada peaje viene de OSM (igual que los radares).
  - NO es una tarifa oficial por tramo: no existe ese dato abierto en ningún
    país (investigado y documentado en download_gasolineras.py y en la
    conversación con el usuario). El coste que calcula la app es una
    ESTIMACIÓN con la tarifa media €/km de cada país, no el precio real del
    tramo exacto. Esto se etiqueta siempre como "≈ estimado" en la interfaz,
    nunca como precio oficial.

Fuente: Overpass API (overpass-api.de), consulta por país de:
  - barrier=toll_booth          (barreras físicas de peaje clásico)
  - highway=* + toll=yes con toll_booth cercano, y
  - barrier=toll_gantry / highway=toll_gantry (pórticos de peaje en "flujo
    libre" — cada vez más comunes en Francia e Italia, sin barrera física)

NOTA: Overpass es un servicio público compartido con normas de uso justo
(no golpear el servidor con muchas peticiones seguidas). Este script hace
UNA consulta por país, con pausa entre ellas, y está pensado para lanzarse
con poca frecuencia (semanal, no cada 3h como los precios de gasolina,
porque la ubicación de los peajes apenas cambia de un día para otro).

Uso:
  pip install requests --break-system-packages
  python3 download_peajes.py
"""

import json
import sys
import time
from datetime import datetime, timezone

import requests

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
CONFIG_FILE = "config_gasolineras.json"  # reutilizamos la misma lista de países activos
OUTPUT_FILE = "peajes.json"
CACHE_FILE_TMPL = "cache_peajes_{pais}.json"

# Tarifas medias €/km para turismo (clase 1 / clase A), IVA incluido cuando aplica.
# Fuentes contrastadas en la conversación (Ministerio de Transportes España,
# Vinci Autoroutes / prensa especializada Francia, ART + concesionarias Italia).
# Son promedios de RED, no de un tramo concreto: un tramo de montaña o un
# túnel específico puede costar bastante más. Por eso la app siempre marca
# el resultado como aproximado.
TARIFAS_MEDIAS_KM = {
    "ES": 0.10,
    "FR": 0.10,
    "IT": 0.09,
}

# Solo los países con peajes de pago relevantes y red de autopistas con OSM decente.
SUPPORTED_COUNTRIES = {"ES", "FR", "IT"}

OVERPASS_QUERY_TMPL = """
[out:json][timeout:120];
area["ISO3166-1"="{iso}"][admin_level=2]->.pais;
(
  node["barrier"="toll_booth"](area.pais);
  node["barrier"="toll_gantry"](area.pais);
  way["barrier"="toll_booth"](area.pais);
  node["highway"="toll_gantry"](area.pais);
);
out center;
"""


def fetch_overpass(iso):
    query = OVERPASS_QUERY_TMPL.format(iso=iso)
    resp = requests.post(OVERPASS_URL, data={"data": query}, timeout=150,
                          headers={"User-Agent": "OraculoVia/1.0"})
    resp.raise_for_status()
    data = resp.json()
    elements = data.get("elements", [])

    out = []
    for el in elements:
        if el.get("type") == "node":
            lat, lon = el.get("lat"), el.get("lon")
        else:
            center = el.get("center") or {}
            lat, lon = center.get("lat"), center.get("lon")
        if lat is None or lon is None:
            continue
        tags = el.get("tags", {})
        out.append({
            "pais": iso,
            "id": f"{iso}-peaje-{el.get('id')}",
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "nombre": tags.get("name") or tags.get("operator") or "",
            "via": tags.get("ref") or "",
            "tipo": "flujo_libre" if tags.get("barrier") == "toll_gantry" or tags.get("highway") == "toll_gantry" else "barrera",
        })
    return out


def cache_path(pais):
    return CACHE_FILE_TMPL.format(pais=pais)


def load_cache(pais):
    try:
        with open(cache_path(pais), "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save_cache(pais, peajes):
    payload = {"fecha": datetime.now(timezone.utc).date().isoformat(), "peajes": peajes}
    with open(cache_path(pais), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))


def get_country_peajes(pais):
    """Misma filosofía defensiva que en gasolineras: si Overpass falla o devuelve
    muy pocos resultados frente a la caché anterior, nos quedamos con la caché
    en vez de dejar el país sin peajes."""
    cache = load_cache(pais)
    cache_peajes = cache["peajes"] if cache else []
    cache_fecha = cache["fecha"] if cache else None

    try:
        nuevos = fetch_overpass(pais)
    except Exception as e:  # noqa: BLE001
        print(f"  [{pais}] ERROR Overpass: {e}", file=sys.stderr)
        if cache_peajes:
            print(f"  [{pais}] usando caché del {cache_fecha} ({len(cache_peajes)} peajes)")
            return cache_peajes, {"fresco": False, "fecha_datos": cache_fecha, "motivo": f"error Overpass: {e}"}
        return [], {"fresco": False, "fecha_datos": None, "motivo": f"error Overpass y sin caché previa: {e}"}

    if not nuevos or (cache_peajes and len(nuevos) < len(cache_peajes) * 0.5):
        motivo = "0 resultados" if not nuevos else f"caída sospechosa ({len(nuevos)} vs {len(cache_peajes)} en caché)"
        print(f"  [{pais}] descarga descartada: {motivo}")
        if cache_peajes:
            return cache_peajes, {"fresco": False, "fecha_datos": cache_fecha, "motivo": motivo}
        return [], {"fresco": False, "fecha_datos": None, "motivo": motivo}

    print(f"  [{pais}] {len(nuevos)} peajes válidos — caché actualizada")
    save_cache(pais, nuevos)
    return nuevos, {"fresco": True, "fecha_datos": datetime.now(timezone.utc).date().isoformat(), "motivo": None}


def load_config():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"paises_activos": ["ES", "FR", "IT"]}


def main():
    cfg = load_config()
    paises = [p for p in cfg.get("paises_activos", []) if p in SUPPORTED_COUNTRIES]

    todos = []
    estado_paises = {}
    for i, pais in enumerate(paises):
        print(f"[{pais}] consultando Overpass...")
        peajes, meta = get_country_peajes(pais)
        estado_paises[pais] = meta
        todos.extend(peajes)
        if i < len(paises) - 1:
            time.sleep(3)  # respeto al servicio público compartido de Overpass

    payload = {
        "actualizado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "paises_incluidos": paises,
        "tarifas_medias_km": {p: TARIFAS_MEDIAS_KM[p] for p in paises},
        "aviso": "Las ubicaciones son reales (OpenStreetMap). El coste que calcula la app "
                 "es una ESTIMACIÓN con la tarifa media del país, no la tarifa oficial del "
                 "tramo exacto — no existe ese dato abierto en ningún país. Tramos de montaña "
                 "o túneles concretos pueden costar bastante más que la media.",
        "estado_paises": estado_paises,
        "num_peajes": len(todos),
        "peajes": todos,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    print(f"\nEscrito {OUTPUT_FILE}: {len(todos)} peajes")
    for pais, meta in estado_paises.items():
        estado_txt = "FRESCO" if meta["fresco"] else f"CACHÉ ({meta['fecha_datos'] or 'sin datos'}) — {meta['motivo']}"
        print(f"  [{pais}] {estado_txt}")


if __name__ == "__main__":
    main()
