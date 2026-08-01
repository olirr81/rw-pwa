#!/usr/bin/env python3
"""
download_gasolineras.py (multi-país)
-------------------------------------
Descarga precios oficiales de carburantes de los países marcados como activos
en config_gasolineras.json (mismo patrón que el config de radares) y genera
UN gasolineras.json compacto para servir estático desde GitHub, igual que
radares.json.

Países soportados con dump completo gratuito (sin API key):
  ES  -> Ministerio para la Transición Ecológica
  FR  -> donnees.roulez-eco.fr (Ministère de l'Économie)
  IT  -> MIMIT (Ministero delle Imprese e del Made in Italy)

Países NO soportados todavía (sin fuente pública de descarga masiva gratuita):
  DE  -> Tankerkönig existe pero exige API key personal Y prohíbe expresamente
         hacer mirror de todas las estaciones (solo consultas puntuales por
         radio, bajo acción explícita del usuario). Replicar aquí el mismo
         patrón que ES/FR/IT violaría sus condiciones de uso y te banearían
         la key. Si lo quieres igualmente, hay que integrarlo como llamada
         "bajo demanda" desde el propio HTML (con tu key), no como descarga
         periódica en bruto — dímelo y lo montamos así, distinto al resto.
  AT  -> E-Control tiene API pero no he confirmado condiciones de bulk.
  CH, AND -> no se ha encontrado fuente pública oficial de precios.

Estos 4 países se dejan en el JSON de salida con nota explicando por qué,
para que no se pierda el requisito y quede trazado.

Uso:
  pip install requests --break-system-packages
  python3 download_gasolineras.py
  -> lee config_gasolineras.json, genera gasolineras.json
"""

import csv
import io
import json
import sys
import zipfile
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

import requests

CONFIG_FILE = "config_gasolineras.json"
OUTPUT_FILE = "gasolineras.json"

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


def _num(raw):
    if not raw:
        return None
    raw = str(raw).strip().replace(",", ".")
    if not raw:
        return None
    try:
        return round(float(raw), 3)
    except ValueError:
        return None


def fetch_es():
    print("  [ES] descargando feed del Ministerio...")
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
    print(f"  [ES] {len(out)} estaciones válidas")
    return out


# ============================================================
# FRANCIA
# ============================================================
FR_URL = "https://donnees.roulez-eco.fr/opendata/instantane"
# El feed francés da el precio directo en euros (ej. valeur="1.685"), y usa
# códigos de carburante numéricos: 1=Gazole 2=SP95 3=E85 4=GPLc 5=E10 6=SP98
FR_FUEL_MAP = {"1": "diesel", "2": "gasolina95", "5": "gasolina95E10", "6": "gasolina98", "4": "glp", "3": "e85"}


def fetch_fr():
    print("  [FR] descargando ZIP de donnees.roulez-eco.fr...")
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
    print(f"  [FR] {len(out)} estaciones válidas")
    return out


# ============================================================
# ITALIA
# ============================================================
IT_ANAGRAFICA_URL = "https://www.mimit.gov.it/images/exportCSV/anagrafica_impianti_attivi.csv"
IT_PREZZI_URL = "https://www.mimit.gov.it/images/exportCSV/prezzo_alle_8.csv"
IT_FUEL_MAP = {
    "benzina": "gasolina95", "gasolio": "diesel", "gpl": "glp", "metano": "gnc",
}


def fetch_it():
    print("  [IT] descargando anagrafica + precios MIMIT...")
    ana_resp = requests.get(IT_ANAGRAFICA_URL, timeout=90, headers={"User-Agent": "OraculoVia/1.0"})
    ana_resp.raise_for_status()
    prz_resp = requests.get(IT_PREZZI_URL, timeout=90, headers={"User-Agent": "OraculoVia/1.0"})
    prz_resp.raise_for_status()

    # Formato pipe-delimited "|" desde el 10/02/2026, cabecera incluida
    ana_reader = csv.DictReader(io.StringIO(ana_resp.content.decode("utf-8", errors="ignore")), delimiter="|")
    stations = {}
    for row in ana_reader:
        idimp = row.get("idImpianto") or row.get("idimpianto")
        lat, lon = _num(row.get("Latitudine")), _num(row.get("Longitudine"))
        if not idimp or lat is None or lon is None:
            continue
        stations[idimp] = {
            "pais": "IT", "id": f"IT-{idimp}", "lat": lat, "lon": lon,
            "rotulo": (row.get("Bandiera") or "").strip().title(),
            "direccion": (row.get("Indirizzo") or "").strip().title(),
            "municipio": (row.get("Comune") or "").strip().title(),
            "precios": {},
        }

    prz_reader = csv.DictReader(io.StringIO(prz_resp.content.decode("utf-8", errors="ignore")), delimiter="|")
    for row in prz_reader:
        idimp = row.get("idImpianto") or row.get("idimpianto")
        st = stations.get(idimp)
        if not st:
            continue
        carb = (row.get("descCarburante") or "").strip().lower()
        out_key = IT_FUEL_MAP.get(carb)
        precio = _num(row.get("prezzo"))
        if out_key and precio is not None:
            is_self = row.get("isSelf") in ("1", "1.0", "true", "True")
            if out_key not in st["precios"] or is_self:
                st["precios"][out_key] = precio

    out = [s for s in stations.values() if s["precios"]]
    print(f"  [IT] {len(out)} estaciones válidas")
    return out


FETCHERS = {"ES": fetch_es, "FR": fetch_fr, "IT": fetch_it}


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

    todas = []
    no_disponibles = {}
    for pais in paises:
        if pais in FETCHERS:
            try:
                todas.extend(FETCHERS[pais]())
            except requests.RequestException as e:
                print(f"  [{pais}] ERROR de red: {e}", file=sys.stderr)
        elif pais in NOT_AVAILABLE_YET:
            no_disponibles[pais] = NOT_AVAILABLE_YET[pais]
            print(f"  [{pais}] omitido: {NOT_AVAILABLE_YET[pais]}")
        else:
            print(f"  [{pais}] país no reconocido, omitido")

    payload = {
        "actualizado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "paises_incluidos": [p for p in paises if p in FETCHERS],
        "paises_no_disponibles": no_disponibles,
        "num_estaciones": len(todas),
        "estaciones": todas,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    print(f"\nEscrito {OUTPUT_FILE}: {len(todas)} estaciones de {payload['paises_incluidos']}")
    if no_disponibles:
        print(f"Pendientes sin fuente gratuita de bulk: {list(no_disponibles.keys())}")


if __name__ == "__main__":
    main()
