# -*- coding: utf-8 -*-
"""
离线 OSM 路网路由引擎（本机可复用件）
用法:
  python osm_route.py --pbf C:\\osm\\beijing.osm.pbf --from 39.9087,116.3975 --to 39.9999,116.2755 --mode drive
  python osm_route.py --pbf ... --poi tourism=attraction --near 39.9087,116.3975 --radius 3000
参数:
  --mode drive|walk|bike  (默认 drive)
  --poi KEY=VALUE         抽取 POI
  --selftest              用合成 PBF 端到端自检
"""
import argparse, math, heapq, os, sys, json

# 各路面等级默认速度 km/h (drive)
SPEED = {
    'motorway': 100, 'motorway_link': 70, 'trunk': 80, 'trunk_link': 55,
    'primary': 60, 'primary_link': 45, 'secondary': 50, 'secondary_link': 40,
    'tertiary': 40, 'tertiary_link': 30, 'unclassified': 30, 'residential': 25,
    'living_street': 15, 'service': 15, 'road': 25,
}
WALK_SPEED = 5.0
BIKE_SPEED = 15.0


def hav(a, b):
    R = 6371000.0
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def build_graph(pbf, mode='drive', highway_filter=None):
    """返回 (coords, adj)  coords: {nid:(lat,lon)}  adj: {u:{v:(dist_m, sec)}}"""
    import osmium

    if highway_filter is None:
        if mode == 'walk':
            highway_filter = {'footway', 'path', 'pedestrian', 'steps', 'living_street', 'residential',
                              'service', 'unclassified', 'tertiary', 'secondary', 'primary', 'track',
                              'cycleway', 'trunk', 'corridor', 'sidewalk'}
        elif mode == 'bike':
            highway_filter = {'cycleway', 'path', 'residential', 'service', 'unclassified', 'tertiary',
                              'secondary', 'primary', 'living_street', 'track'}
        else:
            highway_filter = set(SPEED)

    coords, adj = {}, {}
    fp = osmium.FileProcessor(pbf, osmium.osm.NODE | osmium.osm.WAY).with_locations()
    nway = 0
    for obj in fp:
        if obj.is_way():
            t = obj.tags
            hw = t.get('highway')
            if hw not in highway_filter:
                continue
            if t.get('area') == 'yes' or t.get('access') in ('no', 'private'):
                continue
            if mode == 'drive' and t.get('motor_vehicle') == 'no':
                continue
            if mode == 'walk' and t.get('foot') == 'no':
                continue
            spd = WALK_SPEED if mode == 'walk' else (BIKE_SPEED if mode == 'bike' else SPEED.get(hw, 25))
            nl = [n for n in obj.nodes if n.location.valid()]
            ids = [n.ref for n in nl]
            pts = [(n.location.lat, n.location.lon) for n in nl]
            for i in range(len(ids) - 1):
                u, v = ids[i], ids[i + 1]
                if u == v:
                    continue
                d = hav(pts[i], pts[i + 1])
                if d <= 0:
                    continue
                s = d / (spd / 3.6)
                coords[u] = pts[i]
                coords[v] = pts[i + 1]
                adj.setdefault(u, {})[v] = (d, s)
                if t.get('oneway') not in ('yes', '1', 'true') and hw not in ('motorway',):
                    adj.setdefault(v, {})[u] = (d, s)
            nway += 1
    print(f"[graph] ways={nway} nodes={len(coords)} edges={sum(len(v) for v in adj.values())}", file=sys.stderr)
    return coords, adj


def nearest(coords, lat, lon, k=1):
    best = sorted(coords.items(), key=lambda kv: (kv[1][0] - lat) ** 2 + (kv[1][1] - lon) ** 2)[:k]
    return best[0][0] if k == 1 else best


def astar(coords, adj, s, t, max_speed_kmh=110):
    def h(n):
        return hav(coords[n], coords[t]) / (max_speed_kmh / 3.6)

    g = {s: 0.0}
    par = {}
    pq = [(h(s), 0.0, s)]
    closed = set()
    while pq:
        f, gc, cur = heapq.heappop(pq)
        if cur == t:
            path = [cur]
            while cur in par:
                cur = par[cur]
                path.append(cur)
            return path[::-1], gc
        if cur in closed:
            continue
        closed.add(cur)
        for nb, (d, sec) in adj.get(cur, {}).items():
            ng = gc + sec
            if ng < g.get(nb, 1e18):
                g[nb] = ng
                par[nb] = cur
                heapq.heappush(pq, (ng + h(nb), ng, nb))
    return None, None


def extract_poi(pbf, key, val=None, center=None, radius_m=None):
    import osmium
    out = []
    for obj in osmium.FileProcessor(pbf, osmium.osm.NODE | osmium.osm.WAY).with_locations():
        t = obj.tags
        if t.get(key) != val:
            continue
        if obj.is_node():
            loc = obj.location
            lat, lon = loc.lat, loc.lon
        else:
            nl = [n for n in obj.nodes if n.location.valid()]
            if not nl:
                continue
            lat = sum(n.location.lat for n in nl) / len(nl)
            lon = sum(n.location.lon for n in nl) / len(nl)
        if center and radius_m and hav(center, (lat, lon)) > radius_m:
            continue
        keep_keys = ('tourism', 'amenity', 'opening_hours', 'fee', 'phone', 'wikidata', 'leisure')
        out.append({'name': t.get('name:zh') or t.get('name', ''), 'lat': round(lat, 6),
                    'lon': round(lon, 6), 'tags': {k2: t[k2] for k2 in keep_keys if k2 in t}})
    return out


def selftest(tmp='osm_demo/selftest.pbf'):
    """合成一个 1.1km 直线 + 一条 300m 捷径的小 PBF，验证解析/建图/A*。"""
    import osmium
    os.makedirs(os.path.dirname(tmp) or '.', exist_ok=True)
    if os.path.exists(tmp):
        os.remove(tmp)
    w = osmium.SimpleWriter(tmp)
    # 节点: 0..4 直线(经度递增), 5 为捷径中点(纬度偏北)
    pts = {1: (39.9000, 116.3000), 2: (39.9000, 116.3100), 3: (39.9000, 116.3200),
           4: (39.9000, 116.3300), 5: (39.9030, 116.3100)}
    from osmium.osm.mutable import Node, Way
    for i, (la, lo) in pts.items():
        w.add_node(Node(id=i, location=osmium.osm.Location(lo, la), tags={}))
    w.add_way(Way(id=1, nodes=[1, 2, 3, 4], tags={'highway': 'primary', 'name': '直线主干道'}))
    w.add_way(Way(id=2, nodes=[2, 5], tags={'highway': 'residential', 'name': '北侧小路'}))
    w.add_way(Way(id=3, nodes=[5, 3], tags={'highway': 'residential', 'name': '北侧小路2'}))
    w.close()

    coords, adj = build_graph(tmp, 'drive')
    s, t = 1, 4
    path, sec = astar(coords, adj, s, t)
    dist = sum(adj[path[i]][path[i + 1]][0] for i in range(len(path) - 1))
    print(json.dumps({'mode': 'drive', 'path_nodes': path,
                      'dist_m': round(dist), 'time_s': round(sec),
                      'expect': '走主干道 1->2->3->4 约 2560m'}, ensure_ascii=False))
    coords, adj = build_graph(tmp, 'walk')
    path2, sec2 = astar(coords, adj, 1, 4, max_speed_kmh=25)
    dist2 = sum(adj[path2[i]][path2[i + 1]][0] for i in range(len(path2) - 1))
    print(json.dumps({'mode': 'walk', 'path_nodes': path2, 'dist_m': round(dist2),
                      'time_s': round(sec2), 'expect': '仍是主干道更短'}, ensure_ascii=False))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--pbf')
    ap.add_argument('--from', dest='src')
    ap.add_argument('--to', dest='dst')
    ap.add_argument('--mode', default='drive')
    ap.add_argument('--poi')
    ap.add_argument('--near')
    ap.add_argument('--radius', type=float)
    ap.add_argument('--k', type=int, default=1)
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args()

    if a.selftest:
        selftest()
        raise SystemExit

    if not a.pbf:
        ap.error('--pbf 必填')
    if a.poi:
        k, _, v = a.poi.partition('=')
        c = tuple(map(float, a.near.split(','))) if a.near else None
        res = extract_poi(a.pbf, k, v or None, c, a.radius)
        print(json.dumps(res[:200], ensure_ascii=False, indent=1))
        raise SystemExit

    coords, adj = build_graph(a.pbf, a.mode)
    slat, slon = map(float, a.src.split(','))
    tlat, tlon = map(float, a.dst.split(','))
    s = nearest(coords, slat, slon)
    t = nearest(coords, tlat, tlon)
    path, sec = astar(coords, adj, s, t)
    if not path:
        print('no route'); raise SystemExit(1)
    dist = sum(adj[path[i]][path[i + 1]][0] for i in range(len(path) - 1))
    print(json.dumps({'mode': a.mode, 'nodes': len(path), 'dist_km': round(dist / 1000, 2),
                      'time_min': round(sec / 60, 1),
                      'start_snap_m': round(hav((slat, slon), coords[s])),
                      'end_snap_m': round(hav((tlat, tlon), coords[t]))}, ensure_ascii=False))
