"""
Helper script for generating color palette temperature scale.
Creating color palette:
* Define hex_colors same as in src/postprocessing/material.blend
* Generate palette to svg:
    python generate_svg_palette
Adding color palette scale to frame:
* Convert generated svg to png (set height_px <= frame height):
    rsvg-convert -a -h 1000 -o scale.png scale.svg
* Combine generated scale with frame (choose side: east, west, northeast, southwest etc):
    composite -gravity east scale.png frame.png output.png
"""

import json
import sys
from pathlib import Path

from matplotlib import pyplot as plt
import matplotlib
import numpy as np

# Labels must match the colour range used for the glTF frames:
#   python generate_svg_palette.py [TMIN TMAX]   (deg C)
# without arguments the range written by `tpost generate-gltf` (gltf/range.json) is used
if len(sys.argv) == 3:
    tmin, tmax = float(sys.argv[1]), float(sys.argv[2])
elif Path("gltf/range.json").exists():
    r = json.loads(Path("gltf/range.json").read_text())
    tmin, tmax = r["tmin_C"], r["tmax_C"]
else:
    sys.exit("Give TMIN TMAX in C, or run from the folder where `tpost generate-gltf` wrote gltf/range.json")
print(f"Scale bar {tmin:.1f}..{tmax:.1f} C")

# Color palette hex color codes
hex_colors = [
    "#fcffa4",
    "#fac127",
    "#f57d15",
    "#d44842",
    "#9f2a63",
    "#65156e",
    "#280b54",
]

dpi = 100
height_px = 1000
width_px = 0.02 * height_px

figsize = (width_px / dpi, height_px / dpi)
plt.figure(figsize=figsize)
a = np.outer(np.arange(0, 1, 0.01), np.ones(10))

# Add temperature scale to y axis legend
plt.ylabel("Temperature [°C]", fontsize=12)
x = [f"{t:.0f}" for t in np.linspace(tmax, tmin, 11)]
num_rows = a.shape[0]
tick_positions = np.linspace(0, num_rows - 1, len(x))

# Remove x axis
plt.yticks(tick_positions, x, fontsize=12)
plt.tick_params(axis="x", which="both", bottom=False, labelbottom=False)

# Create a custom colormap from hex values
my_cmap = matplotlib.colors.LinearSegmentedColormap.from_list(
    "my_colormap", hex_colors, N=256
)
# Save to svg
plt.imshow(a, aspect="auto", cmap=my_cmap)
plt.savefig("colormap_scale.svg", bbox_inches="tight", transparent=True)
