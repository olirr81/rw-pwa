import json
import urllib.request
import time

PAISES = {
    "ES": "España",
    "AND": "Andorra",
    "FR": "Francia",
    "DE": "Alemania",
    "IT": "Italia",
    "CH": "Suiza",
    "AT": "Austria"
}

def consultar_overpass_pais(codigo_iso):
    print(f"📡 Descargando datos de {PAISES.get(codigo_iso, codigo_iso)} ({codigo_iso})...")
    overpass_url = "https://overpass-api.de/api/interpreter"
    
    # Consulta por código de área de país (mucho más rápida y sin timeout)
    query = f"""
    [out:json][timeout:120];
    area["ISO3166-1"="{codigo_iso}"]->.searchArea;
    (
      node["highway"="speed_camera"](area.searchArea);
      node["enforcement"="maxspeed"](area.searchArea);
      node["highway"="traffic_signals"]["camera"](area.searchArea);
    );
    out body;
    """
    
    req = urllib.request.Request(
        overpass_url, 
        data=query.encode('utf-8'), 
        headers={'User-Agent': 'RadarPWA_Universal/3.0'}
    )
    
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode('utf-8'))
            return data.get('elements', [])
    except Exception as e:
        print(f"⚠️ Error al consultar {codigo_iso}: {e}")
        return []

def procesar_elementos(nodes, pais):
    elementos = []
    for node in nodes:
        tags = node.get('tags', {})
        
        tipo = "RADAR_FIJO"
        if tags.get('highway') == 'traffic_signals' or tags.get('enforcement') == 'traffic_signals':
            tipo = "FOTO_ROJO"
        elif tags.get('camera:type') in ['belt', 'phone'] or tags.get('enforcement') in ['belt', 'phone']:
            tipo = "CAMARA_CINTURON"

        vel = tags.get('maxspeed', '80')
        try:
            vel = int(''.join(filter(str.isdigit, str(vel))))
        except:
            vel = 80

        elementos.append({
            "id": f"{pais}-{node['id']}",
            "pais": pais,
            "lat": float(node['lat']),
            "lon": float(node['lon']),
            "tipo": tipo,
            "velocidad": vel
        })
    return elementos

def main():
    print(f"🚀 Iniciando actualización para {len(PAISES)} países...")
    todos_los_radares = []

    for iso in PAISES.keys():
        nodes = consultar_overpass_pais(iso)
        elementos = procesar_elementos(nodes, iso)
        todos_los_radares.extend(elementos)
        print(f"   -> {len(elementos)} puntos obtenidos en {iso}")
        time.sleep(2) # Pausa de cortesía para no saturar la API

    print(f"\n📦 TOTAL FINAL EN JSON: {len(todos_los_radares)} puntos.")

    with open('radares.json', 'w', encoding='utf-8') as f:
        json.dump(todos_los_radares, f, ensure_ascii=False, indent=2)

    print("✅ Archivo 'radares.json' listo. Súbelo a GitHub.")

if __name__ == "__main__":
    main()
