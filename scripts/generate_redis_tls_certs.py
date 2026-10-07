"""Generate TLS certificates for Redis in local development and test environments.

Creates:
- ca.crt & ca.key (Certificate Authority)
- redis.crt & redis.key (Server certificate with SAN for 'redis' and 'localhost')
- client.crt & client.key (Client certificate for mTLS)

Private keys (*.key) are strictly excluded from git via .gitignore.
"""

from __future__ import annotations

import argparse
import datetime
import ipaddress
import os
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def generate_certs(output_dir: Path, valid_days: int = 365) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    backend = default_backend()
    now = datetime.datetime.now(datetime.timezone.utc)
    expiry = now + datetime.timedelta(days=valid_days)

    print(f"[*] Generating Redis TLS certificates in: {output_dir}")

    # 1. Generate CA Key & Self-Signed Cert
    ca_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=backend,
    )
    ca_name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "ServiceNow UAT Redis CA"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ServiceNow UAT Engine"),
    ])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(expiry)
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=None),
            critical=True,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256(), backend)
    )

    # 2. Generate Redis Server Key & Cert (with SAN)
    server_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=backend,
    )
    server_name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "redis"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ServiceNow UAT Engine"),
    ])
    server_san = x509.SubjectAlternativeName([
        x509.DNSName("redis"),
        x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
    ])
    server_cert = (
        x509.CertificateBuilder()
        .subject_name(server_name)
        .issuer_name(ca_name)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(expiry)
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([
                ExtendedKeyUsageOID.SERVER_AUTH,
                ExtendedKeyUsageOID.CLIENT_AUTH,
            ]),
            critical=False,
        )
        .add_extension(server_san, critical=False)
        .sign(ca_key, hashes.SHA256(), backend)
    )

    # 3. Write files
    ca_key_path = output_dir / "ca.key"
    ca_crt_path = output_dir / "ca.crt"
    redis_key_path = output_dir / "redis.key"
    redis_crt_path = output_dir / "redis.crt"
    # Audit issue I41 (P2): the docstring at the top of this file promised
    # to generate client.crt & client.key for mTLS, but the implementation
    # only emitted ca.key, ca.crt, redis.key, redis.crt. The missing client
    # certificate forces `--tls-auth-clients no` in docker-compose.yml
    # (line 44), weakening TLS to "encrypt but no client auth" — any
    # process that can reach the Redis port can connect (TLS verifies the
    # server but Redis does not verify the client). Fix: generate a
    # client cert with ExtendedKeyUsage=[CLIENT_AUTH] signed by the same
    # CA, so operators can switch to `--tls-auth-clients yes` for true mTLS.
    client_key_path = output_dir / "client.key"
    client_crt_path = output_dir / "client.crt"

    ca_key_path.write_bytes(
        ca_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    ca_crt_path.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))

    redis_key_path.write_bytes(
        server_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    redis_crt_path.write_bytes(server_cert.public_bytes(serialization.Encoding.PEM))

    # Audit issue I41 (P2): generate client cert for mTLS.
    # The client cert is signed by the same CA as the server cert so a
    # single `--tls-ca-cert-file ca.crt` on the Redis server can verify
    # both. ExtendedKeyUsage is CLIENT_AUTH-only (the client is NOT a
    # server), distinguishing it from the redis.crt which has both
    # SERVER_AUTH and CLIENT_AUTH (Redis server can also act as a client
    # in cluster mode).
    client_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=backend,
    )
    client_name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "uat-api-client"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ServiceNow UAT Engine"),
    ])
    client_cert = (
        x509.CertificateBuilder()
        .subject_name(client_name)
        .issuer_name(ca_name)
        .public_key(client_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(expiry)
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([
                ExtendedKeyUsageOID.CLIENT_AUTH,
            ]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256(), backend)
    )

    client_key_path.write_bytes(
        client_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    client_crt_path.write_bytes(client_cert.public_bytes(serialization.Encoding.PEM))

    # Set restricted permissions on POSIX
    for path in (ca_key_path, redis_key_path, client_key_path):
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    print("[+] Successfully generated:")
    print(f"    - CA Cert:      {ca_crt_path}")
    print(f"    - CA Key:       {ca_key_path}")
    print(f"    - Redis Cert:   {redis_crt_path}")
    print(f"    - Redis Key:    {redis_key_path}")
    print(f"    - Client Cert:  {client_crt_path}")
    print(f"    - Client Key:   {client_key_path}")
    print()
    print("[i] To enable true mTLS in docker-compose.yml, change:")
    print("    --tls-auth-clients no  →  --tls-auth-clients yes")
    print("    and mount client.crt + client.key into the api/worker containers.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate Redis TLS certificates")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("tls/redis"),
        help="Target output directory (default: tls/redis)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=365,
        help="Certificate validity in days (default: 365)",
    )
    args = parser.parse_args()
    generate_certs(args.output_dir, valid_days=args.days)
