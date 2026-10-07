#!/bin/sh
set -eu
export LC_ALL=C
export CFLAGS='-std=gnu89 -fcommon'
cd /lab/source/src
# Only the six libraries and XML CLI are needed; never run historical binaries.
make -j1 -C greeklib greeklib.a
make -j1 -C morphlib morphlib.a
make -j1 -C gkends gkends.a
make -j1 -C gkdict gkdict.a
make -j1 -C gener gener.a
make -j1 -C anal morpheus
mkdir -p /lab/artifacts/rootfs/opt/morpheus/bin
cp anal/morpheus /lab/artifacts/rootfs/opt/morpheus/bin/morpheus
cp -R /lab/source/dist/stemlib /lab/artifacts/rootfs/opt/morpheus/stemlib
cp -R /lab/notices /lab/artifacts/rootfs/opt/morpheus/notices
gcc --version > /lab/artifacts/compiler.txt
dpkg-query -W > /lab/artifacts/packages.tsv
ldd anal/morpheus > /lab/artifacts/ldd.txt
# Retain exact dynamically linked dependencies, not an assumption about base libc.
ldd anal/morpheus | awk '{ for(i=1;i<=NF;i++) if ($i ~ /^\//) print $i }' > /lab/artifacts/dependencies.txt
while IFS= read -r lib; do
    test -f "$lib"
    cp --parents -L "$lib" /lab/artifacts/rootfs
done < /lab/artifacts/dependencies.txt
find /lab/artifacts/rootfs -type d -exec chmod 755 {} +
find /lab/artifacts/rootfs -type f -exec chmod 644 {} +
chmod 755 /lab/artifacts/rootfs/opt/morpheus/bin/morpheus
# Loader must remain executable when the image's base loader is replaced.
find /lab/artifacts/rootfs -type f -name 'ld-linux*' -exec chmod 755 {} +
