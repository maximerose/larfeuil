const CACHE_NAME = 'larfeuil-v1';

self.addEventListener('install', (event) => {
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil(clients.claim());
});

// Intercepte les requêtes pour valider le statut PWA
self.addEventListener('fetch', (event) => {
    event.respondWith(fetch(event.request));
});
