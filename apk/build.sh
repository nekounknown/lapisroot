#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
SDK="${ANDROID_SDK_ROOT:-/opt/android-sdk}"
BT="${ANDROID_BUILD_TOOLS:-/usr/bin}"
PLATFORM="$SDK/platforms/android-34/android.jar"
OUT="$ROOT/build"
# Shizuku API/provider jars. Point APK_LIBS_DIR at a directory containing
# api/classes.jar, provider/classes.jar, aidl-classes.jar,
# shared-classes.jar and annotation-jvm.jar (e.g. extracted from the
# Shizuku AARs published on Maven Central / the Shizuku GitHub release).
APK_LIBS_DIR="${APK_LIBS_DIR:-$ROOT/.libs}"
LIBS="$APK_LIBS_DIR/api/classes.jar:$APK_LIBS_DIR/provider/classes.jar:$APK_LIBS_DIR/aidl-classes.jar:$APK_LIBS_DIR/shared-classes.jar:$APK_LIBS_DIR/annotation-jvm.jar"
SHIZUKU_API="$APK_LIBS_DIR/api/classes.jar"
SHIZUKU_PROVIDER="$APK_LIBS_DIR/provider/classes.jar"
SHIZUKU_AIDL="$APK_LIBS_DIR/aidl-classes.jar"
SHIZUKU_SHARED="$APK_LIBS_DIR/shared-classes.jar"
ANNOTATION="$APK_LIBS_DIR/annotation-jvm.jar"
for jar in "$SHIZUKU_API" "$SHIZUKU_PROVIDER" "$SHIZUKU_AIDL" "$SHIZUKU_SHARED" "$ANNOTATION"; do
    if [ ! -f "$jar" ]; then
        echo "missing Shizuku jar: $jar (set APK_LIBS_DIR)" >&2; exit 1
    fi
done
if [ ! -d "$ROOT/jniLibs/arm64-v8a" ] || ! ls "$ROOT/jniLibs/arm64-v8a/"*.so >/dev/null 2>&1; then
    echo "missing native payloads in $ROOT/jniLibs/arm64-v8a/ (not tracked in git)" >&2; exit 1
fi

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
cp "$ROOT/jniLibs/arm64-v8a/"*.so lib/arm64-v8a/
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
