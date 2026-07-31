import json
import os
import urllib.request
import urllib.parse

def fetch_osm_speed_cameras():
    print("🤖 Consultando OpenStreetMap (Overpass API)...")
    
    # Consulta Overpass optimizada para radares en España
    overpass_query = """
    [out:json][timeout:60];
    (
      node["highway"="speed_camera"](35.0,-10.0,44.0,5.0);
      node["enforcement"="maxspeed"](35.0,-10.0,44.0,5.0);
    );
    out body;
    """
    
    endpoints = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter"
    ]
    
    elements = []
    encoded_data = urllib.parse.urlencode({'data': overpass_query}).encode('utf-8')
    
    for url in endpoints:
        try:
            req = urllib.request.Request(url, data=encoded_data, headers={'User-Agent': 'RadarPWA/1.0'})
            with urllib.request.urlopen(req, timeout=60) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode('utf-8'))
                    elements = data.get('elements', [])
                    if elements:
                        print(f"✅ Descargados {len(elements)} radares desde {url}")
                        break
        except Exception as e:
            print(f"⚠️ Falló el servidor {url}: {e}")
            continue

    radares = []
    for elem in elements:
        lat = elem.get('lat')
        lon = elem.get('lon')
        tags = elem.get('tags', {})
        
        if lat and lon:
            maxspeed = tags.get('maxspeed', None)
            try:
                speed = int(maxspeed) if maxspeed and str(maxspeed).isdigit() else 80
            except ValueError:
                speed = 80

            tipo_desc = "Radar Fijo"
            if tags.get('enforcement') == 'maxspeed':
                tipo_desc = "Radar de Tramo / Fijo"

            radares.append({
                "id": str(elem.get('id')),
                "lat": round(float(lat), 6),
                "lon": round(float(lon), 6),
                "tipo": tipo_desc,
                "velocidad": speed
            })
            
    return radares

def main():
    radares = fetch_osm_speed_cameras()
    
    if not radares:
        print("⚠️ No se pudieron descargar radares de la API. Generando fallback...")
        radares = [
            {"id": "demo1", "lat": 41.3851, "lon": 2.1734, "tipo": "Radar Fijo", "velocidad": 80},
            {"id": "demo2", "lat": 41.1995, "lon": 1.6280, "tipo": "Radar Fijo", "velocidad": 120}
        ]

    # Asignar IDs limpios
    for idx, r in enumerate(radares, 1):
        r['id'] = idx

    # Crear directorios y guardar JSON
    os.makedirs("public", exist_ok=True)
    
    for path in ["radares.json", "public/radares.json"]:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(radares, f, ensure_ascii=False, indent=2)
            
    print(f"🚀 ¡Éxito! Base de datos final guardada con {len(radares)} radares.")

if __name__ == "__main__":
    main()
