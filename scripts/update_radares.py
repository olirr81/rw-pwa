import math
import json
import urllib.request
import os

def calcular_distancia_m(lat1, lon1, lat2, lon2):
    """Calcula la distancia en metros entre dos coordenadas (Haversine)."""
    R = 6371000  # Radio de la Tierra en metros
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def obtener_radares_osm():
    """Descarga radares de España desde la API de OpenStreetMap (Overpass)."""
    print("📥 Consultando OpenStreetMap (Overpass API)...")
    overpass_url = "https://overpass-api.de/api/interpreter"
    # Consulta Overpass para obtener speed_cameras dentro del cuadro de España
    query = """
    [out:json][timeout:25];
    node["highway"="speed_camera"](35.0,-10.0,43.8,4.5);
    out body;
    """
    radares_osm = []
    try:
        req = urllib.request.Request(overpass_url, data=query.encode('utf-8'))
        req.add_header('User-Agent', 'RadarPWA/1.0')
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode('utf-8'))
            for elem in data.get('elements', []):
                maxspeed = elem.get('tags', {}).get('maxspeed', None)
                try:
                    speed = int(maxspeed) if maxspeed and maxspeed.isdigit() else 80
                except ValueError:
                    speed = 80

                radares_osm.append({
                    "lat": round(elem['lat'], 6),
                    "lon": round(elem['lon'], 6),
                    "tipo": "Radar Fijo",
                    "velocidad": speed,
                    "fuente": "OSM"
                })
        print(f"✅ Descargados {len(radares_osm)} radares de OpenStreetMap.")
    except Exception as e:
        print(f"⚠️ Error al obtener datos de OSM: {e}")
    return radares_osm

def cargar_radares_robser(filepath="scripts/fuentes/robser.csv"):
    """Carga radares desde un CSV local de Robser/LaRadioBBS si existe."""
    radares_robser = []
    if not os.path.exists(filepath):
        print(f"ℹ️ Archivo {filepath} no encontrado (puedes añadirlo más adelante).")
        return radares_robser

    print(f"📂 Cargando base de datos Robser desde {filepath}...")
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                parts = line.strip().split(',')
                if len(parts) >= 3:
                    try:
                        lon = float(parts[0])
                        lat = float(parts[1])
                        info = parts[2].replace('"', '').strip()
                        
                        # Detección básica de tipo y velocidad según nombre
                        tipo = "Radar Fijo"
                        velocidad = 80
                        
                        if "SEMAFORO" in info.upper() or "RED LIGHT" in info.upper():
                            tipo = "Semáforo Foto"
                            velocidad = 50
                        elif "MOVIL" in info.upper():
                            tipo = "Radar Móvil"
                        elif "TRAMO" in info.upper():
                            tipo = "Radar de Tramo"
                            
                        # Extraer velocidad si viene en el texto
                        for words in info.split():
                            if words.isdigit() and int(words) in [30, 40, 50, 60, 70, 80, 90, 100, 110, 120]:
                                velocidad = int(words)
                                break

                        radares_robser.append({
                            "lat": round(lat, 6),
                            "lon": round(lon, 6),
                            "tipo": tipo,
                            "velocidad": velocidad,
                            "fuente": "Robser"
                        })
                    except ValueError:
                        continue
        print(f"✅ Cargados {len(radares_robser)} radares de Robser.")
    except Exception as e:
        print(f"⚠️ Error al leer CSV Robser: {e}")
    return radares_robser

def fusionar_y_deduplicar(lista_principal, lista_secundaria, umbral_metros=50):
    """Fusiona dos listas de radares eliminando duplicados cercanos (menos de N metros)."""
    print("🔄 Cruzando fuentes y eliminando duplicados...")
    resultado = list(lista_principal)
    duplicados = 0

    for r2 in lista_secundaria:
        es_duplicado = False
        for r1 in resultado:
            d = calcular_distancia_m(r1['lat'], r1['lon'], r2['lat'], r2['lon'])
            if d <= umbral_metros:
                es_duplicado = True
                # Si r2 tiene más detalle de tipo/velocidad, enriquecemos r1
                if r1['velocidad'] == 80 and r2['velocidad'] != 80:
                    r1['velocidad'] = r2['velocidad']
                if r1['tipo'] == "Radar Fijo" and r2['tipo'] != "Radar Fijo":
                    r1['tipo'] = r2['tipo']
                break
        
        if not es_duplicado:
            resultado.append(r2)
        else:
            duplicados += 1

    print(f"🎯 Fusión completada: {len(resultado)} radares únicos (descartados {duplicados} duplicados).")
    return resultado

def main():
    osm_data = obtener_radares_osm()
    robser_data = cargar_radares_robser()
    
    # Cruzamos ambas listas (Robser primero si existe para priorizar sus tipos)
    if robser_data:
        base_final = fusionar_y_deduplicar(robser_data, osm_data)
    else:
        base_final = osm_data

    # Asignar IDs numéricos simples para la PWA
    for idx, r in enumerate(base_final, 1):
        r['id'] = idx

    # Guardar en public/radares.json
    os.makedirs('public', exist_ok=True)
    out_path = 'public/radares.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(base_final, f, ensure_ascii=False, indent=2)

    print(f"🚀 ¡Éxito! Base de datos final guardada en '{out_path}'.")

if __name__ == "__main__":
    main()
