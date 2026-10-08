#!/bin/bash
# No-sudo install of the full validation toolchain inside WSL/Linux.
#
#   bash validation/install_user.sh            # core tools (~10 min, ~2 GB)
#   WITH_ELMER=1 bash validation/install_user.sh   # + Elmer for benchmark B6 (~15 min more)
#
# Then, in every new terminal:  source ~/tss-env.sh
#
# Installs under ~/tss-tools: micromamba (ccx, jq), FreeCAD 1.0.0 (extracted
# AppImage, bundles its own ccx/gmsh), ParaView 6.0.0, optional Elmer; and a
# Python 3.11 venv (via uv) in the repo clone with the project installed.
set -u
TOOLS="$HOME/tss-tools"
LOGS="$TOOLS/logs"
REPO="${REPO:-$HOME/thermal-simulation-scripts}"
WIN_REPO="${WIN_REPO:-/mnt/c/Users/$USER/Documents/GitHub/thermal-simulation-scripts}"
mkdir -p "$TOOLS" "$LOGS" "$HOME/.local/bin"
export PATH="$HOME/.local/bin:$PATH"
export MAMBA_ROOT_PREFIX="$TOOLS/mamba"

status() { echo "$(date +%T) $1: $2" | tee -a "$LOGS/status.txt"; }

job_python() {
  set -e
  command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
  # clone inside Linux: a Windows checkout has CRLF line endings
  [ -d "$REPO" ] || git clone "$WIN_REPO" "$REPO"
  cd "$REPO"
  uv python install 3.11
  [ -d .venv ] || uv venv --python 3.11 .venv
  uv pip install --python .venv/bin/python -e . pytest scipy gmsh
}

job_mamba() {
  set -e
  cd "$TOOLS"
  [ -x bin/micromamba ] || curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest | tar -xj bin/micromamba
  [ -d env ] || bin/micromamba create -y -p "$TOOLS/env" -c conda-forge calculix jq
}

job_freecad() {
  set -e
  cd "$TOOLS"
  [ -d freecad ] && return 0
  wget -q -O freecad.AppImage "https://github.com/FreeCAD/FreeCAD/releases/download/1.0.0/FreeCAD_1.0.0-conda-Linux-x86_64-py311.AppImage"
  chmod +x freecad.AppImage
  ./freecad.AppImage --appimage-extract >/dev/null
  mv squashfs-root freecad
  rm freecad.AppImage
}

job_paraview() {
  set -e
  cd "$TOOLS"
  [ -x paraview/bin/pvpython ] && return 0
  wget -q -O paraview.tar.gz "https://www.paraview.org/paraview-downloads/download.php?submit=Download&version=v6.0&type=binary&os=Linux&downloadFile=ParaView-6.0.0-MPI-Linux-Python3.12-x86_64.tar.gz"
  mkdir -p paraview
  tar -xzf paraview.tar.gz --strip-components=1 -C paraview
  rm paraview.tar.gz
}

job_elmer() {
  set -e
  MM="$TOOLS/bin/micromamba"
  while [ ! -x "$MM" ]; do sleep 5; done
  [ -d "$TOOLS/elmer-build-env" ] || "$MM" create -y -p "$TOOLS/elmer-build-env" -c conda-forge \
    cmake make compilers openblas liblapack libblas
  [ -d "$TOOLS/elmerfem-src" ] || git clone --depth 1 https://github.com/ElmerCSC/elmerfem.git "$TOOLS/elmerfem-src"
  "$MM" run -p "$TOOLS/elmer-build-env" bash -c "
    set -e
    cmake -S $TOOLS/elmerfem-src -B $TOOLS/elmerfem-src/build \
      -DCMAKE_INSTALL_PREFIX=$TOOLS/elmer -DWITH_MPI=OFF -DWITH_OpenMP=ON \
      -DWITH_ELMERGUI=OFF -DWITH_ElmerIce=OFF -DWITH_LUA=OFF \
      -DCMAKE_PREFIX_PATH=$TOOLS/elmer-build-env
    cmake --build $TOOLS/elmerfem-src/build -j\$(nproc)
    cmake --install $TOOLS/elmerfem-src/build
  "
  # wrappers so Elmer's OpenBLAS never leaks into FreeCAD/VTK processes
  mkdir -p "$TOOLS/elmer-wrap"
  for b in ElmerSolver ElmerGrid ViewFactors; do
    cat > "$TOOLS/elmer-wrap/$b" <<EOF
#!/bin/bash
export LD_LIBRARY_PATH="$TOOLS/elmer-build-env/lib:$TOOLS/elmer/lib/elmersolver\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}"
export ELMER_HOME="$TOOLS/elmer"
exec "$TOOLS/elmer/bin/$b" "\$@"
EOF
    chmod +x "$TOOLS/elmer-wrap/$b"
  done
}

jobs_to_run="python mamba freecad paraview"
[ "${WITH_ELMER:-0}" = 1 ] && jobs_to_run="$jobs_to_run elmer"
for j in $jobs_to_run; do
  ( status "$j" started
    if "job_$j" >"$LOGS/$j.log" 2>&1; then status "$j" OK; else status "$j" "FAILED (see $LOGS/$j.log)"; fi ) &
done
wait

cat > "$HOME/tss-env.sh" <<EOF
# Thermal-simulation toolchain. Use:  source ~/tss-env.sh
export FREECAD_PATH="$TOOLS/freecad"
export PATH="$TOOLS/elmer-wrap:$TOOLS/paraview/bin:$TOOLS/env/bin:$HOME/.local/bin:\$PATH"
export LANG=C.UTF-8 LC_ALL=C.UTF-8
source "$REPO/.venv/bin/activate"
export OMP_NUM_THREADS=\$(nproc)
EOF
status all "done - run: source ~/tss-env.sh"
