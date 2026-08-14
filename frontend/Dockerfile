# Stage 1: Build
FROM node:20-alpine AS builder

WORKDIR /app

# Build-time argument for Vite environment configuration
ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

# Copy dependency manifests first for layer caching
COPY package.json package-lock.json* ./
RUN npm ci --frozen-lockfile

# Copy source
COPY . .

# Build with VITE_API_BASE_URL embedded in client bundle
RUN npm run build

# Stage 2: Serve with nginx
FROM nginx:alpine AS runner

# Copy nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy built assets
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
