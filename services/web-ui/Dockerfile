# Build the SPA, then serve it with nginx, proxying /api/agent and /api/fleet to the backends.
FROM node:22-alpine AS build
WORKDIR /app
COPY services/web-ui/package.json services/web-ui/package-lock.json ./
RUN npm ci
COPY services/web-ui/ ./
RUN npm run build

FROM nginx:1.29-alpine
COPY services/web-ui/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
