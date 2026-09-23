# Redis TLS Certificates

This directory holds the TLS certificates used by the Redis service in
`docker-compose.yml`.

## Generating Self-Signed Certificates (Development)

```bash
# Create this directory
mkdir -p tls/redis && cd tls/redis

# Generate CA key and cert
openssl genrsa -out ca.key 4096
openssl req -x509 -new -nodes -key ca.key -sha256 -days 3650 \
  -subj "/CN=UAT-Redis-CA" -out ca.crt

# Generate server key and CSR
openssl genrsa -out redis.key 2048
openssl req -new -key redis.key -subj "/CN=redis" -out redis.csr

# Sign server cert with CA
openssl x509 -req -in redis.csr -CA ca.crt -CAkey ca.key \
  -CAcreateserial -out redis.crt -days 365 -sha256

# Cleanup
rm redis.csr ca.key ca.srl
```

## Production

In production, use certificates issued by your organization's PKI or a
secrets manager (Vault, AWS ACM, etc.). Mount them at `/tls/` inside the
Redis container via the `REDIS_TLS_DIR` environment variable.

## Skipping TLS in Development

If you need to run without TLS locally, create a
`docker-compose.override.yml`:

```yaml
services:
  redis:
    command:
      [
        "redis-server",
        "--requirepass",
        "${REDIS_PASSWORD}",
        "--appendonly",
        "yes",
      ]
    expose:
      - "6379"
    volumes:
      - redisdata:/data
```

And set `REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379/0` in your `.env`.
