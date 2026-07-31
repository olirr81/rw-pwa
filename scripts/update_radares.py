import json
import os
import requests

def fetch_osm_speed_cameras():
    print("🤖 Consultando OpenStreetMap (Overpass API)...")
    
    # Consulta Overpass optimizada para todos los radares fijos y de tramo en España (bounding box de España)
    overpass_url = "https://overpass-api.de/api/interpreter"
    overpass_query = """
    [out:json][timeout:60];
    (
      node["highway"="speed_camera"](35.0,-10.0,44.0,5.0);
      node["enforcement"="maxspeed"](35.0,-10.0,44.0,5.0);
    );
    out body;
    """
    
    # Servidores de respaldo por si el principal da timeout
    endpoints = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter"
    ]
    
    elements = []
    for url in endpoints:
        try:
            response = requests.post(url, data={'data': overpass_query}, timeout=60)
            if response.status_code == 200:
                data = response.json()
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
            speed = tags.get('maxspeed', 'Desconocido')
            radares.append({
                "id": str(elem.get('id')),
                "lat": float(lat),
                "lon": float(lon),
                "tipo": f"Radar Fijo ({speed} km/h)" if speed != 'Desconocido' else "Radar Fijo",
                "velocidad": speed
            })
            
    return radares

def main():
    radares = fetch_osm_speed_cameras()
    
    if not radares:
        print("⚠️ No se pudieron descargar radares. Generando base de datos de prueba...")
        # Fallback de seguridad con radares clave si la API estuviera caída
        radares = [
            {"id": "demo1", "lat": 41.3851, "lon": 2.1734, "tipo": "Radar Fijo (80 km/h)", "velocidad": "80"},
            {"id": "demo2", "lat": 41.1995, "lon": 1.6280, "tipo": "Radar Fijo (120 km/h)", "velocidad": "120"}
        ]

    # Crear directorios de destino
    os.makedirs("public", exist_ok=True)
    
    # Guardar en raíz y en public por compatibilidad
    for path in ["radares.json", "public/radares.json"]:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(radares, f, ensure_ascii=False, indent=2)
            
    print(f"🚀 ¡Éxito! Base de datos final guardada con {len(radares)} radares.")

if __name__ == "__main__":
    main()
