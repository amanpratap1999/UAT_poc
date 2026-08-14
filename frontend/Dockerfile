# Stage 1: Build
FROM node:20-alpine AS builder

WORKDIR /app

# Copy dependency manifests first for layer caching
COPY package.json package-lock.json* ./
RUN npm ci --frozen-lockfile

# Copy source
COPY . .

# Build with production env (VITE_API_BASE_URL passed at runtime via nginx proxy)
RUN npm run build

# Stage 2: Serve with nginx
FROM nginx:alpine AS runner

# Copy nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy built assets
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
