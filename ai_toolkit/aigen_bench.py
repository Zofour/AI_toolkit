# -*- coding: utf-8 -*-
"""
本机 ComfyUI 生成模型能力基准测试
- 逐模型串行生成，每个模型前后调用 /free 卸载权重，避免显存叠加爆显存
- 每个模型对 3 类提示词各出 1 张：人像 / 写实风景 / 写实静物
- 结果图落盘到 OUT\<modelkey>\，状态写 OUT\bench_state.json
用法: python aigen_bench.py [--only key1,key2] [--steps-mult 1.0]
"""
import argparse, json, os, sys, time, traceback

sys.path.insert(0, r"C:\chatbox_temp\ai-gen-studio")
from comfy import ComfyClient, build_workflow, WorkflowError  # noqa

BASE = "http://127.0.0.1:8000"
OUT = r"C:\chatbox_temp\aigen_bench"
STATE = os.path.join(OUT, "bench_state.json")

TAG_A = ("1girl, solo, portrait, long silver hair, red eyes, looking at viewer, detailed face, "
         "soft lighting, cherry blossom background, masterpiece, best quality, highly detailed")
SENT_A = ("A portrait of a young woman with long silver hair and red eyes, looking at the viewer, "
          "soft cinematic lighting, cherry blossoms in the background, highly detailed, high quality.")
TAG_B = ("photorealistic, mountain lake at golden hour, mist over water, pine forest, dramatic sky, "
         "crisp reflections, ultra detailed, sharp focus, 8k, national geographic")
SENT_B = ("A photorealistic mountain lake at golden hour, mist drifting over the water, a pine forest "
          "on the shore, dramatic clouds and crisp reflections, ultra detailed, National Geographic style.")
TAG_C = ("a red apple and a glass of water on a rustic wooden table, studio lighting, shallow depth of "
         "field, photorealistic, ultra detailed, product photography")
SENT_C = ("A red apple next to a glass of water on a rustic wooden table, studio lighting, shallow depth "
          "of field, photorealistic product photography, ultra detailed.")

NEG = "worst quality, low quality, blurry, jpeg artifacts, watermark, text, signature, deformed, extra fingers, bad anatomy"

SD = dict(model_type="checkpoint", width=512, height=512, steps=25, cfg=7.0,
          sampler="dpmpp_2m", scheduler="karras", seed=12345)

MODELS = [
    dict(key="ekmix", label="Ekmix-gen3", style="tags", **SD,
         ckpt="Ekmix-gen3.ckpt"),
    dict(key="hd20", label="HD-20-non-ema-fp32", style="tags", **SD,
         ckpt="HD-20-non-ema-fp32.safetensors"),
    dict(key="cosfmix", label="cosfMix-v2", style="tags", **SD,
         ckpt="cosfMix-v2.safetensors"),
    dict(key="dreamlike", label="dreamlike-diffusion-1.0", style="tags", **SD,
         ckpt="dreamlike-diffusion-1.0.safetensors"),
    dict(key="anythingv5", label="anything-v5", style="tags", **SD,
         ckpt=r"sd1.5\anything-v5.safetensors"),
    dict(key="zetaturbo", label="Z-Image Turbo", style="sent",
         model_type="z_image", unet="z_image_turbo_bf16.safetensors",
         clip="qwen_3_4b.safetensors", vae="ae.safetensors",
         width=1024, height=1024, steps=8, cfg=1.0,
         sampler="res_multistep", scheduler="simple", seed=12345),
    dict(key="anima", label="Anima base v1.0", style="sent",
         model_type="anima", unet="anima-base-v1.0.safetensors",
         clip="qwen_3_06b_base.safetensors", vae="qwen_image_vae.safetensors",
         width=1024, height=1024, steps=30, cfg=4.0,
         sampler="euler", scheduler="simple", seed=12345),
    dict(key="netayume", label="NetaYumev35 all-in-one", style="sent",
         model_type="checkpoint",
         ckpt="NetaYumev35_pretrained_all_in_one.safetensors",
         width=1024, height=1024, steps=25, cfg=7.0,
         sampler="dpmpp_2m", scheduler="karras", seed=12345),
]

PROMPTS = {
    "A_portrait":  ("人像(动漫/角色)", TAG_A, SENT_A),
    "B_landscape": ("写实风景", TAG_B, SENT_B),
    "C_stilllife": ("写实静物/产品", TAG_C, SENT_C),
}


def log(msg):
    line = time.strftime("%H:%M:%S ") + str(msg)
    print(line, flush=True)
    with open(os.path.join(OUT, "bench.log"), "a", encoding="utf-8") as f:
        f.write(line + "\n")


def free_mem(c):
    try:
        c._post("/free", {"unload_models": True, "free_memory": True}, timeout=30)
        time.sleep(3)
    except Exception as e:
        log("  /free warn: %s" % e)


def run_model(c, m, only_steps_mult):
    key = m["key"]
    d = os.path.join(OUT, key)
    os.makedirs(d, exist_ok=True)
    log("=== %s (%s) ===" % (m["label"], m["model_type"]))
    free_mem(c)
    res = {"key": key, "label": m["label"], "type": m["model_type"], "images": [], "errors": []}
    for pkey, (pname, tag, sent) in PROMPTS.items():
        prompt = sent if m["style"] == "sent" else tag
        spec = dict(m)
        spec["prompt"] = prompt
        spec["negative"] = NEG
        spec["batch"] = 1
        spec["steps"] = max(1, int(round(m["steps"] * only_steps_mult)))
        wf = build_workflow(spec)
        t0 = time.time()
        try:
            pid, job = c.queue_prompt(wf)
        except WorkflowError as e:
            log("  [%s] 校验失败: %s" % (pkey, e))
            res["errors"].append({"prompt": pkey, "error": "validate: %s" % e})
            break
        hist = None
        deadline = time.time() + 420
        while time.time() < deadline:
            time.sleep(1.5)
            hist = c.get_history(pid)
            if hist and hist.get("outputs"):
                break
            if hist and hist.get("status", {}).get("status_str") == "error":
                break
        if not hist or not hist.get("outputs"):
            msg = "timeout/no-output"
            if hist and hist.get("status", {}).get("messages"):
                msg = str(hist["status"]["messages"])[:300]
            log("  [%s] 失败: %s" % (pkey, msg))
            res["errors"].append({"prompt": pkey, "error": msg})
            continue
        saved = []
        for node_out in hist["outputs"].values():
            for im in node_out.get("images", []) or []:
                try:
                    data = c.get_image(im)
                    fn = "%s_%s.png" % (key, pkey)
                    with open(os.path.join(d, fn), "wb") as f:
                        f.write(data)
                    saved.append(fn)
                except Exception as e:
                    log("  [%s] 取图失败: %s" % (pkey, e))
        dt = time.time() - t0
        log("  [%s] ok %.1fs -> %s" % (pkey, dt, saved))
        res["images"].append({"prompt": pkey, "name": pname, "files": saved, "sec": round(dt, 1)})
    free_mem(c)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--steps-mult", type=float, default=1.0)
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    c = ComfyClient(BASE)
    ok, info = c.ping()
    if not ok:
        log("ComfyUI 未就绪: %s" % info)
        sys.exit(1)
    log("ComfyUI ok: %s" % info)
    only = [x for x in a.only.split(",") if x]
    models = [m for m in MODELS if (not only or m["key"] in only)]
    state = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "results": [], "status": "running"}
    for m in models:
        try:
            r = run_model(c, m, a.steps_mult)
        except Exception as e:
            log("!! %s 崩溃: %s" % (m["key"], e))
            traceback.print_exc()
            r = {"key": m["key"], "label": m["label"], "fatal": str(e)}
        state["results"].append(r)
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    state["status"] = "done"
    state["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    log("ALL DONE")


if __name__ == "__main__":
    main()
