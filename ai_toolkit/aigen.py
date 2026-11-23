# -*- coding: utf-8 -*-
"""
本机一键生图【生成器】——只负责：确保 ComfyUI 在线 -> 选模型 -> 按英文提示词出图
(提示词的撰写与出图后的质量判定，由 Chatbox 接入的 AI 完成，本脚本不做 LLM 调用)
所有生成图落到 TEMP 目录（默认 D:\\image_temp），可选另存到 --save。

用法:
  python aigen.py --prompt "1girl, silver hair, red eyes, best quality" --model anythingv5
  python aigen.py --need "写实雪山湖泊" --prompt "photorealistic mountain lake ..." --model auto
  python aigen.py --prompt "..." --model zetaturbo --size 768x768 --n 2 --save D:\\pics
  python aigen.py --list-models
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, r"C:\chatbox_temp\ai-gen-studio")
from comfy import ComfyClient, build_workflow, WorkflowError  # noqa: E402

COMFY_BASE = "http://127.0.0.1:8000"
COMFY_START_BAT = r"C:\chatbox_temp\ai_toolkit\comfyui_start.bat"
DEFAULT_TEMP = r"D:\image_temp"
NEG_BASE = ("worst quality, low quality, blurry, jpeg artifacts, watermark, text, signature, "
            "deformed, bad anatomy, extra fingers, lowres")

# ---------------------------------------------------------------- 模型能力目录（2026-10-11 本机实测）
# arch: checkpoint|z_image|anima ; style: tags(逗号标签) | sent(自然语言句)
MODEL_CATALOG = {
    "cosfmix": dict(label="cosfMix-v2", arch="checkpoint", style="tags", speed=3,
                    ckpt="cosfMix-v2.safetensors",
                    traits={"anime": 3, "portrait": 2, "landscape": 2, "product": 2, "versatile": 3},
                    note="SD1.5 全能王：日系动漫人物强 + 写实风景意外接近照片，静物良好"),
    "anythingv5": dict(label="anything-v5", arch="checkpoint", style="tags", speed=3,
                       ckpt=r"sd1.5\anything-v5.safetensors",
                       traits={"anime": 4, "portrait": 2, "landscape": 2, "versatile": 2},
                       note="纯正日系/丹波动漫第一梯队，人物最稳，写实偏弱"),
    "ekmix": dict(label="Ekmix-gen3", arch="checkpoint", style="tags", speed=2,
                  ckpt="Ekmix-gen3.ckpt",
                  traits={"anime": 3, "portrait": 2, "artistic": 1, "versatile": 2},
                  note="日系动漫/2.5D 角色极强，构图丰富（含EMA副本，加载慢）"),
    "hd20": dict(label="HD-20-non-ema-fp32", arch="checkpoint", style="tags", speed=3,
                 ckpt="HD-20-non-ema-fp32.safetensors",
                 traits={"anime": 2, "portrait": 2, "artistic": 1},
                 note="清新动漫人物尚可；多物体指令遵从偏弱（常丢物体）"),
    "dreamlike": dict(label="dreamlike-diffusion-1.0", arch="checkpoint", style="tags", speed=3,
                      ckpt="dreamlike-diffusion-1.0.safetensors",
                      traits={"artistic": 3, "portrait": 2, "landscape": 2, "product": 1},
                      note="油画/艺术化、高饱和、半写实插画风；不要指望照片级"),
    "netayume": dict(label="NetaYumev35 all-in-one", arch="checkpoint", style="sent", speed=1,
                     ckpt="NetaYumev35_pretrained_all_in_one.safetensors",
                     overrides=dict(width=1024, height=1024, steps=30, cfg=2.2,
                                    sampler="euler", scheduler="simple"),
                     traits={"dreamy": 4, "anime": 2, "portrait": 2},
                     note="柔光梦幻粉彩唯美二次元（Lumina/Gemma2 架构）；必须低cfg(1.5~2.5)，"
                          "用 cfg7 会发暗发糊；非人物/写实题材很弱"),
    "zetaturbo": dict(label="Z-Image Turbo", arch="z_image", style="sent", speed=4,
                      unet="z_image_turbo_bf16.safetensors", clip="qwen_3_4b.safetensors",
                      vae="ae.safetensors",
                      overrides=dict(width=1024, height=1024, steps=8, cfg=1.0,
                                     sampler="res_multistep", scheduler="simple"),
                      traits={"photoreal": 3, "product": 3, "landscape": 3, "portrait": 2,
                              "versatile": 4},
                      note="8 步出图、又快又全面：写实静物/产品最强、写实风景强、2.5D 人物；默认首选"),
    # ---- 2026-11-12 新增：二次元三件套（逐个载入显存；出图后保持驻留，只在切换模型前 /free 释放旧模型）
    "anima_aes": dict(label="Anima Aesthetic v1.1", arch="anima", style="sent", speed=1,
                      unet="anima-aesthetic-v1.1.safetensors", clip="qwen_3_06b_base.safetensors",
                      vae="qwen_image_vae.safetensors",
                      overrides=dict(width=1024, height=1024, steps=30, cfg=4.0,
                                     sampler="er_sde", scheduler="simple"),
                      traits={"anime": 4, "quality": 4, "portrait": 3, "versatile": 3},
                      note="官方推荐的动漫微调版（Aesthetic），风格稳定；CFG 4~5，30 步"),
    "noobai": dict(label="NoobAI-XL 1.1", arch="checkpoint", style="tags", speed=2,
                   ckpt="NoobAI-XL-v1.1.safetensors",
                   overrides=dict(width=832, height=1216, steps=28, cfg=5.0,
                                  sampler="euler_ancestral", scheduler="normal"),
                   traits={"anime": 5, "portrait": 4, "quality": 4},
                   note="SDXL 动漫，Danbooru 标签覆盖最广，需画质标签与负面词；许可非商用"),
    "illustrious": dict(label="Illustrious XL v1.0", arch="checkpoint", style="tags", speed=2,
                        ckpt="Illustrious-XL-v1.0.safetensors",
                        overrides=dict(width=1024, height=1024, steps=28, cfg=5.0,
                                       sampler="euler_ancestral", scheduler="normal"),
                        traits={"anime": 5, "portrait": 4, "versatile": 3},
                        note="SDXL 动漫，原生 1536 分辨率，LoRA 生态最大；许可非商用"),
    "anima": dict(label="Anima base v1.0", arch="anima", style="sent", speed=1,
                  unet="anima-base-v1.0.safetensors", clip="qwen_3_06b_base.safetensors",
                  vae="qwen_image_vae.safetensors",
                  overrides=dict(width=1024, height=1024, steps=30, cfg=4.0,
                                 sampler="euler", scheduler="simple"),
                  traits={"photoreal": 4, "product": 4, "landscape": 2, "anime": 2, "quality": 4},
                  note="画质/指令遵从最强：写实静物产品、半写实风景、动漫人物都顶；慢(~30s/张)"),
}

CATEGORIES = {
    "anime": ["动漫", "二次元", "漫画", "動畫", "anime", "manga", "插画", "插圖", "日系", "萌", "少女",
              "女孩", "角色", "人物", "chibi", "q版", "illustration", "pixiv", "丹波", "danbooru",
              "1girl", "portrait of a girl"],
    "photoreal": ["写实", "寫實", "照片", "摄影", "逼真", "拟真", "真实", "realistic", "photo",
                  "photograph", "8k", "4k", "壁纸", "cinematic", "电影感"],
    "product": ["产品", "商品", "静物", "食物", "美食", "product", "still life", "food"],
    "landscape": ["风景", "景色", "山水", "自然", "landscape", "scenery", "山", "海", "森林"],
    "dreamy": ["唯美", "梦幻", "柔光", "仙", "治愈", "氛围感", "soft", "dreamy", "pastel", "朦胧"],
    "artistic": ["油画", "艺术", "藝術", "水彩", "重彩", "插画风", "artistic", "painting", "concept art"],
    "fast": ["快", "快速", "马上", "立刻", "草稿", "draft", "速"],
    "quality": ["高质量", "高質量", "精细", "精致", "最佳", "高清", "细节", "壁纸", "4k", "8k",
                "masterpiece", "best quality"],
}


def detect_traits(text):
    t = (text or "").lower()
    found = {k: 1 for k, kws in CATEGORIES.items() if any(w.lower() in t for w in kws)}
    return found


def pick_model(text):
    """按实测能力做规则选择，返回 (model_key, 命中特征)。"""
    f = detect_traits(text)
    if f.get("photoreal") or f.get("product"):
        key = "anima" if (f.get("quality") and not f.get("fast")) else "zetaturbo"
    elif f.get("anime") and f.get("dreamy"):
        key = "netayume"
    elif f.get("anime"):
        key = "cosfmix" if (f.get("landscape") or f.get("artistic")) else "anythingv5"
    elif f.get("dreamy"):
        key = "netayume"
    elif f.get("artistic"):
        key = "dreamlike"
    elif f.get("landscape"):
        key = "zetaturbo"
    elif f.get("quality"):
        key = "anima"
    else:
        key = "zetaturbo"
    return key, f


def build_spec(key, prompt, negative, seed, batch, size, steps=None, cfg=None):
    m = MODEL_CATALOG[key]
    spec = dict(model_type=m["arch"], prompt=prompt, negative=negative, seed=seed, batch=batch)
    if m["arch"] == "checkpoint":
        spec["ckpt"] = m["ckpt"]
    else:
        spec.update(unet=m["unet"], clip=m["clip"], vae=m["vae"])
    base = dict(width=512, height=512, steps=25, cfg=7.0, sampler="dpmpp_2m", scheduler="karras")
    if m["arch"] in ("z_image", "anima"):
        base = dict(width=1024, height=1024, steps=25, cfg=4.0, sampler="euler", scheduler="simple")
    base.update(m.get("overrides", {}))
    spec.update(base)
    if size:
        w, h = size.lower().split("x")
        spec["width"], spec["height"] = int(w), int(h)
    if steps:
        spec["steps"] = int(steps)
    if cfg is not None:
        spec["cfg"] = float(cfg)
    return spec


def ensure_comfy(wait=90, log=print):
    c = ComfyClient(COMFY_BASE)
    ok, info = c.ping()
    if ok:
        return c
    log("ComfyUI 未运行，正在启动…")
    subprocess.Popen(["cmd", "/c", COMFY_START_BAT], creationflags=0x08000000)
    dl = time.time() + wait
    while time.time() < dl:
        time.sleep(3)
        ok, info = c.ping()
        if ok:
            log("ComfyUI 已就绪: %s" % info)
            return c
    raise RuntimeError("ComfyUI 启动超时；请手动打开 Comfy Desktop 后重试")


def generate_once(client, spec):
    wf = build_workflow(spec)
    pid, job = client.queue_prompt(wf)
    dl = time.time() + 600
    hist = None
    while time.time() < dl:
        time.sleep(1.5)
        hist = client.get_history(pid)
        if hist and hist.get("outputs"):
            break
        if (hist or {}).get("status", {}).get("status_str") == "error":
            break
    if not hist or not hist.get("outputs"):
        raise RuntimeError("生成失败/超时: %s" % str((hist or {}).get("status"))[:300])
    out = []
    for node_out in hist["outputs"].values():
        for im in node_out.get("images", []) or []:
            out.append(client.get_image(im))
    return out


LOADED_STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".vram_loaded.json")


def read_loaded():
    """上一次出图后仍驻留在显存里的模型 key（无则返回空串）。"""
    try:
        with open(LOADED_STATE, "r", encoding="utf-8") as f:
            return json.load(f).get("model", "")
    except Exception:
        return ""


def write_loaded(key):
    with open(LOADED_STATE, "w", encoding="utf-8") as f:
        json.dump({"model": key}, f)


def free_vram(client_base=COMFY_BASE):
    """卸载 ComfyUI 当前已载入的模型并释放显存。
    仅在两种时机调用：切换模型前（main 里 last != key）、或 --unload 手动释放。
    出图本身结束不会自动调用，模型会继续驻留显存。
    失败只打印警告，不影响已生成的图。"""
    import urllib.request
    body = json.dumps({"unload_models": True, "free_memory": True}).encode("utf-8")
    req = urllib.request.Request(client_base + "/free", data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30):
            pass
        print("VRAM: 已释放（ComfyUI /free）")
        return True
    except Exception as e:
        print("VRAM: 释放失败（忽略）: %s" % e)
        return False


def main():
    ap = argparse.ArgumentParser(description="本机一键生图（生成器）")
    ap.add_argument("--prompt", default="", help="英文提示词（由 Chatbox AI 撰写）")
    ap.add_argument("--need", default="", help="中文需求，仅用于自动选模型与记录")
    ap.add_argument("--model", default="auto", help="auto 或 " + ",".join(MODEL_CATALOG))
    ap.add_argument("--n", type=int, default=1, help="一次生成张数(同提示词)")
    ap.add_argument("--size", default="", help="如 1024x1024")
    ap.add_argument("--steps", type=int, default=0)
    ap.add_argument("--cfg", type=float, default=-1)
    ap.add_argument("--seed", type=int, default=-1)
    ap.add_argument("--neg", default=NEG_BASE)
    ap.add_argument("--temp-dir", default=DEFAULT_TEMP)
    ap.add_argument("--save", default="")
    ap.add_argument("--tag", default="", help="文件名标记，如 r2")
    ap.add_argument("--list-models", action="store_true")
    ap.add_argument("--unload", action="store_true",
                    help="仅释放当前已载入的模型显存，不出图")
    a = ap.parse_args()

    if a.list_models:
        for k, m in MODEL_CATALOG.items():
            print("%-11s %-24s arch=%-10s style=%-5s %s" %
                  (k, m["label"], m["arch"], m["style"], m["note"]))
        return

    if a.unload:
        free_vram()
        write_loaded("")
        return
    if not a.prompt:
        print("需要 --prompt 给出英文提示词"); sys.exit(2)

    if a.model == "auto":
        key, traits = pick_model((a.need or "") + " " + a.prompt)
    else:
        key = a.model
        if key not in MODEL_CATALOG:
            print("未知模型 %s，可选: %s" % (key, list(MODEL_CATALOG))); sys.exit(2)
        traits = detect_traits((a.need or "") + " " + a.prompt)
    m = MODEL_CATALOG[key]
    print("模型: %s (%s) style=%s | 命中特征: %s" % (key, m["label"], m["style"], traits or "无"))

    os.makedirs(a.temp_dir, exist_ok=True)
    client = ensure_comfy()
    seed = a.seed if a.seed >= 0 else int(time.time()) % 2**31
    spec = build_spec(key, a.prompt, a.neg, seed, max(1, a.n), a.size or None,
                      steps=a.steps or None, cfg=(a.cfg if a.cfg >= 0 else None))
    t0 = time.time()
    last = read_loaded()
    if last and last != key:
        print("VRAM: 切换模型 %s -> %s，先释放旧模型" % (last, key))
        free_vram()
    try:
        imgs = generate_once(client, spec)
    except WorkflowError as e:
        print("工作流校验失败: %s" % e); sys.exit(1)
    ts = time.strftime("%Y%m%d_%H%M%S")
    tag = ("_" + a.tag) if a.tag else ""
    files = []
    for i, data in enumerate(imgs):
        fn = os.path.join(a.temp_dir, "%s%s_%s_%d.png" % (key, tag, ts, i))
        with open(fn, "wb") as f:
            f.write(data)
        files.append(fn)
    write_loaded(key)
    result = {"ok": True, "model": key, "label": m["label"], "style": m["style"],
              "seed": seed, "prompt": a.prompt, "size": [spec["width"], spec["height"]],
              "steps": spec["steps"], "cfg": spec["cfg"], "sec": round(time.time() - t0, 1),
              "files": files, "note": m["note"]}
    if a.save:
        os.makedirs(a.save, exist_ok=True)
        saved = []
        for f in files:
            dst = os.path.join(a.save, os.path.basename(f))
            shutil.copy2(f, dst); saved.append(dst)
        result["saved"] = saved
    print("FILES: " + " | ".join(files))
    print("JSON=" + json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
