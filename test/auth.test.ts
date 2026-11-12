import { SignJWT, createLocalJWKSet, exportJWK, generateKeyPair } from "jose";
import { beforeAll, describe, expect, it } from "vitest";
import { checkAccess, getAccessToken, normalizeTeamDomain, safeEqual } from "../src/auth";

const TEAM = "example.cloudflareaccess.com";
const AUD = "aud-tag-123";
const env = { ACCESS_TEAM_DOMAIN: TEAM, ACCESS_AUD: AUD };

let keys: ReturnType<typeof createLocalJWKSet>;
let sign: (claims: Record<string, unknown>, opts?: { iss?: string; aud?: string; exp?: string }) => Promise<string>;

beforeAll(async () => {
  const { publicKey, privateKey } = await generateKeyPair("RS256");
  const jwk = { ...(await exportJWK(publicKey)), kid: "k1", alg: "RS256" };
  keys = createLocalJWKSet({ keys: [jwk] });
  sign = (claims, opts = {}) =>
    new SignJWT(claims)
      .setProtectedHeader({ alg: "RS256", kid: "k1" })
      .setIssuer(opts.iss ?? `https://${TEAM}`)
      .setAudience(opts.aud ?? AUD)
      .setIssuedAt()
      .setExpirationTime(opts.exp ?? "1h")
      .sign(privateKey);
});

const req = (headers: Record<string, string> = {}) => new Request("https://mw.example/", { headers });

describe("checkAccess", () => {
  it("accepts a valid Access token from the header", async () => {
    const token = await sign({ email: "owner@example.com" });
    expect(await checkAccess(req({ "Cf-Access-Jwt-Assertion": token }), env, keys)).toEqual({ ok: true, email: "owner@example.com" });
  });

  it("accepts the CF_Authorization cookie", async () => {
    const token = await sign({ email: "owner@example.com" });
    const r = await checkAccess(req({ Cookie: `theme=dark; CF_Authorization=${token}` }), env, keys);
    expect(r.ok).toBe(true);
  });

  it("rejects a token for another application", async () => {
    const token = await sign({}, { aud: "someone-else" });
    expect(await checkAccess(req({ "Cf-Access-Jwt-Assertion": token }), env, keys)).toMatchObject({ ok: false, status: 403 });
  });

  it("rejects a token from another team", async () => {
    const token = await sign({}, { iss: "https://evil.cloudflareaccess.com" });
    expect(await checkAccess(req({ "Cf-Access-Jwt-Assertion": token }), env, keys)).toMatchObject({ ok: false, status: 403 });
  });

  it("rejects an expired token", async () => {
    const token = await sign({}, { exp: "-5m" });
    expect(await checkAccess(req({ "Cf-Access-Jwt-Assertion": token }), env, keys)).toMatchObject({ ok: false, status: 403 });
  });

  it("rejects a token signed with a different key", async () => {
    const other = await generateKeyPair("RS256");
    const forged = await new SignJWT({}).setProtectedHeader({ alg: "RS256", kid: "k1" }).setIssuer(`https://${TEAM}`).setAudience(AUD).setExpirationTime("1h").sign(other.privateKey);
    expect(await checkAccess(req({ "Cf-Access-Jwt-Assertion": forged }), env, keys)).toMatchObject({ ok: false, status: 403 });
  });

  it("asks for sign-in when no token is present", async () => {
    expect(await checkAccess(req(), env, keys)).toMatchObject({ ok: false, status: 401 });
  });

  it("fails closed when Access isn't configured", async () => {
    expect(await checkAccess(req(), {}, keys)).toMatchObject({ ok: false, status: 503 });
    expect(await checkAccess(req(), { ACCESS_TEAM_DOMAIN: TEAM }, keys)).toMatchObject({ ok: false, status: 503 });
  });

  it("allows everything only with the explicit local-dev flag", async () => {
    expect(await checkAccess(req(), { ALLOW_UNAUTHENTICATED: "true" })).toEqual({ ok: true, email: null });
    expect(await checkAccess(req(), { ALLOW_UNAUTHENTICATED: "yes" })).toMatchObject({ ok: false });
  });
});

describe("helpers", () => {
  it("normalises the team domain", () => {
    expect(normalizeTeamDomain("myteam")).toBe("myteam.cloudflareaccess.com");
    expect(normalizeTeamDomain("https://myteam.cloudflareaccess.com/")).toBe("myteam.cloudflareaccess.com");
  });

  it("prefers the header over the cookie", () => {
    expect(getAccessToken(req({ "Cf-Access-Jwt-Assertion": "a", Cookie: "CF_Authorization=b" }))).toBe("a");
    expect(getAccessToken(req({ Cookie: "x=1" }))).toBeNull();
  });

  it("compares secrets exactly", () => {
    expect(safeEqual("abc", "abc")).toBe(true);
    expect(safeEqual("abc", "abd")).toBe(false);
    expect(safeEqual("abc", "abcd")).toBe(false);
    expect(safeEqual("", "")).toBe(true);
  });
});
