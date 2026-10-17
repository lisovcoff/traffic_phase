"""Visual aid only: native image versus unregistered raw normalized coordinates."""
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
tracks = json.loads((ROOT/'.web_runtime'/OUT.name/'first_entry.json').read_text(encoding='utf-8'))
origin = min(d['millis'] for t in tracks for d in t['detections'])
fig, axes = plt.subplots(1, 2, figsize=(16, 7))
img = Image.open(ROOT/'.web_runtime/enthusiasts_video_20261017/full_frames/start.png')
axes[0].imshow(img)
axes[0].set_title('Video PTS 0: native context (display scaled)')
axes[0].axis('off')
ax = axes[1]
for t in tracks:
    ds = t['detections']
    ax.plot([d['centroid_x'] for d in ds], [d['centroid_y'] for d in ds], alpha=.13, linewidth=.6, color='gray')
    d = ds[0]
    if d['millis'] <= origin + 200:
        ax.add_patch(Rectangle((d['x1'], d['y1']), d['x2']-d['x1'], d['y2']-d['y1'], fill=False, linewidth=1))
        ax.text(d['x1'], d['y1'], str(t['id']), fontsize=8)
ax.set(xlim=(0,1), ylim=(1,0), xlabel='Raw normalized x (registration UNKNOWN)', ylabel='Raw normalized y',
       title='JSON first 200 ms boxes + complete first-entry paths')
ax.set_aspect(1520/2688)
fig.suptitle('No clock alignment; no transformation fitted; simultaneous source-start hypothesis only')
fig.tight_layout()
fig.savefig(OUT/'geometry_preview.png', dpi=140)
plt.close(fig)
