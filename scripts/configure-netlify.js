const fs = require("node:fs");
const path = require("node:path");

const apiUrl = process.env.RENDER_API_URL;
if (!apiUrl) {
  throw new Error("Set RENDER_API_URL in Netlify to the public Render backend URL.");
}

let parsed;
try {
  parsed = new URL(apiUrl);
} catch {
  throw new Error("RENDER_API_URL must be an absolute HTTPS URL.");
}
if (parsed.protocol !== "https:" || parsed.pathname !== "/" || parsed.search || parsed.hash) {
  throw new Error("RENDER_API_URL must be an HTTPS origin, without a path or query string.");
}

const rules = [
  `/api/* ${parsed.origin}/api/:splat 200`,
  `/socket.io/* ${parsed.origin}/socket.io/:splat 200`,
  `/socket.io ${parsed.origin}/socket.io 200`,
  "",
].join("\n");

const publishDir = path.resolve(__dirname, "..", "www");
fs.writeFileSync(path.join(publishDir, "_redirects"), rules, "utf8");
console.log("Wrote Netlify API and Socket.IO proxy rules.");
