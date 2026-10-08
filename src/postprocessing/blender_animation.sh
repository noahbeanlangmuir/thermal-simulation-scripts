#!/bin/bash
# Render every glTF frame with PCBooth and assemble the animation.
#   blender_animation.sh <gltf_dir>     (run in the designs directory)
# Output of every tool goes to blender.log; the script stops at the first failure.
set -euo pipefail
GLTF_DIR=$1
height=$(yq '.thermal.RENDERER.IMAGE_HEIGHT' blendcfg.yaml )
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
WD=$PWD
LOG="$WD/blender.log"
: > "$LOG"
fail() { echo "ERROR: $1 (see $LOG)" >&2; tail -n 20 "$LOG" >&2; exit 1; }
echo "Converting colormap..."
rsvg-convert -a -h "$height" -o "$SCRIPT_DIR"/colormap_scale.png "$SCRIPT_DIR"/colormap_scale.svg >> "$LOG" 2>&1 || fail "rsvg-convert failed"
mkdir -p blends renders
for GLTF in "$GLTF_DIR"/*.gltf; do
    if [[ -f "$GLTF" ]]; then
        name=$(basename "$GLTF" .gltf)
        echo "Converting $name to .blend"
        tpost gltf-to-blend --gltf "$GLTF" --blend "temp.blend" >> "$LOG" 2>&1 || fail "gltf-to-blend failed for $name"
        echo "Preparing $name for pcbooth"
        tpost process-blend --input "temp.blend" --output "temp.blend" --material "$SCRIPT_DIR/material.blend" --config "config.json" >> "$LOG" 2>&1 || fail "process-blend failed for $name"
        echo "Rendering $name frame"
        before=$(find renders -maxdepth 1 -type f | wc -l)
        pcbooth -b "temp.blend" -c thermal >> "$LOG" 2>&1 || fail "pcbooth failed for frame $name"
        after=$(find renders -maxdepth 1 -type f | wc -l)
        # pcbooth names its output itself; the newest file is only ours if one was added
        [ "$after" -gt "$before" ] || fail "pcbooth wrote no image for frame $name"
        mv temp.blend blends/$name.blend
        latest_file=$(find renders -maxdepth 1 -type f -printf "%T@ %p\n" | sort -n | tail -n 1 | cut -d' ' -f2-)
        mv "$latest_file" "renders/$name.png"
        echo "Merging $name scale with frame"
        composite -gravity east "$SCRIPT_DIR"/colormap_scale.png renders/"$name".png renders/"$name".png >> "$LOG" 2>&1 || fail "composite failed for $name"
    fi
done
echo "Processing frames..."
trap 'cd "$WD"' EXIT
cd renders
ffmpeg -y -framerate 25 -i %04d.png -c:v libvpx-vp9 -pix_fmt yuva420p10le -lossless 1 -vf scale=iw:-2 animation.webm >> "$LOG" 2>&1 || fail "ffmpeg webm failed"
ffmpeg -y -framerate 25 -i %04d.png -vf palettegen palette.png >> "$LOG" 2>&1 || fail "ffmpeg palette failed"
ffmpeg -y -framerate 25 -i %04d.png -i palette.png -lavfi "paletteuse" animation.gif >> "$LOG" 2>&1 || fail "ffmpeg gif failed"
echo "Processing completed"
