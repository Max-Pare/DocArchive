# --- build stage ---
# Node 24 LTS. Node 20 is past EOL (April 2026), and jsdom (a test dependency
# resolved by `npm ci`) requires ^22.22.2 || ^24.15.0 || >=26.0.0.
FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# API is reverse-proxied at /api by Caddy in production
ENV VITE_API_BASE=/api
RUN npm run build

# --- serve stage ---
FROM nginx:1.31-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
