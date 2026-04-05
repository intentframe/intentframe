#!/bin/bash
set -euo pipefail

# Creates a self-signed code signing certificate for development.
# Run once — the certificate persists in your login keychain and
# bundle.sh will use it automatically on every rebuild.
#
# This prevents macOS from re-prompting for Calendar, Reminders,
# Contacts, Notifications, etc. after each rebuild.

CERT_NAME="IntentFrame Dev"

# Check if certificate already exists
if security find-identity -v -p codesigning 2>/dev/null | grep -q "$CERT_NAME"; then
    echo "Certificate '$CERT_NAME' already exists. No action needed."
    exit 0
fi

echo "Creating self-signed code signing certificate: '$CERT_NAME'"
echo ""
echo "A dialog will open asking you to set trust for the certificate."
echo "Set Code Signing to 'Always Trust' when prompted."
echo ""

# Create the certificate using the Keychain Certificate Assistant CLI.
# This is the most reliable way on macOS — it creates a properly
# formatted certificate that codesign recognizes.

cat > /tmp/intentframe-cert.cfg <<EOF
[ req ]
default_bits       = 2048
distinguished_name = dn
x509_extensions    = codesign
prompt             = no

[ dn ]
CN = $CERT_NAME

[ codesign ]
keyUsage = critical, digitalSignature
extendedKeyUsage = critical, codeSigning
EOF

# Generate cert + key
openssl req -x509 \
    -config /tmp/intentframe-cert.cfg \
    -newkey rsa:2048 \
    -keyout /tmp/intentframe-key.pem \
    -out /tmp/intentframe-cert.pem \
    -days 3650 \
    -nodes \
    2>/dev/null

# Create PKCS12 bundle
openssl pkcs12 -export \
    -out /tmp/intentframe-cert.p12 \
    -inkey /tmp/intentframe-key.pem \
    -in /tmp/intentframe-cert.pem \
    -passout pass:intentframe \
    -name "$CERT_NAME" \
    2>/dev/null

# Import into login keychain with codesign access
security import /tmp/intentframe-cert.p12 \
    -k "$HOME/Library/Keychains/login.keychain-db" \
    -P "intentframe" \
    -T /usr/bin/codesign \
    -f pkcs12

# Allow codesign to use it without prompting
security set-key-partition-list \
    -S "apple-tool:,apple:" \
    -s -k "" \
    "$HOME/Library/Keychains/login.keychain-db" \
    2>/dev/null || true

rm -f /tmp/intentframe-cert.cfg /tmp/intentframe-key.pem /tmp/intentframe-cert.pem /tmp/intentframe-cert.p12

echo ""

# Verify it worked
if security find-identity -v -p codesigning 2>/dev/null | grep -q "$CERT_NAME"; then
    echo "✅ Certificate '$CERT_NAME' is ready for code signing."
    echo ""
    echo "If codesign still fails, open Keychain Access, find '$CERT_NAME',"
    echo "double-click → Trust → Code Signing → 'Always Trust'."
else
    echo "⚠️  Certificate was imported but not yet trusted for code signing."
    echo ""
    echo "Open Keychain Access and:"
    echo "  1. Click 'My Certificates' tab (top)"
    echo "  2. Find '$CERT_NAME'"
    echo "  3. Double-click → Trust → Code Signing → 'Always Trust'"
fi
