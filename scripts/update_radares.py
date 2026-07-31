import os
import json
import time
import requests

# Mapa de países con su código ISO3166-1 alpha-2 (el estándar que utiliza Overpass API)
PAISES = {
    "ES": "España",
    "AD": "Andorra",
    "FR": "Francia",
    "DE": "Alemania",
    "IT": "Italia",
    "CH": "Suiza",
    "AT": "Austria"
}

# Servidores alternativos de Overpass por si el principal está saturado
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter"
]

def obtener_radares_pais(codigo_iso, nombre_pais):
    print(f"📡 Descargando datos de {nombre_pais} ({codigo_iso})...")
    
    # Query de Overpass optimizada con 180s de timeout
    query = f"""
    [out:json][timeout:180];
    area["ISO3166-1"="{codigo_iso}"][admin_level=2]->.searchArea;
    (
      node["highway"="speed_camera"](area.searchArea);
      node["enforcement"="maxspeed"](area.searchArea);
    );
    out body;
    """
    
    # Probamos con hasta 3 intentos por país rotando o reintentando
    for intento in range(1, 4):
        url = OVERPASS_URLS[(intento - 1) % len(OVERPASS_URLS)]
        try:
            response = requests.post(url, data={'data': query}, timeout=190)
            
            if response.status_code == 200:
                data = response.json()
                elementos = data.get("elements", [])
                
                # Inyectamos el país en los metadatos de cada nodo por si lo usas luego
                for elem in elementos:
                    elem["country"] = codigo_iso
                    
                print(f"   -> {len(elementos)} puntos obtenidos en {codigo_iso}")
                return elementos
            elif response.status_code == 504:
                print(f"⚠️ Error 504 (Timeout) en {codigo_iso} (intento {intento}/3). Reintentando...")
            else:
                print(f"⚠️ Error HTTP {response.status_code} en {codigo_iso} (intento {intento}/3)")

        except requests.exceptions.RequestException as e:
            print(f"⚠️ Error de conexión en {codigo_iso} (intento {intento}/3): {e}")
        
        # Pausa de seguridad para no saturar la API
        time.sleep(6)

    print(f"❌ No se pudieron obtener datos para {codigo_iso} tras 3 intentos.")
    return []

def main():
    print(f"🚀 Iniciando actualización para {len(PAISES)} países...")
    
    todos_los_radares = []
    ids_vistos = set()
    
    for codigo_iso, nombre_pais in PAISES.items():
        elementos = obtener_radares_pais(codigo_iso, nombre_pais)
        
        # Filtrar duplicados por ID de nodo de OpenStreetMap
        for elem in elementos:
            node_id = elem.get("id")
            if node_id and node_id not in ids_vistos:
                ids_vistos.add(node_id)
                todos_los_radares.append(elem)
        
        # Breve descanso entre países para ser respetuosos con los servidores públicos
        time.sleep(3)

    total_puntos = len(todos_los_radares)
    print(f"\n📦 TOTAL FINAL EN JSON: {total_puntos} puntos.")
    
    # Guardar en radares.json
    archivo_salida = "radares.json"
    try:
        with open(archivo_salida, "w", encoding="utf-8") as f:
            json.dump(todos_los_radares, f, ensure_ascii=False, indent=2)
        print(f"✅ Archivo '{archivo_salida}' listo. Súbelo a GitHub.")
    except Exception as e:
        print(f"❌ Error guardando el archivo JSON: {e}")

if __name__ == "__main__":
    main()
