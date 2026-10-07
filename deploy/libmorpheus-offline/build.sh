#!/bin/sh
set -eu
export LC_ALL=C
mkdir -p /lab/artifacts/rootfs/opt/libmorpheus/lib /lab/artifacts/rootfs/opt/libmorpheus/bin
cmake -S /lab/source -B /lab/build -G Ninja \
  -DCMAKE_BUILD_TYPE=Debug -DBUILD_TESTING=ON \
  -DMORPHEUS_BUILD_CRUNCHER=OFF -DMORPHEUS_BUILD_NODE_BINDING=OFF \
  -DMORPHEUS_BUILD_STEMLIB_TOOLS=OFF -DMORPHEUS_BUILD_DENO_GENER_PREPARER=OFF \
  -DMORPHEUS_STEMLIB_DIR=/lab/data/stemlib
# Explicit target closure prevents default ALL preparer/index-builder targets.
cmake --build /lab/build --parallel 1 --target morpheus \
  morpheus_stemlib_abi_test morpheus_stemlib_io_test morpheus_morphflag_bounds_test
# Own-project tests only, before any Campbell or morphology evaluation input.
ctest --test-dir /lab/build -R '^(stemlib_abi|stemlib_io|morphflag_bounds)$' \
  --output-on-failure --timeout 10 > /lab/artifacts/tests.log 2>&1 || {
  cat /lab/artifacts/tests.log
  exit 1
}
cat /lab/artifacts/tests.log
cp -L /lab/build/libmorpheus.so /lab/artifacts/rootfs/opt/libmorpheus/lib/libmorpheus.so.1
gcc -std=c17 -Wall -Wextra -Werror -I/lab/source/include /lab/analysis_probe.c \
  -L/lab/build -lmorpheus -Wl,-rpath,'$ORIGIN/../lib' \
  -o /lab/artifacts/rootfs/opt/libmorpheus/bin/analysis_probe
cp -R /lab/data/stemlib /lab/artifacts/rootfs/opt/libmorpheus/stemlib
cp -R /lab/notices /lab/artifacts/rootfs/opt/libmorpheus/notices
cp /lab/build/CMakeCache.txt /lab/artifacts/CMakeCache.txt
gcc --version > /lab/artifacts/compiler.txt
cmake --version > /lab/artifacts/cmake-version.txt
dpkg-query -W > /lab/artifacts/packages.tsv
ldd /lab/build/libmorpheus.so > /lab/artifacts/ldd.txt
ldd /lab/artifacts/rootfs/opt/libmorpheus/bin/analysis_probe > /lab/artifacts/probe-ldd.txt
ldd /lab/build/libmorpheus.so | awk '{for(i=1;i<=NF;i++) if($i ~ /^\//) print $i}' > /lab/artifacts/dependencies.txt
while IFS= read -r lib; do
  test -f "$lib"
  cp --parents -L "$lib" /lab/artifacts/rootfs
done < /lab/artifacts/dependencies.txt
find /lab/artifacts/rootfs -type d -exec chmod 755 {} +
find /lab/artifacts/rootfs -type f -exec chmod 644 {} +
chmod 755 /lab/artifacts/rootfs/opt/libmorpheus/bin/analysis_probe
find /lab/artifacts/rootfs -type f -name 'ld-linux*' -exec chmod 755 {} +
