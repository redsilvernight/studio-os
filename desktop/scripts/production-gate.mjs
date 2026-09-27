import { pathToFileURL } from "node:url";

const PLATFORM = "windows-x86_64";
const REGISTRATION_MODES = new Set(["present", "closed", "open"]);
const CLOSED_PROBE_EMAIL = "c4-preflight@studio-os.invalid";

export class UsageError extends Error {}

export function parseArgs(argv) {
  const options = {
    repo: "redsilvernight/studio-os",
    betaTag: "desktop-dev",
    stableTag: "desktop-prod",
    registration: "present",
    requireStable: false,
    githubApiBase: "https://api.github.com",
    timeoutMs: 15_000,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === "--require-stable") {
      options.requireStable = true;
      continue;
    }
    if (!argument.startsWith("--")) throw new UsageError(`unexpected argument: ${argument}`);
    const [rawName, inlineValue] = argument.slice(2).split("=", 2);
    const value = inlineValue ?? argv[++index];
    if (!value || value.startsWith("--")) throw new UsageError(`missing value for --${rawName}`);
    const key = {
      "base-url": "baseUrl",
      "expected-api-origin": "expectedApiOrigin",
      repo: "repo",
      "beta-tag": "betaTag",
      "stable-tag": "stableTag",
      registration: "registration",
      "github-api-base": "githubApiBase",
      "timeout-ms": "timeoutMs",
    }[rawName];
    if (!key) throw new UsageError(`unknown option: --${rawName}`);
    options[key] = key === "timeoutMs" ? Number(value) : value;
  }
  if (!options.baseUrl) throw new UsageError("--base-url is required");
  if (!options.expectedApiOrigin) throw new UsageError("--expected-api-origin is required");
  if (!REGISTRATION_MODES.has(options.registration)) {
    throw new UsageError("--registration must be present, closed, or open");
  }
  if (!Number.isInteger(options.timeoutMs) || options.timeoutMs < 100) {
    throw new UsageError("--timeout-ms must be an integer >= 100");
  }
  options.baseUrl = normalizeOrigin(options.baseUrl);
  options.expectedApiOrigin = normalizeOrigin(options.expectedApiOrigin);
  options.githubApiBase = options.githubApiBase.replace(/\/+$/, "");
  if (!/^[^/]+\/[^/]+$/.test(options.repo)) throw new UsageError("--repo must be owner/name");
  return options;
}

function normalizeOrigin(value) {
  const url = new URL(value);
  if (!/^https?:$/.test(url.protocol) || url.username || url.password || url.search || url.hash) {
    throw new UsageError(`invalid HTTP origin: ${value}`);
  }
  return url.origin;
}

async function fetchResponse(url, options, fetchImpl) {
  try {
    return await fetchImpl(url, { ...options, signal: AbortSignal.timeout(options.timeoutMs) });
  } catch (error) {
    throw new Error(`request failed for ${url}: ${error.message}`);
  }
}

async function fetchJson(url, options, fetchImpl, acceptedStatuses = [200]) {
  const response = await fetchResponse(url, options, fetchImpl);
  let body;
  try {
    body = await response.json();
  } catch {
    throw new Error(`${url} returned non-JSON status ${response.status}`);
  }
  if (!acceptedStatuses.includes(response.status)) {
    throw new Error(`${url} returned status ${response.status}`);
  }
  return { response, body };
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function addCheck(result, name, operation) {
  try {
    const details = await operation();
    result.checks.push({ name, status: "pass", details });
  } catch (error) {
    result.checks.push({ name, status: "fail", details: { error: error.message } });
    result.ok = false;
  }
}

function repositoryPath(repo) {
  return repo.split("/").map(encodeURIComponent).join("/");
}

async function checkRelease(options, fetchImpl, tag, channel) {
  const releaseUrl = `${options.githubApiBase}/repos/${repositoryPath(options.repo)}/releases/tags/${encodeURIComponent(tag)}`;
  const { body: release } = await fetchJson(releaseUrl, options, fetchImpl);
  assert(!release.draft, `${tag} is a draft release`);
  const manifestAsset = release.assets?.find((asset) => asset.name === "latest.json");
  assert(manifestAsset?.browser_download_url, `${tag} has no latest.json asset`);
  const { body: manifest } = await fetchJson(manifestAsset.browser_download_url, options, fetchImpl);
  assert(manifest.schema_version === 1, `${tag} has unsupported schema_version`);
  assert(manifest.channel === channel, `${tag} channel is ${manifest.channel}, expected ${channel}`);
  assert(normalizeOrigin(manifest.api_origin) === options.expectedApiOrigin, `${tag} api_origin is ${manifest.api_origin}`);
  const artifact = manifest.artifacts?.[PLATFORM];
  const platform = manifest.platforms?.[PLATFORM];
  assert(artifact?.file, `${tag} manifest has no ${PLATFORM} artifact file`);
  assert(Number.isInteger(artifact.size_bytes) && artifact.size_bytes > 0, `${tag} artifact size is invalid`);
  assert(/^[a-f0-9]{64}$/i.test(artifact.sha256 ?? ""), `${tag} artifact sha256 is invalid`);
  assert(platform?.url, `${tag} platform URL is missing`);
  assert(typeof platform.signature === "string" && platform.signature.length > 0, `${tag} updater signature is missing`);
  const installer = release.assets?.find((asset) => asset.name === artifact.file);
  assert(installer, `${tag} release has no ${artifact.file} asset`);
  assert(installer.size === artifact.size_bytes, `${tag} installer size differs from manifest`);
  assert(installer.digest === `sha256:${artifact.sha256.toLowerCase()}`, `${tag} installer digest differs from manifest`);
  assert(platform.url === installer.browser_download_url, `${tag} installer URL differs from release asset`);
  return {
    tag,
    version: manifest.version,
    channel,
    api_origin: manifest.api_origin,
    installer: artifact.file,
    size_bytes: artifact.size_bytes,
    sha256: artifact.sha256.toLowerCase(),
    release_url: release.html_url,
  };
}

export async function runGate(options, fetchImpl = fetch) {
  const result = { timestamp: new Date().toISOString(), ok: true, checks: [] };
  await addCheck(result, "instance.health", async () => {
    const { body } = await fetchJson(`${options.baseUrl}/healthz`, options, fetchImpl);
    assert(body.status === "ok", "health status is not ok");
    return { url: `${options.baseUrl}/healthz`, status: body.status };
  });
  await addCheck(result, "instance.openapi", async () => {
    const { body } = await fetchJson(`${options.baseUrl}/openapi.json`, options, fetchImpl);
    const required = [
      "/api/v1/auth/register",
      "/api/v1/auth/resend-verification",
      "/api/v1/auth/verify-email",
    ];
    const missing = required.filter((path) => !body.paths?.[path]);
    assert(missing.length === 0, `missing registration routes: ${missing.join(", ")}`);
    return { url: `${options.baseUrl}/openapi.json`, registration_routes: required };
  });
  if (options.registration !== "present") {
    await addCheck(result, `instance.registration.${options.registration}`, async () => {
      const url = `${options.baseUrl}/api/v1/auth/register`;
      const { response, body } = await fetchJson(
        url,
        {
          ...options,
          method: "POST",
          headers: { "content-type": "application/json" },
          // The body is validated before the gate: a closed probe needs a
          // well-formed address, on the reserved .invalid TLD (RFC 2606).
          body: JSON.stringify({ email: options.registration === "closed" ? CLOSED_PROBE_EMAIL : "invalid" }),
        },
        fetchImpl,
        options.registration === "closed" ? [404] : [422],
      );
      if (options.registration === "closed") {
        assert(body.detail?.error_code === "registration_unavailable", "registration route is absent or not closed by the gate");
      }
      return { url, status: response.status, mode: options.registration };
    });
  }
  await addCheck(result, "release.beta", () => checkRelease(options, fetchImpl, options.betaTag, "beta"));
  if (options.requireStable) {
    await addCheck(result, "release.stable", () => checkRelease(options, fetchImpl, options.stableTag, "stable"));
  }
  return result;
}

export async function main(argv = process.argv.slice(2), io = console) {
  let options;
  try {
    options = parseArgs(argv);
  } catch (error) {
    io.error(JSON.stringify({ ok: false, error: error.message }));
    return 2;
  }
  const result = await runGate(options);
  io.log(JSON.stringify(result));
  return result.ok ? 0 : 1;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exitCode = await main();
}
