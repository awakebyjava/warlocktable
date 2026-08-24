/* Service worker for the Warlock Table panel.
 *
 * Caches the app SHELL only - never API responses. A cached status would be
 * actively harmful: the panel exists to tell you whether the table is
 * healthy right now, and a stale green light is worse than no light.
 *
 * What this buys: opening the icon when the Pi is unreachable shows the
 * panel with a clear "cannot reach the table" state, instead of Safari's
 * dinosaur. That distinction matters mid-session - it tells you the iPad is
 * fine and the table is not.
 */
// BUMP THIS whenever the shell changes shape. The activate handler deletes
// every cache that is not this one, so a new name is what guarantees the
// old shell is actually gone rather than merely out of favour.
const CACHE = "warlock-shell-v6";
const SHELL = [
  // "/" is now the join chooser and "/gm" is the panel. Both are cached:
  // the GM's installed app opens /gm, and a player who scanned the code
  // gets a real page rather than a browser error if the Pi blinks.
  "/", "/gm", "/player", "/style.css", "/app.js", "/dice-presets.js",
  "/manifest.webmanifest", "/icon-192.png", "/apple-touch-icon.png",
  "/favicon-64.png",
  // Must match what style.css actually asks for. Syne was dropped for
  // Playfair Display when the brand kit landed and lingered here; a name
  // that 404s is worse than useless, because addAll() rejects ATOMICALLY
  // and one missing file means the whole shell fails to cache.
  "/fonts/IBMPlexSans.ttf", "/fonts/PlayfairDisplay-ExtraBold.ttf",
  "/fonts/IBMPlexMono-Regular.ttf", "/fonts/IBMPlexMono-Medium.ttf"
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  // API traffic is never cached and never served from cache.
  if (url.pathname.startsWith("/api/")) return;
  // Shell: network first so updates land, cache only as the fallback.
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy)).catch(() => {});
        return res;
      })
      .catch(() => caches.match(e.request).then((r) => r || caches.match("/")))
  );
});
