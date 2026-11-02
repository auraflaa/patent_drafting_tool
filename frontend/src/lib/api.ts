import { formatFileSize } from "./format";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

/** Returns a fresh Firebase ID token for the signed-in user, or null. */
type TokenProvider = () => Promise<string | null>;

let tokenProvider: TokenProvider = async () => null;

/**
 * Called once by AuthContext. Firebase ID tokens expire after an hour, so the
 * provider is asked for a token on every request instead of a cached string
 * being pushed in here.
 */
export function setTokenProvider(provider: TokenProvider) {
  tokenProvider = provider;
}

/**
 * Called once by AuthContext. A 401 means the API no longer accepts this
 * session (expired, revoked, or account removed), so every caller would
 * otherwise just show "sign in again" while staying on the broken page.
 */
type UnauthorizedHandler = () => void;

let unauthorizedHandler: UnauthorizedHandler | null = null;
let reportedUnauthorized = false;

export function setUnauthorizedHandler(handler: UnauthorizedHandler | null) {
  unauthorizedHandler = handler;
  reportedUnauthorized = false;
}

/** Tell the app the session is dead, at most once per signed-in session. */
function notifyUnauthorized(context: string, path: string, detail: string) {
  logError(context, { path, status: 401, detail });
  if (reportedUnauthorized) return;
  reportedUnauthorized = true;
  try {
    unauthorizedHandler?.();
  } catch (error) {
    logError("unauthorizedHandler", error);
  }
}

/** Token failures that really mean the session is gone, not a network blip. */
const FATAL_TOKEN_ERRORS = new Set([
  "auth/user-disabled",
  "auth/user-not-found",
  "auth/user-token-expired",
  "auth/invalid-user-token",
]);

/**
 * Ask Firebase for the current ID token.
 *
 * Returning `null` here means "nobody is signed in". A refresh that *failed*
 * must throw instead: sending the request unauthenticated turns a network
 * blip into a 401, and a 401 deletes the user's session.
 */
async function authHeaders(): Promise<Record<string, string>> {
  let token: string | null;
  try {
    token = await tokenProvider();
  } catch (error) {
    const code = (error as { code?: string } | null)?.code ?? "";
    if (FATAL_TOKEN_ERRORS.has(code)) {
      notifyUnauthorized("authHeaders", "(token refresh)", code);
      throw new ApiError(401, "Your session has expired. Please sign in again.");
    }
    logError("authHeaders.tokenRefresh", error);
    throw new ApiError(503, "Could not refresh your session with Firebase.");
  }
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/** Log an error for debugging without surfacing it to the user. */
export function logError(context: string, error: unknown): void {
  console.warn(`[${context}]`, error);
}

/** Ordinary API calls answer in well under a second; cap the wait anyway. */
export const REQUEST_TIMEOUT_MS = 30_000;
/** Uploads, downloads and in-process document generation legitimately run long. */
export const LONG_REQUEST_TIMEOUT_MS = 180_000;

/**
 * `fetch` with a deadline.
 *
 * Without one, a backend that is alive but stalled (a wedged datastore
 * connection) leaves every screen spinning with no way out. The deadline turns
 * that into a clear, retryable error.
 */
async function fetchWithTimeout(
  url: string,
  init: RequestInit,
  timeoutMs: number,
): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } catch (error) {
    if ((error as { name?: string } | null)?.name === "AbortError") {
      throw new ApiError(
        504,
        `The server did not respond within ${Math.round(timeoutMs / 1000)} seconds.`,
      );
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Pull a displayable message out of a FastAPI error body.
 *
 * FastAPI sends `{"detail": "..."}` for HTTPException and
 * `{"detail": [{loc, msg, type}, ...]}` for request-validation (422) errors.
 * Only strings are accepted; anything else returns `null` so a validation
 * array can never reach the UI as `[object Object]`.
 */
function detailFromBody(body: unknown): string | null {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string" && detail.trim()) return detail.trim();
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        const msg = (item as { msg?: unknown } | null)?.msg;
        return typeof msg === "string" ? msg.trim() : "";
      })
      .filter(Boolean);
    if (messages.length) return messages.join(" ");
  }
  return null;
}

/** Read the server's error text from a failed response, or null if unusable. */
async function readErrorDetail(response: Response): Promise<string | null> {
  try {
    return detailFromBody(await response.json());
  } catch {
    return null;
  }
}

/** True when `message` is this module's own placeholder, not server text. */
function isGenericStatusMessage(message: string): boolean {
  return /^(Request|Upload|Download) failed \(\d+\)$/.test(message);
}

/** Status-code-to-friendly-message map for user-visible errors.
 * Technical details are never shown to the user — they are logged
 * via logError() and only a friendly message is returned. */
function friendlyMessage(status: number): string {
  switch (status) {
    case 401:
      return "Your session has expired. Please sign in again.";
    case 403:
      return "You don't have permission to do that.";
    case 404:
      return "The requested item could not be found.";
    case 429:
      return "Too many requests. Please wait a moment and try again.";
    case 413:
      return "The file is too large for this deployment.";
    case 415:
      return "This file type is not supported.";
    case 503:
      return "The server is temporarily unavailable. Please try again in a moment.";
    case 504:
      return "The server took too long to respond. Please try again.";
    default:
      return "Something went wrong. The error has been logged.";
  }
}

/**
 * Convert an API error into a user-friendly message.
 *
 * The caller passes a `context` string (used for the log line) and a
 * `fallback` message (used when the error has no status code — e.g. a
 * network failure). The technical error is logged via `logError`.
 *
 * 4xx responses carry curated, actionable text from the backend ("Complete
 * the required questionnaire fields first: ...", "Only the assigned Patent
 * Agent ... can generate drafts."), so that text is shown instead of a
 * generic sentence. 5xx responses can leak implementation detail, so they
 * keep the stable generic line.
 */
export function getFriendlyError(
  context: string,
  error: unknown,
  fallback: string,
): string {
  logError(context, error);
  if (error instanceof ApiError) {
    if (error.status === 401) {
      return "Your session has expired. Please sign in again.";
    }
    const isClientError = error.status >= 400 && error.status < 500;
    if (
      isClientError &&
      error.status !== 429 &&
      !isGenericStatusMessage(error.message)
    ) {
      return error.message;
    }
    return friendlyMessage(error.status);
  }
  // Non-API errors (network, JSON parse, etc.) get the fallback, which
  // should already be a friendly sentence written by the caller.
  return fallback;
}

/** Public limits reported by `GET /api/config/capabilities`. */
export interface RuntimeCapabilities {
  deployment_target: "self_hosted" | "vercel";
  max_upload_size_bytes: number;
  max_request_body_bytes: number;
  /** Largest file that fits in one Firestore document after compression. */
  max_stored_size_bytes: number;
}

let capabilitiesRequest: Promise<RuntimeCapabilities> | null = null;

/**
 * Deployment limits are fixed for the life of a backend instance, so one
 * request per page load is enough. A failed lookup is retried on the next call
 * rather than poisoning the cache.
 */
export function getRuntimeCapabilities(): Promise<RuntimeCapabilities> {
  if (!capabilitiesRequest) {
    capabilitiesRequest = fetchWithTimeout(
      `${API_URL}/api/config/capabilities`,
      { cache: "no-store" },
      REQUEST_TIMEOUT_MS,
    )
      .then(async (response) => {
        if (!response.ok) {
          throw new ApiError(
            response.status,
            `Could not load deployment capabilities (${response.status})`,
          );
        }
        return (await response.json()) as RuntimeCapabilities;
      })
      .catch((error: unknown) => {
        capabilitiesRequest = null;
        throw error;
      });
  }
  return capabilitiesRequest;
}

interface ApiFetchOptions extends RequestInit {
  auth?: boolean; // defaults to true
  /** Override the 30 s deadline (draft generation legitimately takes longer). */
  timeoutMs?: number;
}

export async function apiFetch<T>(path: string, options: ApiFetchOptions = {}): Promise<T> {
  const {
    auth = true,
    headers,
    timeoutMs = REQUEST_TIMEOUT_MS,
    ...rest
  } = options;

  const finalHeaders: Record<string, string> = {
    "Content-Type": "application/json",
    ...(headers as Record<string, string> | undefined),
    ...(auth ? await authHeaders() : {}),
  };

  const response = await fetchWithTimeout(
    `${API_URL}${path}`,
    { ...rest, headers: finalHeaders },
    timeoutMs,
  );

  if (!response.ok) {
    let detail = (await readErrorDetail(response)) ?? `Request failed (${response.status})`;
    // Auth warnings are logged for debugging but never shown to users.
    if (response.status === 401) {
      notifyUnauthorized("apiFetch", path, detail);
      detail = "Your session has expired. Please sign in again.";
    }
    throw new ApiError(response.status, detail);
  }

  reportedUnauthorized = false;

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** For multipart uploads — apiFetch always sends Content-Type: application/json,
 * which breaks a multipart body, so this builds its own fetch with just the
 * Authorization header and lets the browser set the multipart boundary. */
export async function apiUpload<T>(
  path: string,
  file: File,
  fieldName = "upload",
  query?: Record<string, string | number | boolean>,
): Promise<T> {
  const capabilities = await getRuntimeCapabilities().catch(() => null);
  if (capabilities && file.size > capabilities.max_upload_size_bytes) {
    throw new ApiError(
      413,
      `"${file.name}" is ${formatFileSize(file.size)}; this deployment accepts files up to ` +
        `${formatFileSize(capabilities.max_upload_size_bytes)}.`,
    );
  }

  const formData = new FormData();
  formData.append(fieldName, file);

  const finalHeaders: Record<string, string> = { ...(await authHeaders()) };

  const qs = query
    ? "?" + new URLSearchParams(Object.entries(query).map(([k, v]) => [k, String(v)])).toString()
    : "";

  const response = await fetchWithTimeout(
    `${API_URL}${path}${qs}`,
    {
      method: "POST",
      headers: finalHeaders,
      body: formData,
    },
    LONG_REQUEST_TIMEOUT_MS,
  );

  if (!response.ok) {
    let detail = (await readErrorDetail(response)) ?? `Upload failed (${response.status})`;
    if (response.status === 401) {
      notifyUnauthorized("apiUpload", path, detail);
      detail = "Your session has expired. Please sign in again.";
    }
    throw new ApiError(response.status, detail);
  }

  reportedUnauthorized = false;

  return (await response.json()) as T;
}

/** Read the filename from Content-Disposition.
 *
 * The backend sends an ASCII `filename` plus an RFC 5987 `filename*` for
 * non-Latin-1 names; prefer the encoded form so a Japanese or emoji filename
 * survives. `response.headers.get` only exposes this header because the API
 * lists it in `Access-Control-Expose-Headers`.
 */
function filenameFromDisposition(disposition: string, fallback: string): string {
  const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (encoded) {
    try {
      return decodeURIComponent(encoded[1].trim());
    } catch {
      // malformed escape — fall through to the ASCII parameter
    }
  }
  const quoted = disposition.match(/filename="([^"]*)"/i);
  if (quoted) return quoted[1];
  const bare = disposition.match(/filename=([^;]+)/i);
  return bare ? bare[1].trim().replace(/^"|"$/g, "") : fallback;
}

/** For binary downloads (PDF/DOCX) — apiFetch always parses JSON, so this
 * fetches the blob directly, reads the filename from Content-Disposition,
 * and triggers a normal browser download via a throwaway <a> tag. */
export async function apiDownload(path: string, fallbackFilename: string): Promise<void> {
  const finalHeaders: Record<string, string> = { ...(await authHeaders()) };

  const response = await fetchWithTimeout(
    `${API_URL}${path}`,
    { headers: finalHeaders },
    LONG_REQUEST_TIMEOUT_MS,
  );
  if (!response.ok) {
    let detail = (await readErrorDetail(response)) ?? `Download failed (${response.status})`;
    if (response.status === 401) {
      notifyUnauthorized("apiDownload", path, detail);
      detail = "Your session has expired. Please sign in again.";
    }
    throw new ApiError(response.status, detail);
  }

  reportedUnauthorized = false;

  const disposition = response.headers.get("Content-Disposition") || "";
  const filename = filenameFromDisposition(disposition, fallbackFilename);

  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Revoking immediately can cancel the download in some browsers, because the
  // navigation to the blob URL has not started yet. Give it time to finish.
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}
