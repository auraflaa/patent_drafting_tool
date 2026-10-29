import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";
import {
  GoogleAuthProvider,
  onAuthStateChanged,
  signInWithPopup,
  signInWithRedirect,
  signOut,
  type User as FirebaseUser,
} from "firebase/auth";
import {
  apiFetch,
  setTokenProvider,
  setUnauthorizedHandler,
  ApiError,
  logError,
} from "../lib/api";
import { FirebaseConfigError, firebaseAuth, isFirebaseConfigured } from "../lib/firebase";
import type { MeResponse, UserOut } from "../lib/types";

// Product requirement: a session ends after 30 minutes of inactivity. Firebase
// itself keeps the browser session alive and refreshes ID tokens in the
// background, so the idle rule is enforced here instead of through JWT expiry.
const IDLE_TIMEOUT_MS = 30 * 60_000;
const IDLE_CHECK_INTERVAL_MS = 60_000;
const ACTIVITY_EVENTS = ["mousedown", "keydown", "scroll", "touchstart"] as const;

type AuthStatus = "loading" | "unauthenticated" | "pending" | "approved";

interface AuthContextValue {
  status: AuthStatus;
  user: UserOut | null;
  permissions: string[];
  /** Set when Firebase Web config is missing from the build. */
  configError: string | null;
  /** Set when the API could not describe the signed-in user (e.g. 5xx). */
  sessionError: string | null;
  hasPermission: (code: string) => boolean;
  hasRole: (code: string) => boolean;
  signInWithGoogle: () => Promise<void>;
  logout: () => void;
  refreshMe: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const PENDING_ACCOUNT_STATUSES = new Set(["Pending", "Rejected", "Suspended"]);

const CACHE_VERSION = 2;
const PROFILE_CACHE_KEY = `patent-platform:profile:v${CACHE_VERSION}`;
// Older keys are ignored; drop them so a schema change cannot resurrect them.
const LEGACY_CACHE_KEYS = ["patent-platform:profile"];

interface CachedProfile {
  user: UserOut;
  permissions: string[];
  status: AuthStatus;
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

/** A cache entry is untrusted input: it can be stale, edited, or half-written. */
function isCachedProfile(value: unknown): value is CachedProfile {
  if (!value || typeof value !== "object") return false;
  const entry = value as { user?: unknown; permissions?: unknown; status?: unknown };
  if (entry.status !== "approved" && entry.status !== "pending") return false;
  if (!isStringArray(entry.permissions)) return false;
  if (!entry.user || typeof entry.user !== "object") return false;
  const user = entry.user as Partial<UserOut>;
  return (
    typeof user.id === "string" &&
    typeof user.email === "string" &&
    typeof user.full_name === "string" &&
    typeof user.account_status === "string" &&
    isStringArray(user.roles)
  );
}

/** Read the cached profile from localStorage (if any and still valid). */
function readCachedProfile(): CachedProfile | null {
  try {
    for (const key of LEGACY_CACHE_KEYS) localStorage.removeItem(key);
    const raw = localStorage.getItem(PROFILE_CACHE_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    return isCachedProfile(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

/** Persist the profile to localStorage so it survives page reloads. */
function writeCachedProfile(user: UserOut | null, permissions: string[], status: AuthStatus) {
  try {
    if (user && (status === "approved" || status === "pending")) {
      localStorage.setItem(PROFILE_CACHE_KEY, JSON.stringify({ user, permissions, status }));
    } else {
      localStorage.removeItem(PROFILE_CACHE_KEY);
    }
  } catch {
    // localStorage may be unavailable (private browsing) — ignore.
  }
}

const GOOGLE_PROVIDER = new GoogleAuthProvider();
GOOGLE_PROVIDER.setCustomParameters({ prompt: "select_account" });

/** Pop-ups are blocked or unsupported in a few environments; fall back to a full redirect. */
function shouldFallBackToRedirect(error: unknown): boolean {
  const code = (error as { code?: string } | null)?.code;
  return (
    code === "auth/popup-blocked" ||
    code === "auth/popup-closed-by-user" ||
    code === "auth/cancelled-popup-request" ||
    code === "auth/operation-not-supported-in-this-environment"
  );
}

export function AuthProvider({ children }: { children: ReactNode }) {
  // Lazy initialiser: localStorage is read once, not on every render.
  const [cached] = useState(readCachedProfile);
  const [status, setStatus] = useState<AuthStatus>(cached?.status ?? "loading");
  const [user, setUser] = useState<UserOut | null>(cached?.user ?? null);
  const [permissions, setPermissions] = useState<string[]>(cached?.permissions ?? []);
  const [configError, setConfigError] = useState<string | null>(
    isFirebaseConfigured() ? null : new FirebaseConfigError().message,
  );
  const [sessionError, setSessionError] = useState<string | null>(null);
  const lastActivityRef = useRef<number>(Date.now());

  const clearSession = useCallback(() => {
    setUser(null);
    setPermissions([]);
    setStatus("unauthenticated");
    writeCachedProfile(null, [], "unauthenticated");
  }, []);

  // Every API call asks Firebase for the current ID token, so a token that is
  // refreshed or revoked in another tab is picked up on the next request.
  useEffect(() => {
    if (!isFirebaseConfigured()) {
      setTokenProvider(async () => null);
      return;
    }
    setTokenProvider(async () => {
      try {
        const current = firebaseAuth().currentUser;
        return current ? await current.getIdToken() : null;
      } catch {
        return null;
      }
    });
    return () => setTokenProvider(async () => null);
  }, []);

  // A 401 from any request means the session is no longer usable. Drop the
  // cached profile and Firebase session so ProtectedRoute sends the user back
  // to /login instead of leaving a half-dead page on screen. Deliberately not
  // calling logout() here: its /api/auth/logout ACK would itself 401.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      try {
        void signOut(firebaseAuth());
      } catch {
        // unconfigured Firebase — clearing local state is enough
      }
      clearSession();
    });
    return () => setUnauthorizedHandler(null);
  }, [clearSession]);

  const loadMe = useCallback(async () => {
    try {
      const me = await apiFetch<MeResponse>("/api/auth/me");
      setUser(me.user);
      setPermissions(me.permissions);
      setSessionError(null);
      const nextStatus = PENDING_ACCOUNT_STATUSES.has(me.user.account_status)
        ? "pending"
        : "approved";
      setStatus(nextStatus);
      writeCachedProfile(me.user, me.permissions, nextStatus);
    } catch (error) {
      logError("loadMe", error);
      // A 401 means Firebase no longer accepts the session; anything else
      // (network, 5xx) also leaves us unable to describe the user.
      if (error instanceof ApiError && error.status === 401) {
        try {
          await signOut(firebaseAuth());
        } catch {
          // nothing else to do — the local state is cleared below
        }
      } else {
        setSessionError(
          "The API could not load your account. Try again shortly.",
        );
      }
      clearSession();
    }
  }, [clearSession]);

  const handleSignedIn = useCallback(
    async (firebaseUser: FirebaseUser | null) => {
      if (!firebaseUser) {
        clearSession();
        return;
      }
      // Ensure the first request after a redirect sign-in carries a token.
      try {
        await firebaseUser.getIdToken();
      } catch {
        clearSession();
        return;
      }
      await loadMe();
    },
    [clearSession, loadMe],
  );

  useEffect(() => {
    if (!isFirebaseConfigured()) {
      setStatus("unauthenticated");
      return;
    }
    let unsubscribe: (() => void) | undefined;
    try {
      unsubscribe = onAuthStateChanged(firebaseAuth(), (firebaseUser) => {
        void handleSignedIn(firebaseUser);
      });
    } catch (error) {
      setConfigError(
        error instanceof Error ? error.message : "Firebase could not be initialised.",
      );
      setStatus("unauthenticated");
    }
    return () => unsubscribe?.();
  }, [handleSignedIn]);

  const signInWithGoogle = useCallback(async () => {
    const auth = firebaseAuth();
    setSessionError(null);
    try {
      await signInWithPopup(auth, GOOGLE_PROVIDER);
    } catch (error) {
      if (shouldFallBackToRedirect(error)) {
        await signInWithRedirect(auth, GOOGLE_PROVIDER);
        return;
      }
      throw error;
    }
  }, []);

  const logout = useCallback(() => {
    // Best-effort ACK; the real session lives in Firebase, not the API.
    apiFetch("/api/auth/logout", { method: "POST" }).catch(() => {});
    try {
      void signOut(firebaseAuth());
    } catch {
      // already signed out or unconfigured
    }
    clearSession();
  }, [clearSession]);

  // Track activity for the idle rule.
  useEffect(() => {
    const markActive = () => {
      lastActivityRef.current = Date.now();
    };
    ACTIVITY_EVENTS.forEach((event) => window.addEventListener(event, markActive));
    return () =>
      ACTIVITY_EVENTS.forEach((event) => window.removeEventListener(event, markActive));
  }, []);

  useEffect(() => {
    if (status !== "approved") return;
    const interval = setInterval(() => {
      if (Date.now() - lastActivityRef.current > IDLE_TIMEOUT_MS) {
        logout();
      }
    }, IDLE_CHECK_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [status, logout]);

  const hasPermission = useCallback(
    (code: string) => permissions.includes(code),
    [permissions],
  );
  const hasRole = useCallback((code: string) => user?.roles.includes(code) ?? false, [user]);

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      user,
      permissions,
      configError,
      sessionError,
      hasPermission,
      hasRole,
      signInWithGoogle,
      logout,
      refreshMe: loadMe,
    }),
    [
      status,
      user,
      permissions,
      configError,
      sessionError,
      hasPermission,
      hasRole,
      signInWithGoogle,
      logout,
      loadMe,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
