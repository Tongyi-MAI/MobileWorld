#!/bin/bash
# Build patched Clipper APK targeting SDK 34.
#
# The original Clipper (https://github.com/majido/clipper) targets SDK 0/10,
# which is rejected by API 34 with INSTALL_FAILED_DEPRECATED_SDK_VERSION.
# This script applies MobileWorld patches and rebuilds the APK.
#
# Prerequisites: ANDROID_HOME or ANDROID_SDK_ROOT set, javac available.
# Output: docker/apks/clipper.apk
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SRC_DIR="$REPO_ROOT/resources/clipper/src/main/java/ca/zgrs/clipper"
PATCHES_DIR="$SCRIPT_DIR/patches"
BUILD_DIR="/tmp/clipper-build-$$"
OUTPUT_DIR="$SCRIPT_DIR/apks"
OUTPUT="$OUTPUT_DIR/clipper.apk"

SDK="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-}}"
if [ -z "$SDK" ]; then
    echo "ERROR: ANDROID_HOME or ANDROID_SDK_ROOT must be set" >&2
    exit 1
fi

# Find build-tools (prefer 34.x)
BT_VERSION=$(ls "$SDK/build-tools/" | grep '^34\.' | sort -V | tail -1)
if [ -z "$BT_VERSION" ]; then
    BT_VERSION=$(ls "$SDK/build-tools/" | sort -V | tail -1)
fi
BT="$SDK/build-tools/$BT_VERSION"
PLATFORM="$SDK/platforms/android-34/android.jar"

if [ ! -f "$PLATFORM" ]; then
    echo "ERROR: Android platform android-34 not found at $PLATFORM" >&2
    echo "Install with: sdkmanager 'platforms;android-34'" >&2
    exit 1
fi

echo "Using build-tools: $BT_VERSION"
echo "Using platform: $PLATFORM"

# Clean
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/classes" "$BUILD_DIR/src/ca/zgrs/clipper" "$OUTPUT_DIR"

# Apply patches over original source
cp "$PATCHES_DIR/clipper_Main.java" "$BUILD_DIR/src/ca/zgrs/clipper/Main.java"
cp "$PATCHES_DIR/clipper_ClipperReceiver.java" "$BUILD_DIR/src/ca/zgrs/clipper/ClipperReceiver.java"
cp "$PATCHES_DIR/clipper_AndroidManifest.xml" "$BUILD_DIR/AndroidManifest.xml"

# 1. Compile Java
echo "Compiling..."
javac -source 1.8 -target 1.8 \
    -classpath "$PLATFORM" \
    -d "$BUILD_DIR/classes" \
    "$BUILD_DIR/src/ca/zgrs/clipper/"*.java 2>&1 | grep -v "^warning:" || true

# 2. Create DEX
echo "Creating DEX..."
"$BT/d8" --output "$BUILD_DIR" \
    $(find "$BUILD_DIR/classes" -name "*.class") 2>&1

# 3. Package APK with manifest
echo "Packaging APK..."
"$BT/aapt" package -f \
    -M "$BUILD_DIR/AndroidManifest.xml" \
    -I "$PLATFORM" \
    -F "$BUILD_DIR/unsigned.apk"

# 4. Add DEX into APK
(cd "$BUILD_DIR" && zip -j unsigned.apk classes.dex) > /dev/null

# 5. Align
"$BT/zipalign" -f 4 "$BUILD_DIR/unsigned.apk" "$BUILD_DIR/aligned.apk"

# 6. Sign with a debug keystore
KEYSTORE="$BUILD_DIR/debug.keystore"
keytool -genkeypair -keystore "$KEYSTORE" -storepass android \
    -alias key -keypass android -keyalg RSA -keysize 2048 -validity 10000 \
    -dname "CN=MobileWorld" 2>/dev/null
"$BT/apksigner" sign --ks "$KEYSTORE" --ks-pass pass:android "$BUILD_DIR/aligned.apk"

# 7. Output
cp "$BUILD_DIR/aligned.apk" "$OUTPUT"
echo "Built: $OUTPUT"

# Verify
"$BT/aapt" dump badging "$OUTPUT" 2>/dev/null | grep -E "targetSdkVersion|package:" || true

# Cleanup
rm -rf "$BUILD_DIR"
