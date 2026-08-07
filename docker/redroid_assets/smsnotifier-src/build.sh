#!/bin/bash
# Build smsnotifier.apk locally (needs the Android SDK build-tools + a JDK).
# Output: ../smsnotifier.apk (shipped + installed on the device by setup_notifier.sh).
set -e
SDK="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
BT="$SDK/build-tools/35.0.0"
PLATFORM="$SDK/platforms/android-35/android.jar"
export JAVA_HOME="${JAVA_HOME:-/Applications/Android Studio.app/Contents/jbr/Contents/Home}"
export PATH="$JAVA_HOME/bin:$PATH"
ROOT="$(cd "$(dirname "$0")" && pwd)"
OUT="$ROOT/../smsnotifier.apk"
cd "$ROOT"
rm -rf build && mkdir -p build/gen build/obj build/apk

echo "=== aapt2 link (manifest only, no resources) ==="
"$BT/aapt2" link -o build/apk/base-unsigned.apk -I "$PLATFORM" \
  --manifest AndroidManifest.xml --java build/gen \
  --min-sdk-version 24 --target-sdk-version 34

echo "=== javac ==="
find src build/gen -name "*.java" > build/sources.txt
"$JAVA_HOME/bin/javac" -source 8 -target 8 -classpath "$PLATFORM" -d build/obj @build/sources.txt

echo "=== d8 (dex) ==="
CLASSES=$(find build/obj -name "*.class")
"$BT/d8" --min-api 24 --lib "$PLATFORM" --output build/apk $CLASSES

echo "=== package dex + zipalign + sign ==="
cd build/apk
cp base-unsigned.apk app-unaligned.apk
zip -j app-unaligned.apk classes.dex >/dev/null
cd "$ROOT"
"$BT/zipalign" -f -p 4 build/apk/app-unaligned.apk build/apk/app-aligned.apk
KS="$HOME/.android/debug.keystore"
if [ ! -f "$KS" ]; then
  keytool -genkeypair -keystore "$KS" -storepass android -keypass android \
    -alias androiddebugkey -keyalg RSA -keysize 2048 -validity 10000 \
    -dname "CN=Android Debug,O=Android,C=US"
fi
"$BT/apksigner" sign --ks "$KS" --ks-pass pass:android --key-pass pass:android \
  --out "$OUT" build/apk/app-aligned.apk
echo "=== built $OUT ==="
ls -la "$OUT"
