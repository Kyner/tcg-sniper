# Build do front (Vite) numa etapa com Node; a imagem final é só o Caddy com os arquivos prontos.
FROM node:24.22.1-alpine AS build
WORKDIR /web
COPY package.json package-lock.json .npmrc ./
RUN npm ci
COPY . .
RUN npm run build

FROM caddy:2.10.0-alpine
COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=build /web/dist /srv
EXPOSE 8090
