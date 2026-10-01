# Imagen del frontend. Construir desde la raiz del proyecto:
#   docker build -f frontend/Dockerfile -t pf-frontend --build-arg VITE_API_BASE_URL=http://localhost:8000 ..
#
# Vite incrusta VITE_API_BASE_URL en el bundle en build time (import.meta.env), no en runtime --
# por eso es un ARG de build, no un ENV del contenedor final. Tiene que ser una URL alcanzable
# desde el NAVEGADOR del usuario, no el nombre del servicio en la red de docker-compose (p.ej.
# "http://localhost:8000", nunca "http://api:8000": el navegador no resuelve nombres de la red
# interna de Docker). El dia que haya un dominio real (sin nginx todavia, ver docs/09), este
# build-arg es lo unico que cambia.
#
# Sin nginx a proposito (docs/09): `serve` alcanza para servir el build estatico de produccion
# de Vite sin sumar una pieza mas a la infraestructura antes de que haga falta.

FROM node:22-slim AS build
WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/index.html frontend/vite.config.ts frontend/tsconfig*.json frontend/tailwind.config.js frontend/postcss.config.js ./
COPY frontend/src/ ./src/
COPY frontend/public/ ./public/

ARG VITE_API_BASE_URL=http://localhost:8000
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM node:22-slim
WORKDIR /app
RUN npm install --global serve@14
COPY --from=build /app/dist ./dist

EXPOSE 5173
CMD ["serve", "-s", "dist", "-l", "5173"]
