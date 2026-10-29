# --- build: compile the Vite/React app to static assets --------------------
FROM node:20-slim AS build

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Vite has no runtime env — every VITE_* var is baked into the static bundle
# at build time (see vite.config.ts / src/lib/firebase.ts), so it has to
# arrive as a build ARG, not a container-run-time environment variable.
#
# The Firebase values are the browser-safe Web SDK config, not secrets:
# https://firebase.google.com/docs/projects/api-keys
# Example:
#   docker build \
#     --build-arg VITE_API_URL=https://api.example.com \
#     --build-arg VITE_FIREBASE_API_KEY=... \
#     --build-arg VITE_FIREBASE_AUTH_DOMAIN=my-project.firebaseapp.com \
#     --build-arg VITE_FIREBASE_PROJECT_ID=my-project \
#     --build-arg VITE_FIREBASE_APP_ID=1:123:web:abc \
#     .
ARG VITE_API_URL
ARG VITE_FIREBASE_API_KEY
ARG VITE_FIREBASE_AUTH_DOMAIN
ARG VITE_FIREBASE_PROJECT_ID
ARG VITE_FIREBASE_MESSAGING_SENDER_ID
ARG VITE_FIREBASE_APP_ID

ENV VITE_API_URL=$VITE_API_URL \
    VITE_FIREBASE_API_KEY=$VITE_FIREBASE_API_KEY \
    VITE_FIREBASE_AUTH_DOMAIN=$VITE_FIREBASE_AUTH_DOMAIN \
    VITE_FIREBASE_PROJECT_ID=$VITE_FIREBASE_PROJECT_ID \
    VITE_FIREBASE_MESSAGING_SENDER_ID=$VITE_FIREBASE_MESSAGING_SENDER_ID \
    VITE_FIREBASE_APP_ID=$VITE_FIREBASE_APP_ID

RUN npm run build

# --- serve: static files behind nginx, SPA fallback routing ---------------
FROM nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -q -O- http://localhost/health || exit 1
