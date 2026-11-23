# -*- coding: utf-8 -*-
"""从省级 pbf 裁出单个区县 bbox -> 小 pbf（供 osm_route.py 用）
用法: python clip_bbox.py beijing.osm.pbf changping.osm.pbf --bbox 115.83,40.02,116.52,40.40
"""
import argparse, os, sys
import osmium
from osmium.osm.mutable import Node, Way


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src')
    ap.add_argument('dst')
    ap.add_argument('--bbox', required=True, help='minlon,minlat,maxlon,maxlat')
    a = ap.parse_args()
    minlon, minlat, maxlon, maxlat = map(float, a.bbox.split(','))

    def inside(lat, lon):
        return minlat <= lat <= maxlat and minlon <= lon <= maxlon

    # pass 1: 收集 bbox 内的节点
    keep = {}
    tags_n = 0
    for obj in osmium.FileProcessor(a.src, osmium.osm.NODE):
        if inside(obj.location.lat, obj.location.lon):
            keep[obj.id] = (obj.location.lon, obj.location.lat, dict(obj.tags))
            tags_n += 1
    print(f'[clip] nodes inside bbox: {tags_n}', file=sys.stderr)

    # pass 2: 保留节点全在 bbox 内的 way
    ways = []
    for obj in osmium.FileProcessor(a.src, osmium.osm.WAY):
        ids = [n.ref for n in obj.nodes]
        if ids and all(i in keep for i in ids):
            ways.append((obj.id, ids, dict(obj.tags)))
    print(f'[clip] ways kept: {len(ways)}', file=sys.stderr)

    if os.path.exists(a.dst):
        os.remove(a.dst)
    w = osmium.SimpleWriter(a.dst)
    for nid, (lon, lat, t) in keep.items():
        w.add_node(Node(id=nid, location=osmium.osm.Location(lon, lat), tags=t))
    for wid, ids, t in ways:
        w.add_way(Way(id=wid, nodes=ids, tags=t))
    w.close()
    print(f'[clip] wrote {a.dst} {os.path.getsize(a.dst)/1e6:.2f} MB', file=sys.stderr)


if __name__ == '__main__':
    main()
