# -*- coding: utf-8 -*-
"""批量生成「真实世界环境」背景图（无人物），供人像合成 / 抠图风格化训练使用。

用法:
  python bg_gen.py --target 64 --budget 100 [--size 1536x1024] [--out DIR] [--model zetaturbo]

- 可断点续跑：已存在的 bg_NNN.png 跳过；每次调用最多跑 budget 秒后退出（便于绕过 120s 命令上限）。
- 所有背景图落 --out 目录（默认 D:\\zimage_persons_1000_matted\\_backgrounds）。
"""
import argparse
import os
import sys
import time

sys.path.insert(0, r"C:\chatbox_temp\ai_toolkit")
from aigen import ensure_comfy, build_spec, generate_once, NEG_BASE  # noqa: E402

NEG = (NEG_BASE + ", people, person, human, crowd, man, woman, face, text, watermark, "
       "logo, letters, signature, border, frame, painting, illustration, cartoon, "
       "anime, 3d render, cgi, low detail, oversaturated")

# (分类, 英文提示词) —— 覆盖室内 / 室外 / 影棚背景 / 纹理墙 多场景、多时段、多色调
PROMPTS = [
    # ---- 室内 ----
    ("office",   "photorealistic photograph of an empty modern office interior, large windows, desks and office chairs, soft natural daylight, shallow depth of field, 35mm lens"),
    ("office2",  "photorealistic empty startup office loft, exposed brick wall, standing desks, warm industrial pendant lights, wide shot"),
    ("cafe",     "photorealistic cozy coffee shop interior, wooden tables, hanging bulbs, warm ambient light, blurred bokeh background, no people"),
    ("library",  "photorealistic university library interior, tall wooden bookshelves, green reading lamps, quiet warm light, deep perspective"),
    ("classroom","photorealistic empty lecture classroom, rows of seats, blackboard, fluorescent lights, afternoon light through windows"),
    ("bedroom",  "photorealistic tidy modern bedroom, white bedding, window with sheer curtains, soft morning light, minimal"),
    ("livingroom","photorealistic contemporary living room, sofa, coffee table, houseplant, large window, warm evening lamps"),
    ("kitchen",  "photorealistic bright modern kitchen, marble countertop, cabinets, window daylight, clean and tidy"),
    ("restaurant","photorealistic upscale restaurant interior evening, warm dim lights, set tables, wine glasses bokeh, no people"),
    ("hotel",    "photorealistic luxury hotel lobby, marble floor, chandelier, tall windows, warm golden light"),
    ("museum",   "photorealistic museum gallery hall, polished floor, blank display walls, soft diffuse skylight, spacious"),
    ("bookstore","photorealistic independent bookstore interior, stacked books, warm reading lights, cozy narrow aisles"),
    ("gym",      "photorealistic modern gym interior, equipment racks, rubber floor, industrial ceiling lights, cool tones"),
    ("corridor", "photorealistic quiet hospital corridor, pale green walls, polished floor, fluorescent light, perspective vanishing point"),
    ("subway",   "photorealistic empty subway train interior, metal poles, seats, cool fluorescent light, motion blur windows"),
    ("bus",      "photorealistic empty city bus interior, seats and windows, daylight, warm tones"),
    ("plane",    "photorealistic empty airplane cabin interior, rows of seats, overhead bins, soft cabin light"),
    ("workshop", "photorealistic woodworking workshop, tools on wall, sawdust, warm tungsten light, cluttered bench"),
    ("artstudio","photorealistic artist studio loft, easels, paint splattered floor, big north window day light"),
    ("greenhouse","photorealistic botanical greenhouse interior, lush green plants, glass roof, humid soft light"),
    ("mall",     "photorealistic modern shopping mall atrium, glass railings, escalators, bright skylight"),
    ("bar",      "photorealistic dim cocktail bar interior, bottles on shelf, neon accent light, moody warm glow"),
    ("salon",    "photorealistic hair salon interior, mirrors, chairs, bright clean light, pastel tones"),
    ("barbershop","photorealistic vintage barbershop interior, leather chairs, mirrors, warm wood, tungsten light"),
    ("locker",   "photorealistic gym locker room, metal lockers, benches, cool light"),
    ("stairwell","photorealistic concrete stairwell, railing, daylight from above, brutalist"),
    ("rooftopterrace","photorealistic rooftop terrace with plants and lounge chairs, city skyline at dusk beyond railing"),
    # ---- 室外 / 街景 / 自然 ----
    ("street_day","photorealistic city street daytime, shopfronts, parked cars, pedestrians far away blurred, overcast light"),
    ("street_night","photorealistic city street at night, neon signs bokeh, wet asphalt reflections, moody"),
    ("park",     "photorealistic park path with trees, green lawn, dappled sunlight, benches, spring"),
    ("garden",   "photorealistic blooming garden, flowers, hedge, soft sunlight, shallow depth of field"),
    ("campus",   "photorealistic university campus quad, brick buildings, trees, sunny afternoon"),
    ("forest",   "photorealistic forest trail, tall trees, green moss, sunbeams through canopy, mist"),
    ("beach",    "photorealistic sandy beach with calm sea, blue sky, distant horizon, bright sunlight"),
    ("mountain", "photorealistic mountain landscape, rocky peaks, alpine meadow, dramatic clouds"),
    ("desert",   "photorealistic desert dunes at golden hour, warm sand, clear sky"),
    ("snow",     "photorealistic snowy winter landscape, snow covered trees, pale blue light, soft"),
    ("lake",     "photorealistic calm lake with reeds and distant hills, soft morning haze, reflections"),
    ("riverside","photorealistic riverside promenade, railing, water, city buildings across, dusk"),
    ("plaza",    "photorealistic european stone plaza, old buildings, cobblestone, warm afternoon light"),
    ("bridge",   "photorealistic steel bridge walkway, cables, city river below, clear sky"),
    ("market",   "photorealistic outdoor market street with stalls and awnings, colorful, no people"),
    ("alley",    "photorealistic narrow asian alley, pipes, lanterns, wet ground, cinematic"),
    ("parking",  "photorealistic empty rooftop parking lot, painted lines, city skyline, dusk"),
    ("stadium",  "photorealistic empty stadium stands and green field, clear sky, wide angle"),
    ("ballfield","photorealistic empty soccer field with goal, grass, blue sky, afternoon"),
    ("vineyard", "photorealistic vineyard rows on rolling hills, warm sunset light"),
    ("field",    "photorealistic golden wheat field, lone tree, blue sky, summer"),
    ("harbor",   "photorealistic marina harbor with boats and masts, calm water, evening light"),
    ("trainstation","photorealistic train station platform, tracks, station roof, daylight, perspective"),
    ("cafeoutdoor","photorealistic outdoor cafe terrace, umbrellas and tables, sunny street, no people"),
    ("temple",   "photorealistic east asian temple courtyard, red pillars, stone pavement, soft light"),
    ("templez",  "photorealistic chinese ancient architecture corridor, red columns, eaves, warm light"),
    ("skyline",  "photorealistic city skyline at golden hour, dense buildings, warm haze, distant view"),
    ("snowcabin","photorealistic cozy wooden cabin exterior among snow, warm window glow, twilight"),
    # ---- 影棚背景 / 纹理墙（模拟室内实拍背景）----
    ("seamless_teal","photorealistic seamless studio paper backdrop, teal green gradient, subtle fabric texture, even light"),
    ("seamless_warm","photorealistic seamless studio paper backdrop, warm beige gradient, subtle texture, soft light"),
    ("seamless_gray","photorealistic seamless studio paper backdrop, neutral gray gradient, subtle vignette, soft light"),
    ("seamless_red","photorealistic seamless studio paper backdrop, deep red gradient, subtle texture, dramatic light"),
    ("brickwall","photorealistic red brick wall texture, weathered, natural daylight, shallow depth of field"),
    ("concrete", "photorealistic raw concrete wall texture, brutalist, soft side light, subtle grain"),
    ("woodwall", "photorealistic wooden plank wall, warm brown, soft lighting"),
    ("plasterwall","photorealistic painted plaster wall, off white, subtle stains and texture, daylight"),
    ("bokehlights","photorealistic abstract night bokeh lights, city blur, colorful, dreamy out of focus"),
    ("blurredroom","photorealistic heavily blurred interior room background, soft colors, out of focus, bokeh"),
    ("marble",   "photorealistic polished marble wall with veins, elegant, soft light"),
    ("curtain",  "photorealistic sheer curtain by a window, soft backlit daylight, gentle folds"),
    ("bamboo",   "photorealistic bamboo grove, dense green stalks, soft filtered light"),
    ("muralwall","photorealistic graffiti painted brick wall, colorful street art, daylight, urban"),
    ("sunsetwall","photorealistic concrete wall lit by warm sunset light, long shadows, orange glow"),
    ("neonwall", "photorealistic wall with pink and blue neon light glow, moody night, wet street"),
    ("officeblur","photorealistic blurred office interior out of focus, cool tones, bokeh, shallow dof"),
    ("shelfblur","photorealistic heavily blurred bookshelf and plant background, warm tones, bokeh"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=64)
    ap.add_argument("--budget", type=float, default=100.0)
    ap.add_argument("--size", default="1536x1024")
    ap.add_argument("--out", default=r"D:\zimage_persons_1000_matted\_backgrounds")
    ap.add_argument("--model", default="zetaturbo")
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    n_prompts = len(PROMPTS)
    t0 = time.time()
    client = None
    made = 0
    for i in range(a.target):
        fn = os.path.join(a.out, "bg_%03d.png" % i)
        if os.path.exists(fn):
            continue
        if time.time() - t0 > a.budget:
            print("BUDGET reached at index %d" % i)
            break
        if client is None:
            client = ensure_comfy()
        cat, prompt = PROMPTS[i % n_prompts]
        seed = 731000 + i * 977
        spec = build_spec(a.model, prompt, NEG, seed, 1, a.size)
        ti = time.time()
        try:
            imgs = generate_once(client, spec)
        except Exception as e:
            print("FAIL idx=%d %s: %s" % (i, cat, e))
            continue
        with open(fn, "wb") as f:
            f.write(imgs[0])
        made += 1
        print("OK %03d %-14s %5.1fs -> %s" % (i, cat, time.time() - ti, os.path.basename(fn)))
    done = sum(1 for i in range(a.target) if os.path.exists(os.path.join(a.out, "bg_%03d.png" % i)))
    print("PROGRESS %d/%d (made %d this run, %.0fs)" % (done, a.target, made, time.time() - t0))


if __name__ == "__main__":
    main()
