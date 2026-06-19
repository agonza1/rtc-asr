const CACHE_NAME = "rtc-asr-demo-shell-v3";
const LOCAL_DEMO_HOSTS = new Set(["localhost", "127.0.0.1", "::1"]);
const IS_LOCAL_DEMO = LOCAL_DEMO_HOSTS.has(self.location.hostname);
const SHELL_ASSETS = [
  "/rtc-asr",
  "/rtc-asr/manifest.webmanifest",
  "/rtc-asr/assets/styles.css",
  "/rtc-asr/assets/app.js",
  "/rtc-asr/assets/icons/icon.svg",
  "/rtc-asr/assets/icons/icon-192.png",
  "/rtc-asr/assets/icons/icon-512.png",
  "/rtc-asr/assets/icons/apple-touch-icon.png",
];

self.addEventListener("install", (event) => {
  if (IS_LOCAL_DEMO) {
    event.waitUntil(self.skipWaiting());
    return;
  }

  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_ASSETS)));
  self.skipWaiting();
});

self.addEventListener("message", (event) => {
  if (event.data?.type === "SKIP_WAITING") {
    self.skipWaiting();
  }
});

self.addEventListener("activate", (event) => {
  if (IS_LOCAL_DEMO) {
    event.waitUntil(
      (async () => {
        const keys = await caches.keys();
        const demoCaches = keys.filter((key) => key.startsWith("rtc-asr-demo-shell"));
        await Promise.all(demoCaches.map((key) => caches.delete(key)));
        await self.clients.claim();
        await self.registration.unregister();
      })()
    );
    return;
  }

  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") {
    return;
  }

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) {
    return;
  }

  if (IS_LOCAL_DEMO) {
    event.respondWith(fetch(request));
    return;
  }

  if (SHELL_ASSETS.includes(url.pathname)) {
    event.respondWith(caches.match(request).then((cached) => cached || fetch(request)));
    return;
  }

  if (request.mode === "navigate" && url.pathname.startsWith("/rtc-asr")) {
    event.respondWith(
      fetch(request).catch(async () => {
        const cached = await caches.match("/rtc-asr");
        return cached || Response.error();
      })
    );
  }
});
