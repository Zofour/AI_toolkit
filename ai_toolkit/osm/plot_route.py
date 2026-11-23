# -*- coding: utf-8 -*-
"""昌平路网 + 路线可视化"""
import sys, json
sys.path.insert(0, r'C:\chatbox_temp\ai_toolkit')
import osm_route as R
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

PBF = 'osm_demo/changping.osm.pbf'
coords, adj = R.build_graph(PBF, 'drive')

# 全路网线段（抽样，避免图太重）
segs = []
for u, nbs in adj.items():
    if u not in coords:
        continue
    a = coords[u]
    for v in nbs:
        if v in coords:
            b = coords[v]
            segs.append([(a[1], a[0]), (b[1], b[0])])
segs = segs[::3]

ROUTES = [
    ('昌平城区 -> 回龙观', (40.2206, 116.2353), (40.0748, 116.3392), '#d62728'),
    ('昌平城区 -> 居庸关', (40.2206, 116.2353), (40.2913, 116.0686), '#1f77b4'),
]

fig, ax = plt.subplots(figsize=(11, 9), dpi=130)
ax.add_collection(LineCollection(segs, colors='#bbbbbb', linewidths=0.35))

stats = {}
for label, s_ll, t_ll, color in ROUTES:
    s = R.nearest(coords, *s_ll)
    t = R.nearest(coords, *t_ll)
    path, sec = R.astar(coords, adj, s, t)
    pts = [(coords[n][1], coords[n][0]) for n in path]
    dist = sum(adj[path[i]][path[i + 1]][0] for i in range(len(path) - 1))
    xs, ys = zip(*pts)
    ax.plot(xs, ys, color=color, linewidth=2.2, label=f'{label}  {dist/1000:.1f} km / {sec/60:.0f} min')
    ax.plot(xs[0], ys[0], 'o', color=color, markersize=7)
    ax.plot(xs[-1], ys[-1], 's', color=color, markersize=7)
    stats[label] = {'dist_km': round(dist / 1000, 2), 'time_min': round(sec / 60, 1), 'nodes': len(path)}

# 昌平区行政边界 bbox
ax.set_xlim(115.838, 116.500)
ax.set_ylim(40.035, 40.392)
ax.set_aspect(1 / 0.766)  # cos(40.2°)
ax.set_xlabel('longitude')
ax.set_ylabel('latitude')
ax.set_title('Changping District (Beijing) - OSM offline routing', fontsize=12)
ax.legend(loc='lower left', fontsize=9)
ax.grid(alpha=0.25, linestyle=':')
fig.tight_layout()
fig.savefig('osm_demo/changping_route.png')
print(json.dumps(stats, ensure_ascii=False))
print('nodes in graph:', len(coords), 'edges:', sum(len(v) for v in adj.values()))
