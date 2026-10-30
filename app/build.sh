#!/usr/bin/env bash
# Builds Dynamic Island into a signed APK without Gradle.
# Requires: JDK 17+, Android SDK build-tools 34 + platform android-34.
#   ANDROID_HOME=/path/to/sdk ./build.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
ANDROID_DIR="$ROOT/android"
BUILD="$ROOT/build"
DIST="$ROOT/dist"

: "${ANDROID_HOME:?set ANDROID_HOME to your Android SDK path}"
BT="${BUILD_TOOLS:-$ANDROID_HOME/build-tools/34.0.0}"
PLATFORM="$ANDROID_HOME/platforms/android-34/android.jar"
[ -f "$PLATFORM" ] || { echo "missing $PLATFORM"; exit 1; }

VERSION_CODE=1
VERSION_NAME=1.0.0

rm -rf "$BUILD"
mkdir -p "$BUILD/compiled" "$BUILD/gen" "$BUILD/classes" "$BUILD/dex" "$DIST"

echo "==> 0/6 stage the web app"
mkdir -p "$ANDROID_DIR/assets"
cp "$ROOT/index.html" "$ANDROID_DIR/assets/index.html"

echo "==> 1/6 compile resources"
"$BT/aapt2" compile --dir "$ANDROID_DIR/res" -o "$BUILD/compiled/res.zip"

echo "==> 2/6 link resources + assets"
"$BT/aapt2" link \
  -o "$BUILD/base.apk" \
  -I "$PLATFORM" \
  --manifest "$ANDROID_DIR/AndroidManifest.xml" \
  -A "$ANDROID_DIR/assets" \
  --java "$BUILD/gen" \
  --min-sdk-version 24 --target-sdk-version 34 \
  --version-code "$VERSION_CODE" --version-name "$VERSION_NAME" \
  --auto-add-overlay \
  "$BUILD/compiled/res.zip"

echo "==> 3/6 compile java"
javac -source 8 -target 8 -nowarn -bootclasspath "$PLATFORM" \
  -d "$BUILD/classes" \
  $(find "$ANDROID_DIR/src" "$BUILD/gen" -name '*.java')

echo "==> 4/6 dex"
"$BT/d8" --lib "$PLATFORM" --min-api 24 --release \
  --output "$BUILD/dex" \
  $(find "$BUILD/classes" -name '*.class')

echo "==> 5/6 package + align"
cp "$BUILD/base.apk" "$BUILD/unaligned.apk"
( cd "$BUILD/dex" && zip -q -j "$BUILD/unaligned.apk" classes.dex )
"$BT/zipalign" -f -p 4 "$BUILD/unaligned.apk" "$BUILD/aligned.apk"

echo "==> 6/6 sign"
KS="$ROOT/keystore/dynamic-island.jks"
# The key is published as base64 so that the released APK can be updated in
# place. Without it every build would generate a fresh key and Android would
# refuse to install the new APK over the old one.
B64=""
for cand in "$ROOT/keystore/dynamic-island.jks.base64" "$ROOT/../keystore/dynamic-island.jks.base64"; do
  if [ -f "$cand" ]; then B64="$cand"; break; fi
done
if [ ! -f "$KS" ] && [ -n "$B64" ]; then
  echo "    restoring the signing key from ${B64#$ROOT/}"
  mkdir -p "$(dirname "$KS")"
  base64 -d "$B64" > "$KS"
fi
if [ ! -f "$KS" ]; then
  echo "    creating a signing key at $KS"
  mkdir -p "$ROOT/keystore"
  keytool -genkeypair -v \
    -keystore "$KS" -alias dynamicisland \
    -keyalg RSA -keysize 2048 -validity 10950 \
    -storepass dynamicisland -keypass dynamicisland \
    -dname "CN=Dynamic Island, OU=Apps, O=Hub Clue, L=Bengaluru, C=IN" >/dev/null 2>&1
fi

APK="$DIST/DynamicIsland-${VERSION_NAME}.apk"
"$BT/apksigner" sign \
  --ks "$KS" --ks-key-alias dynamicisland \
  --ks-pass pass:dynamicisland --key-pass pass:dynamicisland \
  --v1-signing-enabled true --v2-signing-enabled true --v3-signing-enabled true \
  --out "$APK" "$BUILD/aligned.apk"

"$BT/apksigner" verify --print-certs "$APK" | head -5
ls -lh "$APK"
echo "done: $APK"
