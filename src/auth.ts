import { createRemoteJWKSet, jwtVerify, type JWTVerifyGetKey } from "jose";

/**
 * Cloudflare Access puts a signed JWT on every request it lets through.
 * We verify it here too, so the data stays private even if someone reaches
 * the Worker without going through Access.
 * https://developers.cloudflare.com/cloudflare-one/identity/authorization-cookie/validating-json/
 */

const jwksCache = new Map<string, JWTVerifyGetKey>();

export function normalizeTeamDomain(team: string): string {
  const host = team.trim().replace(/^https?:\/\//, "").replace(/\/+$/, "");
  return host.includes(".") ? host : `${host}.cloudflareaccess.com`;
}

function getJwks(teamDomain: string): JWTVerifyGetKey {
  let jwks = jwksCache.get(teamDomain);
  if (!jwks) {
    jwks = createRemoteJWKSet(new URL(`https://${teamDomain}/cdn-cgi/access/certs`));
    jwksCache.set(teamDomain, jwks);
  }
  return jwks;
}

export function getAccessToken(request: Request): string | null {
  const header = request.headers.get("Cf-Access-Jwt-Assertion");
  if (header) return header;
  const cookie = request.headers.get("Cookie") ?? "";
  const m = /(?:^|;\s*)CF_Authorization=([^;]+)/.exec(cookie);
  return m ? decodeURIComponent(m[1]!) : null;
}

export type AuthResult =
  | { ok: true; email: string | null }
  | { ok: false; status: 401 | 403 | 503; reason: string };

export interface AuthEnv {
  ACCESS_TEAM_DOMAIN?: string;
  ACCESS_AUD?: string;
  ALLOW_UNAUTHENTICATED?: string;
}

export async function checkAccess(
  request: Request,
  env: AuthEnv,
  keys?: JWTVerifyGetKey, // injectable for tests
): Promise<AuthResult> {
  if (env.ALLOW_UNAUTHENTICATED === "true") return { ok: true, email: null };
  if (!env.ACCESS_TEAM_DOMAIN || !env.ACCESS_AUD) {
    return { ok: false, status: 503, reason: "Cloudflare Access isn't configured yet." };
  }
  const token = getAccessToken(request);
  if (!token) return { ok: false, status: 401, reason: "Sign-in required." };
  const team = normalizeTeamDomain(env.ACCESS_TEAM_DOMAIN);
  try {
    const { payload } = await jwtVerify(token, keys ?? getJwks(team), {
      issuer: `https://${team}`,
      audience: env.ACCESS_AUD,
    });
    return { ok: true, email: typeof payload.email === "string" ? payload.email : null };
  } catch {
    return { ok: false, status: 403, reason: "Your sign-in couldn't be verified." };
  }
}

/** Constant-time string comparison for the collect token. */
export function safeEqual(a: string, b: string): boolean {
  const enc = new TextEncoder();
  const x = enc.encode(a);
  const y = enc.encode(b);
  let diff = x.length ^ y.length;
  for (let i = 0; i < Math.max(x.length, y.length); i++) diff |= (x[i] ?? 0) ^ (y[i] ?? 0);
  return diff === 0;
}
