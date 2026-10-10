const OFFLINE_PAGE = `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#07111f">
  <title>AI Second Brain — Offline</title>
  <style>
    body{margin:0;min-height:100vh;display:grid;place-items:center;background:#07111f;color:#f8fbff;font:16px system-ui,sans-serif}
    main{max-width:420px;margin:24px;padding:28px;border:1px solid #284467;border-radius:20px;background:#102342;text-align:center}
    h1{font-size:1.35rem}p{line-height:1.6;color:#c3d2e7}button{padding:12px 20px;border:0;border-radius:10px;background:linear-gradient(120deg,#2563eb,#7c3aed);color:white;font-weight:700}
  </style>
</head>
<body><main><h1>AI Second Brain</h1><p>Internet connection is required to open your notes and AI features. Reconnect and try again.</p><button onclick="location.reload()">Try again</button></main></body>
</html>`;

self.addEventListener("install", (event) => {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

// Keep authenticated pages and user data network-only. This handler only
// supplies a small offline message when a page navigation has no connection.
self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET" || request.mode !== "navigate") return;

  const requestUrl = new URL(request.url);
  if (requestUrl.origin !== self.location.origin) return;

  event.respondWith(
    fetch(request).catch(() => new Response(OFFLINE_PAGE, {
      status: 200,
      headers: { "Content-Type": "text/html; charset=utf-8" }
    }))
  );
});
