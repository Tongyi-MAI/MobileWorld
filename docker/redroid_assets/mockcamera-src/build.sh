#!/bin/bash
set -e
export ANDROID_HOME=/opt/android-sdk
BT=$ANDROID_HOME/build-tools/34.0.0
PLATFORM=$ANDROID_HOME/platforms/android-34/android.jar
ROOT=/root/mockcamera
cd $ROOT
rm -rf build/gen build/obj build/apk
mkdir -p build/gen build/obj build/apk build/compiled

echo "=== aapt2 compile resources ==="
$BT/aapt2 compile --dir res -o build/compiled/res.zip

echo "=== aapt2 link ==="
$BT/aapt2 link \
  -o build/apk/base-unsigned.apk \
  -I $PLATFORM \
  --manifest AndroidManifest.xml \
  -R build/compiled/res.zip \
  --java build/gen \
  --auto-add-overlay \
  --min-sdk-version 24 \
  --target-sdk-version 34

echo "=== javac ==="
find src build/gen -name "*.java" > build/sources.txt
javac -source 8 -target 8 \
  -classpath $PLATFORM \
  -d build/obj \
  @build/sources.txt 2>build/javac.err || { cat build/javac.err; exit 1; }
grep -v "bootstrap class path" build/javac.err | grep -vi "warning" || true

echo "=== d8 (dex) ==="
CLASSES=$(find build/obj -name "*.class")
$BT/d8 --min-api 24 --lib $PLATFORM --output build/apk $CLASSES

echo "=== add classes.dex into apk ==="
cd build/apk
cp base-unsigned.apk app-unaligned.apk
# add classes.dex into the apk (stored in root)
zip -j app-unaligned.apk classes.dex >/dev/null
cd $ROOT

echo "=== zipalign ==="
$BT/zipalign -f -p 4 build/apk/app-unaligned.apk build/apk/app-aligned.apk

echo "=== debug keystore ==="
KS=$ROOT/build/debug.keystore
if [ ! -f $KS ]; then
  keytool -genkeypair -keystore $KS -alias androiddebugkey \
    -storepass android -keypass android -keyalg RSA -keysize 2048 -validity 10000 \
    -dname "CN=Android Debug,O=Android,C=US" >/dev/null 2>&1
fi

echo "=== apksigner ==="
$BT/apksigner sign \
  --ks $KS --ks-pass pass:android --key-pass pass:android \
  --ks-key-alias androiddebugkey \
  --out build/apk/MockCamera-debug.apk \
  build/apk/app-aligned.apk

$BT/apksigner verify --verbose build/apk/MockCamera-debug.apk | head -8
echo "=== BUILD OK ==="
ls -la build/apk/MockCamera-debug.apk
