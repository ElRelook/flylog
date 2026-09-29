/* FlyLog service worker: offline use and "Share to FlyLog" on Android.
 * - own files (page, scripts, Python modules): network first, cache as fallback,
 *   so a new version is picked up as soon as you are online;
 * - libraries from CDNs (Pyodide, Leaflet, fonts): cache first, they are versioned;
 * - map tiles are not cached (too big, and their terms restrict it). */

const CACHE = "flylog-v2";
const SHARE_CACHE = "flylog-share";
const CDN = ["cdn.jsdelivr.net", "cdnjs.cloudflare.com", "fonts.googleapis.com", "fonts.gstatic.com"];

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) {
      if (key !== CACHE && key !== SHARE_CACHE) await caches.delete(key);
    }
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // A .igc shared from another app (Android share sheet).
  if (event.request.method === "POST" && url.pathname.endsWith("/share-target")) {
    event.respondWith((async () => {
      const form = await event.request.formData();
      const file = form.get("igc");
      if (file) {
        const cache = await caches.open(SHARE_CACHE);
        await cache.put("shared.igc", new Response(file, { headers: { "X-Name": encodeURIComponent(file.name || "vol.igc") } }));
      }
      return Response.redirect("./?shared=1", 303);
    })());
    return;
  }
  if (event.request.method !== "GET") return;

  if (CDN.includes(url.hostname)) {
    event.respondWith((async () => {
      const cached = await fromCache(event.request);
      if (cached) return cached;
      const res = await fetch(event.request);
      // <script>/<link> without crossorigin give opaque responses: cache them too.
      if (res.ok || res.type === "opaque") store(event.request, res);
      return res;
    })());
    return;
  }

  if (url.origin === self.location.origin) {
    event.respondWith((async () => {
      let res;
      try {
        res = await fetch(event.request);
      } catch {
        const cached = await fromCache(event.request, { ignoreSearch: true });
        if (cached) return cached;
        throw new Error("hors ligne");
      }
      if (res.ok) store(event.request, res);
      return res;
    })());
  }
});

// The cache is a bonus: if storage is unavailable (quota, private mode…),
// requests must still go through normally.
async function fromCache(request, options) {
  try {
    return await caches.match(request, options);
  } catch {
    return undefined;
  }
}

function store(request, response) {
  const copy = response.clone();
  caches.open(CACHE).then((cache) => cache.put(request, copy)).catch(() => {});
}
