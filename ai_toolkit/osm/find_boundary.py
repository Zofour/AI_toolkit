# -*- coding: utf-8 -*-
"""找昌平区行政边界 bbox"""
import osmium

src = 'osm_demo/beijing.osm.pbf'
rel_id = None
way_ids = set()
for o in osmium.FileProcessor(src, osmium.osm.RELATION):
    if o.tags.get('boundary') == 'administrative' and '昌平' in o.tags.get('name', '') + o.tags.get('name:zh', ''):
        print('REL', o.id, o.tags.get('name'), 'admin_level', o.tags.get('admin_level'), 'members', len(o.members))
        if o.tags.get('admin_level') == '6':
            rel_id = o.id
            way_ids = {m.ref for m in o.members if m.type == 'w'}
print('target rel', rel_id, 'ways', len(way_ids))

lats, lons = [], []
for o in osmium.FileProcessor(src, osmium.osm.NODE | osmium.osm.WAY).with_locations():
    if not o.is_way() or o.id not in way_ids:
        continue
    for n in o.nodes:
        if n.location.valid():
            lats.append(n.location.lat)
            lons.append(n.location.lon)

print('bbox minlon,minlat,maxlon,maxlat =',
      round(min(lons), 4), round(min(lats), 4), round(max(lons), 4), round(max(lats), 4),
      '| pts', len(lats))
print('center', round(sum(lats) / len(lats), 4), round(sum(lons) / len(lons), 4))
