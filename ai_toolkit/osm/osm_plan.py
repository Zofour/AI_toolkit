# -*- coding: utf-8 -*-
"""
离线地图：地点查找 + 路径规划 + 多站行程（OSM 数据，本机全离线）
默认出发地：北京化工大学(昌平校区) 40.25159,116.14444

常用：
  python osm_plan.py --find "化工大学"                  # 查地点
  python osm_plan.py --to "居庸关"                      # 默认从学校出发
  python osm_plan.py --from "昌平城区" --to "回龙观" --mode drive
  python osm_plan.py --stops "定陵;居庸关;蟒山"          # 多站行程（含每段与总里程）
  python osm_plan.py --to "十三陵" --plot out.png        # 出图
  python osm_plan.py --areas                            # 列出本机已有离线地图

参数：--mode drive|walk|bike  --pbf 自定义pbf  --json 纯JSON输出
"""
import argparse, json, os, pickle, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import osm_route as R

DATA = r'C:\chatbox_temp\ai_toolkit\osm'
CACHE = os.path.join(DATA, 'cache')
DEFAULT_ORIGIN = (40.25159, 116.14444)   # 北京化工大学(昌平校区)
DEFAULT_PBF = os.path.join(DATA, 'changping.osm.pbf')


def areas():
    return [f for f in os.listdir(DATA) if f.endswith('.osm.pbf')]


def pick_pbf(pbf):
    if pbf:
        return pbf if os.path.isabs(pbf) else os.path.join(DATA, pbf)
    if os.path.exists(DEFAULT_PBF):
        return DEFAULT_PBF
    raise SystemExit(f'找不到默认地图 {DEFAULT_PBF}，用 --pbf 指定')


def _cache_path(pbf, kind):
    os.makedirs(CACHE, exist_ok=True)
    tag = os.path.splitext(os.path.basename(pbf))[0]
    st = os.stat(pbf)
    return os.path.join(CACHE, f'{tag}_{kind}_{int(st.st_mtime)}.pkl')


def get_graph(pbf, mode='drive'):
    cp = _cache_path(pbf, 'graph_' + mode)
    if os.path.exists(cp):
        with open(cp, 'rb') as f:
            coords, adj = pickle.load(f)
        return coords, adj
    coords, adj = R.build_graph(pbf, mode)
    with open(cp, 'wb') as f:
        pickle.dump((coords, adj), f, protocol=4)
    return coords, adj


def get_places(pbf):
    """返回 [(name, lat, lon, kind)]"""
    cp = _cache_path(pbf, 'places')
    if os.path.exists(cp):
        with open(cp, 'rb') as f:
            return pickle.load(f)
    import osmium
    out = []
    for o in osmium.FileProcessor(pbf, osmium.osm.NODE | osmium.osm.WAY).with_locations():
        nm = o.tags.get('name:zh') or o.tags.get('name') or o.tags.get('name:en')
        if not nm:
            continue
        if o.is_node():
            lat, lon = o.location.lat, o.location.lon
            kind = 'node'
        else:
            nl = [n for n in o.nodes if n.location.valid()]
            if not nl:
                continue
            lat = sum(n.location.lat for n in nl) / len(nl)
            lon = sum(n.location.lon for n in nl) / len(nl)
            kind = 'way'
        out.append((nm, round(lat, 6), round(lon, 6), kind))
    with open(cp, 'wb') as f:
        pickle.dump(out, f, protocol=4)
    return out


def norm(s):
    return s.replace(' ', '').replace('（', '(').replace('）', ')').lower()


def find_places(places, q, limit=12):
    nq = norm(q)
    exact = [p for p in places if norm(p[0]) == nq]
    start = [p for p in places if norm(p[0]).startswith(nq)]
    has = [p for p in places if nq in norm(p[0])]
    seen, res = set(), []
    for p in exact + start + has:
        if p[0] in seen:
            continue
        seen.add(p[0])
        res.append(p)
        if len(res) >= limit:
            break
    return res


def resolve(spec, places, what='地点'):
    """'lat,lon' 或地点名 -> (lat, lon, 显示名)"""
    s = spec.strip()
    parts = s.split(',')
    if len(parts) == 2:
        try:
            lat, lon = float(parts[0]), float(parts[1])
            return lat, lon, f'{lat},{lon}'
        except ValueError:
            pass
    hits = find_places(places, s, limit=1)
    if not hits:
        raise SystemExit(f'找不到{what}「{s}」，先用 --find 查一下名称')
    nm, lat, lon, _ = hits[0]
    return lat, lon, nm


def leg(coords, adj, a, b, mode):
    s = R.nearest(coords, a[0], a[1])
    t = R.nearest(coords, b[0], b[1])
    path, sec = R.astar(coords, adj, s, t, max_speed_kmh=120 if mode == 'drive' else 25)
    if not path:
        return None
    dist = sum(adj[path[i]][path[i + 1]][0] for i in range(len(path) - 1))
    return {'path': path, 'dist_km': round(dist / 1000, 2), 'time_min': round(sec / 60, 1),
            'snap_start_m': round(R.hav(a, coords[s])), 'snap_end_m': round(R.hav(b, coords[t]))}


def plot_legs(coords, adj, legs, names, out):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection
    plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
    segs = [[(coords[u][1], coords[u][0]), (coords[v][1], coords[v][0])]
            for u, nbs in adj.items() if u in coords for v in nbs if v in coords][::3]
    fig, ax = plt.subplots(figsize=(11, 9), dpi=130)
    ax.add_collection(LineCollection(segs, colors='#bbbbbb', linewidths=0.35))
    colors = ['#d62728', '#1f77b4', '#2ca02c', '#9467bd', '#ff7f0e', '#8c564b']
    for i, L in enumerate(legs):
        pts = [(coords[n][1], coords[n][0]) for n in L['path']]
        xs, ys = zip(*pts)
        c = colors[i % len(colors)]
        ax.plot(xs, ys, color=c, linewidth=2.2,
                label=f'{names[i]} -> {names[i+1]}  {L["dist_km"]} km / {L["time_min"]} min')
        ax.plot(xs[0], ys[0], 'o', color=c, markersize=7)
        ax.plot(xs[-1], ys[-1], 's', color=c, markersize=7)
    ax.autoscale()
    ax.set_aspect(1 / 0.766)
    ax.set_xlabel('longitude'); ax.set_ylabel('latitude')
    ax.set_title('Offline OSM route (Changping, Beijing)')
    ax.legend(loc='lower left', fontsize=9)
    ax.grid(alpha=0.25, linestyle=':')
    fig.tight_layout(); fig.savefig(out)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--areas', action='store_true')
    ap.add_argument('--pbf')
    ap.add_argument('--find')
    ap.add_argument('--limit', type=int, default=12)
    ap.add_argument('--from', dest='src')
    ap.add_argument('--to', dest='dst')
    ap.add_argument('--stops')
    ap.add_argument('--mode', default='drive')
    ap.add_argument('--plot')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()

    if a.areas:
        for f in sorted(areas()):
            p = os.path.join(DATA, f)
            print(f'{f}  {os.path.getsize(p)/1e6:.2f} MB')
        print('默认出发地: 北京化工大学(昌平校区) 40.25159,116.14444')
        return

    pbf = pick_pbf(a.pbf)

    if a.find:
        places = get_places(pbf)
        hits = find_places(places, a.find, a.limit)
        if not hits:
            print('无匹配'); return
        for nm, lat, lon, kind in hits:
            print(f'{nm}\t{lat},{lon}\t{kind}')
        return

    places = get_places(pbf)
    coords, adj = get_graph(pbf, a.mode)

    if a.stops:
        raw = [s.strip() for s in a.stops.split(';') if s.strip()]
        pts = [DEFAULT_ORIGIN + ('北京化工大学(昌平校区)',)] if not a.src else [resolve(a.src, places, '出发地')]
        pts += [resolve(x, places, '途经点') for x in raw]
    else:
        if not a.dst:
            raise SystemExit('需要 --to 或 --stops，或 --find 查地点')
        if a.src:
            pts = [resolve(a.src, places, '出发地'), resolve(a.dst, places, '目的地')]
        else:
            pts = [DEFAULT_ORIGIN + ('北京化工大学(昌平校区)',), resolve(a.dst, places, '目的地')]

    legs = []
    for i in range(len(pts) - 1):
        L = leg(coords, adj, pts[i][:2], pts[i + 1][:2], a.mode)
        if L is None:
            raise SystemExit(f'第 {i+1} 段无路可走: {pts[i][2]} -> {pts[i+1][2]}')
        L['from'], L['to'] = pts[i][2], pts[i + 1][2]
        legs.append(L)

    total_d = round(sum(L['dist_km'] for L in legs), 2)
    total_t = round(sum(L['time_min'] for L in legs), 1)
    out = {'mode': a.mode, 'origin_default': a.src is None,
           'legs': [{k: v for k, v in L.items() if k != 'path'} for L in legs],
           'total_km': total_d, 'total_min': total_t}

    if a.plot:
        names = [p[2] for p in pts]
        out['plot'] = plot_legs(coords, adj, legs, names, a.plot)

    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        for i, L in enumerate(legs, 1):
            print(f'{i}. {L["from"]} -> {L["to"]}: {L["dist_km"]} km, {L["time_min"]} min'
                  f'  (吸附 {L["snap_start_m"]}m/{L["snap_end_m"]}m)')
        if len(legs) > 1:
            print(f'总计: {total_d} km, {total_t} min')
        if a.plot:
            print('图:', a.plot)


if __name__ == '__main__':
    main()
