# Olmavax A.I — container image
# Node side only. The OpenCharvis Python agent runs as an optional sidecar.
FROM node:20-alpine

WORKDIR /app

COPY package*.json ./
COPY server/    ./server/
COPY public/    ./public/
COPY extension/ ./extension/
COPY python/    ./python/
COPY advanced/  ./advanced/
COPY tests/     ./tests/
COPY .env.example ./

# Run unprivileged and store chat data on a volume.
RUN mkdir -p /app/data && chown -R node:node /app
USER node
VOLUME ["/app/data"]

# Bind to localhost inside the container; publish explicitly with -p.
ENV HOST=0.0.0.0 \
    PORT=8787 \
    OLMAVAX_DATA=/app/data

EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=4s --start-period=6s \
  CMD wget -qO- http://127.0.0.1:8787/api/status >/dev/null || exit 1

CMD ["node", "server/server.js"]
