FROM node:22-alpine AS build

WORKDIR /app
COPY package.json package-lock.json ./
ARG NPM_CONFIG_REGISTRY=https://registry.npmjs.org
ARG NPM_CONFIG_REPLACE_REGISTRY_HOST=always
RUN npm ci --no-audit --no-fund
COPY . .
ARG NEXT_PUBLIC_API_URL=/api
ARG NEXT_PUBLIC_ALLOW_REGISTRATION=false
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_ALLOW_REGISTRATION=$NEXT_PUBLIC_ALLOW_REGISTRATION
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
USER node
EXPOSE 3000
CMD ["node", "server.js"]
