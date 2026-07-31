import json
import urllib.request
import math

# Cargar configuración
with open('config_paises.json', 'r', encoding='utf-8') as f:
    config = json.load(f)

paises = config.get("paises_activos", ["ES"])
print(f"🌍 Generando Base de Datos Premium para países: {', '.join(paises)}...")

# Bounding boxes aproximadas por país para consultas Overpass OSM
BBOX_PAISES = {
    "ES": "35.0,-10.0,44.0,4.5",
    "AND": "42.4,1.4,42.7,1.8",
    "FR": "41.3,-5.2,51.1,9.6",
    "DE": "47.2,5.8,55.1,15.1",
    "IT": "36.6,6.6,47.1,18.8",
    "CH": "45.8,5.9,47.8,10.5",
    "AT": "46.3,9.5,49.0,17.2"
}

elementos_totales = []

def consultar_overpass(bbox_str):
    overpass_url = "https://overpass-api.de/api/interpreter"
    query = f"""
    [out:json][timeout:60];
    (
      node["highway"="speed_camera"]({bbox_str});
      node["enforcement"="maxspeed"]({bbox_str});
      node["highway"="traffic_signals"]["camera"]({bbox_str});
    );
    out body;
    """
    req = urllib.request.Request(overpass_url, data=query.encode('utf-8'), headers={'User-Agent': 'RadarPWA/2.0'})
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode('utf-8'))
            return data.get('elements', [])
    except Exception as e:
        print(f"⚠️ Error al consultar Overpass para bbox {bbox_str}: {e}")
        return []

for p in paises:
    if p in BBOX_PAISES:
        print(f"📡 Descargando datos de {p}...")
        nodes = consultar_overpass(BBOX_PAISES[p])
        for node in nodes:
            tags = node.get('tags', {})
            
            # Clasificación inteligente de categorías
            tipo = "RADAR_FIJO"
            if tags.get('highway') == 'traffic_signals' or tags.get('enforcement') == 'traffic_signals':
                tipo = "FOTO_ROJO"
            elif tags.get('camera:type') == 'belt' or tags.get('camera:type') == 'phone':
                tipo = "CAMARA_CINTURON"

            vel = tags.get('maxspeed', '80')
            try:
                vel = int(''.join(filter(str.isdigit, str(vel))))
            except:
                vel = 80

            elementos_totales.append({
                "id": f"{p}-{node['id']}",
                "pais": p,
                "lat": node['lat'],
                "lon": node['lon'],
                "tipo": tipo,
                "velocidad": vel
            })

print(f"✅ Descargados {len(elementos_totales)} puntos totales.")

# Guardar fichero maestro
with open('radares.json', 'w', encoding='utf-8') as f:
    json.dump(elementos_totales, f, ensure_ascii=False, indent=2)

print("🚀 'radares.json' generado con éxito!")
