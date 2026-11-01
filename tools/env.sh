# shellcheck shell=bash
# Source this before building:   . tools/env.sh
# Fetches a JDK and the Android SDK into .toolchain/ on first use, then exports
# JAVA_HOME / ANDROID_HOME / PATH so app/build.sh can find them. Everything it
# downloads is disposable - delete .toolchain/ to start over.

TOOLCHAIN="${TOOLCHAIN:-/scratch/work/.toolchain}"
JDK_URL="https://api.adoptium.net/v3/binary/latest/17/ga/linux/x64/jdk/hotspot/normal/eclipse"
CMDLINE_URL="https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip"

# the sandbox caps virtual memory, which kills both the JVM and chromium
ulimit -v unlimited 2>/dev/null || true

if [ ! -x "$TOOLCHAIN/jdk/bin/java" ]; then
  echo "==> fetching JDK 17"
  mkdir -p "$TOOLCHAIN/jdk"
  curl -sSL -o "$TOOLCHAIN/jdk.tgz" "$JDK_URL" &&
    tar -xzf "$TOOLCHAIN/jdk.tgz" -C "$TOOLCHAIN/jdk" --strip-components=1 &&
    rm -f "$TOOLCHAIN/jdk.tgz"
fi
export JAVA_HOME="$TOOLCHAIN/jdk"

export ANDROID_HOME="${ANDROID_HOME:-$TOOLCHAIN/sdk}"
if [ ! -f "$ANDROID_HOME/platforms/android-34/android.jar" ]; then
  echo "==> fetching Android SDK 34"
  mkdir -p "$ANDROID_HOME/cmdline-tools"
  curl -sSL -o "$TOOLCHAIN/cmdline.zip" "$CMDLINE_URL" &&
    unzip -q -o "$TOOLCHAIN/cmdline.zip" -d "$ANDROID_HOME/cmdline-tools" &&
    mv -f "$ANDROID_HOME/cmdline-tools/cmdline-tools" "$ANDROID_HOME/cmdline-tools/latest" 2>/dev/null
  yes | "$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" --sdk_root="$ANDROID_HOME" --licenses >/dev/null 2>&1
  "$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" --sdk_root="$ANDROID_HOME" \
      "platforms;android-34" "build-tools;34.0.0" >/dev/null
  rm -f "$TOOLCHAIN/cmdline.zip"
fi

export PATH="$JAVA_HOME/bin:$PATH"
export _JAVA_OPTIONS="-Xmx700m"
echo "==> toolchain ready (JDK: $JAVA_HOME, SDK: $ANDROID_HOME)"
