#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
SDK="${ANDROID_SDK_ROOT:-/opt/android-sdk}"
BT="${ANDROID_BUILD_TOOLS:-/usr/bin}"
PLATFORM="$SDK/platforms/android-34/android.jar"
OUT="$ROOT/build"
LIBS="/tmp/opencode/apk-libs/api/classes.jar:/tmp/opencode/apk-libs/provider/classes.jar:/tmp/opencode/apk-libs/aidl-classes.jar:/tmp/opencode/apk-libs/shared-classes.jar:/tmp/opencode/apk-libs/annotation-jvm.jar"
SHIZUKU_API="/tmp/opencode/apk-libs/api/classes.jar"
SHIZUKU_PROVIDER="/tmp/opencode/apk-libs/provider/classes.jar"
SHIZUKU_AIDL="/tmp/opencode/apk-libs/aidl-classes.jar"
SHIZUKU_SHARED="/tmp/opencode/apk-libs/shared-classes.jar"
ANNOTATION="/tmp/opencode/apk-libs/annotation-jvm.jar"

rm -rf "$OUT"
mkdir -p "$OUT/classes" "$OUT/dex" "$OUT/lib/arm64-v8a"

"$BT/aapt2" compile --dir "$ROOT/res" -o "$OUT/res.zip"
"$BT/aapt2" link -o "$OUT/base.apk" -I "$PLATFORM" \
    --manifest "$ROOT/AndroidManifest.xml" -R "$OUT/res.zip" \
    --auto-add-overlay

javac -source 17 -target 17 -classpath "$PLATFORM:$LIBS" -d "$OUT/classes" \
    $(find "$ROOT/src" -name '*.java')

"$BT/d8" --lib "$PLATFORM" --output "$OUT/dex" \
    "$SHIZUKU_API" "$SHIZUKU_PROVIDER" "$SHIZUKU_AIDL" "$SHIZUKU_SHARED" "$ANNOTATION" \
    $(find "$OUT/classes" -name '*.class')

cp "$OUT/base.apk" "$OUT/unsigned.apk"
cd "$OUT"
zip -q -j unsigned.apk dex/classes*.dex
cp "$ROOT/jniLibs/arm64-v8a/libexploit.so" lib/arm64-v8a/
zip -q -r unsigned.apk lib

"$BT/zipalign" -f 4 unsigned.apk aligned.apk

KEYSTORE="$ROOT/debug.keystore"
if [ ! -f "$KEYSTORE" ]; then
    keytool -genkeypair -keystore "$KEYSTORE" \
        -storepass android -keypass android -alias androiddebugkey \
        -keyalg RSA -keysize 2048 -validity 10000 \
        -dname "CN=Android Debug,O=Android,C=US" >/dev/null 2>&1
fi

"$BT/apksigner" sign --ks "$KEYSTORE" \
    --ks-pass pass:android --key-pass pass:android \
    --out "$ROOT/lapisroot.apk" aligned.apk

echo "built $ROOT/lapisroot.apk"
"$BT/apksigner" verify --print-certs "$ROOT/lapisroot.apk" | head -5
