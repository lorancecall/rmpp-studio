#!/bin/sh
# Cross-build the tablet parts:
#   build/librmpp-remote.so  xochitl add-on (LD_PRELOAD via rmpp-preload)
#   build/rmpp-remote        input injection + add-on client
# SDK defaults to ../sdk (Arm GNU aarch64 toolchain + Qt 6.10 headers + the tablet's Qt libraries in devlibs/).
set -e
cd "$(dirname "$0")"
SDK=${SDK:-../sdk}
CXX=${CXX:-$SDK/bin/aarch64-none-linux-gnu-g++}
CC=${CC:-$SDK/bin/aarch64-none-linux-gnu-gcc}
STRIP=${STRIP:-$SDK/bin/aarch64-none-linux-gnu-strip}
Q=$SDK/qt/usr/include/qt6
mkdir -p build
"$CXX" -std=c++17 -O2 -fPIC -shared -DQT_NO_VERSION_TAGGING -DQT_NO_DEBUG \
  -I"$Q" -I"$Q/QtCore" -I"$Q/QtGui" -I"$Q/QtQuick" \
  addon/remote.cpp -o build/librmpp-remote.so -L"$SDK/devlibs" \
  -l:libQt6Core.so.6 -l:libQt6Gui.so.6 -l:libQt6Quick.so.6 \
  -ldl -Wl,--allow-shlib-undefined -Wl,-soname,librmpp-remote.so
"$CC" -std=gnu11 -O2 -Wall tablet/rmpp-remote.c -o build/rmpp-remote -lm
# no local paths or debug info in the binaries
"$STRIP" --strip-unneeded build/librmpp-remote.so
"$STRIP" build/rmpp-remote
ls -la build
