const { onRequest } = require("firebase-functions/v2/https");

const SPIKE_URL = (process.env.SPIKE_URL || "http://127.0.0.1:8080").replace(
  /\/$/,
  "",
);

function spikePath(req) {
  const raw = String(req.originalUrl || req.url || req.path || "");
  const path = raw.split("?")[0];
  if (path.endsWith("/status")) {
    return "/api/status";
  }
  if (path.endsWith("/demo")) {
    return "/api/demo";
  }
  return "";
}

exports.spikeGateway = onRequest(
  {
    region: "europe-west1",
    cors: true,
    timeoutSeconds: 360,
    invoker: "public",
  },
  async (req, res) => {
    const path = spikePath(req);
    if (!path) {
      res.status(404).json({ error: "Unknown gateway path." });
      return;
    }
    if (path === "/api/status" && req.method !== "GET") {
      res.status(405).json({ error: "GET required." });
      return;
    }
    if (path === "/api/demo" && req.method !== "POST") {
      res.status(405).json({ error: "POST required." });
      return;
    }
    const headers = { Accept: "application/json" };
    const init = { method: req.method, headers };
    if (req.method === "POST") {
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(req.body || {});
    }
    let upstream;
    try {
      upstream = await fetch(`${SPIKE_URL}${path}`, init);
    } catch (error) {
      const message = error instanceof Error ? error.message : "upstream failed";
      res.status(502).json({ error: message });
      return;
    }
    const text = await upstream.text();
    let payload;
    try {
      payload = JSON.parse(text);
    } catch {
      payload = { error: text || `Upstream HTTP ${upstream.status}` };
    }
    res.status(upstream.status).json(payload);
  },
);
