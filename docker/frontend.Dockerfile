# Frontend dev container — Node 20 (matches CI and Slate runtime)
FROM node:20-slim

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# Source code mounted as volume in docker-compose (Vite hot-reload)
COPY frontend/ ./

EXPOSE 5173
