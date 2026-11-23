# 离线地图数据与工具（本机固化环境）

## 入口
- 规划 CLI：`python C:\chatbox_temp\ai_toolkit\osm\osm_plan.py`
- 路由引擎：`python C:\chatbox_temp\ai_toolkit\osm_route.py`
- **默认出发地：北京化工大学(昌平校区) 40.25159,116.14444**

## 常见调用
```
osm_plan.py --areas
osm_plan.py --find "蟒山"
osm_plan.py --to "居庸关"
osm_plan.py --stops "蟒山国家森林公园;十三陵;居庸关" --plot plan.png
osm_plan.py --from "昌平城区" --to "回龙观" --mode drive --json
```

## 文件
| 文件 | 说明 |
|---|---|
| changping.osm.pbf | 昌平区切片 5.72 MB（876,311 节点 / 88,659 way） |
| beijing.osm.pbf | 北京省级底图 41.78 MB（裁别的区用） |
| fetch.py | 分段并行下载器（断点续传）：`python fetch.py <秒> <并发>` |
| clip_bbox.py | 按 bbox 裁 pbf：`--bbox minlon,minlat,maxlon,maxlat` |
| find_boundary.py | 从省级 pbf 找区县行政边界 bbox（改脚本内名称） |
| plot_route.py | 早期演示用的出图脚本（现功能已并入 osm_plan.py --plot） |
| cache/ | 图与地点索引 pickle 缓存（改 pbf 后自动失效重算） |

## 昌平区边界
relation 2988894（admin_level=6），bbox `115.8382,40.0353,116.4999,40.3915`，中心 `40.2365,116.178`

## 数据来源与限制
- 来源：`https://download.openstreetmap.fr/extracts/asia/china/beijing-latest.osm.pbf`（Geofabrik / Overpass 本机不可达）
- 单连接 ~15 KB/s，16 并发 40~130 KB/s；41.78 MB 约 15 分钟
- 计时为「按道路等级限速的自由流」估计，不含红绿灯/拥堵/限行；无公交时刻表
