# Build stage
FROM node:22-alpine AS builder

WORKDIR /app
COPY dashboard/package*.json ./
RUN npm ci

COPY dashboard/ ./
# `src/roadmapFixtures.ts` imports the shared contract fixtures (`../../contracts/
# fixtures/*.json`), which live outside `dashboard/`: keep them at that relative path.
COPY contracts/fixtures /contracts/fixtures
# Same-origin API calls: Caddy proxies /api to the API service.
ENV VITE_STUDIO_API_URL=""
RUN npm run build

# Serve stage: lightweight static server
FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY docker/dashboard.nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
