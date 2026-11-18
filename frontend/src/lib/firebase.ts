/**
 * Firebase Web SDK bootstrap.
 *
 * Only the browser-safe config lives here (all `VITE_FIREBASE_*` values are
 * public by design — see https://firebase.google.com/docs/projects/api-keys).
 * The Admin service-account key stays server-side in `backend/secrets/`.
 *
 * Nothing is initialised at import time: a checkout without a Firebase project
 * should still render the login screen with a configuration message instead of
 * crashing on a blank page.
 */
import { initializeApp, type FirebaseApp } from "firebase/app";
import { getAuth, type Auth } from "firebase/auth";

const config = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
};

export class FirebaseConfigError extends Error {
  constructor() {
    super(
      "Firebase is not configured. Copy frontend/.env.example to frontend/.env " +
        "and fill in the VITE_FIREBASE_* values from the Firebase console.",
    );
    this.name = "FirebaseConfigError";
  }
}

/** True when the browser-safe Firebase config is present. */
export function isFirebaseConfigured(): boolean {
  return Boolean(config.apiKey && config.authDomain && config.projectId && config.appId);
}

let cachedApp: FirebaseApp | null = null;
let cachedAuth: Auth | null = null;

/** The singleton Firebase Auth instance, or a clear error if unconfigured. */
export function firebaseAuth(): Auth {
  if (!isFirebaseConfigured()) throw new FirebaseConfigError();
  if (!cachedAuth) {
    cachedApp = initializeApp(config);
    cachedAuth = getAuth(cachedApp);
  }
  return cachedAuth;
}
