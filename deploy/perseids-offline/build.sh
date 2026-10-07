#!/bin/sh
set -eu
export LC_ALL=C
export CFLAGS='-std=gnu89 -fcommon'
cd /lab/source/src
# Only the six libraries and tagged-output CLI are needed; never run historical binaries.
make -j1 -C greeklib greeklib.a
make -j1 -C morphlib morphlib.a
make -j1 -C gkends gkends.a
make -j1 -C gkdict gkdict.a
make -j1 -C gener gener.a
make -j1 -C anal cruncher
mkdir -p /lab/artifacts/rootfs/opt/perseids/bin
cp anal/cruncher /lab/artifacts/rootfs/opt/perseids/bin/cruncher
cp -R /lab/source/stemlib /lab/artifacts/rootfs/opt/perseids/stemlib
cp -R /lab/notices /lab/artifacts/rootfs/opt/perseids/notices
gcc --version > /lab/artifacts/compiler.txt
dpkg-query -W > /lab/artifacts/packages.tsv
ldd anal/cruncher > /lab/artifacts/ldd.txt
# Retain exact dynamically linked dependencies, not an assumption about base libc.
ldd anal/cruncher | awk '{ for(i=1;i<=NF;i++) if ($i ~ /^\//) print $i }' > /lab/artifacts/dependencies.txt
while IFS= read -r lib; do
    test -f "$lib"
    cp --parents -L "$lib" /lab/artifacts/rootfs
done < /lab/artifacts/dependencies.txt
find /lab/artifacts/rootfs -type d -exec chmod 755 {} +
find /lab/artifacts/rootfs -type f -exec chmod 644 {} +
chmod 755 /lab/artifacts/rootfs/opt/perseids/bin/cruncher
# Loader must remain executable when the image's base loader is replaced.
find /lab/artifacts/rootfs -type f -name 'ld-linux*' -exec chmod 755 {} +
