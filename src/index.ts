import { checkAccess, type AuthEnv } from "./auth";
import { lockedPage } from "./pages";

/**
 * Serves site/ (the dashboard plus the data.json that build.py writes) from
 * Cloudflare, but only to people Cloudflare Access lets in. DRAMeXchange's
 * terms forbid republishing its prices, so the dashboard is owner-only.
 */
export interface Env extends AuthEnv {
  ASSETS: Fetcher;
}

/** Served without sign-in: the privacy policy and what it needs to render. */
const PUBLIC_PATHS = new Set(["/privacy", "/privacy.html", "/styles.css", "/favicon.svg", "/robots.txt"]);
export const isPublic = (path: string) => PUBLIC_PATHS.has(path) || path.startsWith("/fonts/");

export const SECURITY_HEADERS: Record<string, string> = {
  "Content-Security-Policy":
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
  "Permissions-Policy": "camera=(), microphone=(), geolocation=(), interest-cohort=()",
  "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
  "X-Robots-Tag": "noindex, nofollow",
  "Cross-Origin-Opener-Policy": "same-origin",
};

function withHeaders(res: Response, extra: Record<string, string> = {}): Response {
  const out = new Response(res.body, res);
  for (const [k, v] of Object.entries({ ...SECURITY_HEADERS, ...extra })) out.headers.set(k, v);
  return out;
}

async function handle(request: Request, env: Env): Promise<Response> {
  const path = new URL(request.url).pathname;

  if (path === "/healthz") return new Response("ok", { headers: { "Content-Type": "text/plain" } });
  if (request.method !== "GET" && request.method !== "HEAD") {
    return new Response("Method not allowed", { status: 405, headers: { Allow: "GET, HEAD" } });
  }
  if (isPublic(path)) return env.ASSETS.fetch(request);

  const auth = await checkAccess(request, env);
  if (!auth.ok) {
    return new Response(lockedPage(auth.reason, auth.status === 503), {
      status: auth.status,
      headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" },
    });
  }

  const res = await env.ASSETS.fetch(request);
  // Private content must never land in a shared cache; data.json changes daily.
  return withHeaders(res, { "Cache-Control": "private, no-cache" });
}

export default {
  async fetch(request, env): Promise<Response> {
    try {
      return withHeaders(await handle(request, env));
    } catch (err) {
      console.error("request failed", err);
      return withHeaders(new Response("Internal error", { status: 500 }));
    }
  },
} satisfies ExportedHandler<Env>;
