const CACHE_NAME = 'radares-pwa-v1';
const ASSETS = [
  './',
  './index.html',
  './manifest.json',
  './radares.json'
];

// Instalación: guardar archivos esenciales en caché
self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(ASSETS);
    })
  );
  self.skipWaiting();
});

// Activación: limpiar cachés antiguas si las hay
self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          if (key !== CACHE_NAME) return caches.delete(key);
        })
      );
    })
  );
  self.clients.claim();
});

// Estrategia: Buscar primero en red; si falla (sin cobertura), servir de caché
self.addEventListener('fetch', (e) => {
  e.respondWith(
    fetch(e.request).catch(() => {
      return caches.match(e.request);
    })
  );
});
