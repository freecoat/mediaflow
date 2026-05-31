const CACHE = 'claqo-m-v1';
const SHELL = ['/static/css/mobile.css','/static/js/mobile.js','/static/icons/icon-192.png','/m/offline'];
self.addEventListener('install', e => { self.skipWaiting(); e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).catch(()=>{})); });
self.addEventListener('activate', e => { e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k!==CACHE).map(k => caches.delete(k))))); self.clients.claim(); });
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET') return; // azioni online: passa diretto
  if (url.pathname.startsWith('/static/')) {
    e.respondWith(caches.match(e.request).then(r => r || fetch(e.request).then(resp => { const cp = resp.clone(); caches.open(CACHE).then(c=>c.put(e.request, cp)); return resp; }).catch(()=>r)));
    return;
  }
  if (url.pathname.startsWith('/m')) {
    e.respondWith(fetch(e.request).catch(() => caches.match('/m/offline')));
  }
});
