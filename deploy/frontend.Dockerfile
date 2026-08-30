# Cloud frontend image: production Vite build served by nginx (internal only).
# The public entry is crypto-proxy (Caddy) which forwards / to this service.
# Build context: repository root (docker build -f deploy/frontend.Dockerfile .)
FROM node:20-alpine AS build

ARG VITE_API_BASE_URL=/api
ARG VITE_WS_URL=wss://localhost/ws
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_WS_URL=$VITE_WS_URL

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run typecheck && npm test -- --run && npm run build

FROM nginx:1.27-alpine AS serve
COPY --from=build /app/dist /usr/share/nginx/html
RUN printf 'server {\n\
    listen 80;\n\
    server_name _;\n\
    root /usr/share/nginx/html;\n\
    index index.html;\n\
    location / { try_files $uri $uri/ /index.html; }\n\
    location = /healthz { access_log off; return 200 "frontend ok"; }\n\
}\n' > /etc/nginx/conf.d/default.conf
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://127.0.0.1/healthz || exit 1
