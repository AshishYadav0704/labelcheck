/* Service worker: caches the app shell so LabelCheck opens instantly and offline.
   API calls always go to the network (reports must be fresh). */
const CACHE = "labelcheck-shell-v3";
const SHELL = ["/", "/index.html", "/styles.css", "/app.js", "/manifest.webmanifest", "/icons/icon-192.png", "/icons/icon-512.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;

  // Page navigations (including shared /r/<id> links): network first, cached shell as fallback.
  if (req.mode === "navigate") {
    event.respondWith(fetch(req).catch(() => caches.match("/index.html")));
    return;
  }
  // Static files: cache first, refresh in the background.
  event.respondWith(
    caches.match(req).then((cached) => {
      const network = fetch(req).then((res) => {
        if (res.ok) caches.open(CACHE).then((c) => c.put(req, res.clone()));
        return res;
      }).catch(() => cached);
      return cached || network;
    }),
  );
});
