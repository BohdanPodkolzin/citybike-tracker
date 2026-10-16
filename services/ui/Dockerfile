FROM node:22-alpine AS build

WORKDIR /src


COPY package.json package-lock.json* ./

RUN if [ -f package-lock.json ]; then npm ci --no-audit --no-fund; else npm install --no-audit --no-fund; fi

COPY index.html vite.config.js ./

COPY src ./src

RUN npm run build


FROM nginxinc/nginx-unprivileged:1.27-alpine

COPY nginx.conf.template /etc/nginx/templates/default.conf.template

COPY --from=build /src/dist /usr/share/nginx/html

ENV HISTORY_URL=http://127.0.0.1:8002

EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q --spider http://127.0.0.1:8080/ || exit 1
# CMD is inherited: the image's entrypoint renders the template, then starts nginx
