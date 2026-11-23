# -*- coding: utf-8 -*-
"""NetaYume 架构/参数探测：尝试不同 cfg / ModelSamplingAuraFlow，看哪种正常。"""
import sys, os, time, json
sys.path.insert(0, r"C:\chatbox_temp\ai-gen-studio")
from comfy import ComfyClient, WorkflowError

OUT = r"C:\chatbox_temp\aigen_bench\netayume_probe"
os.makedirs(OUT, exist_ok=True)
c = ComfyClient("http://127.0.0.1:8000")
POS = ("A portrait of a young woman with long silver hair and red eyes, looking at the viewer, "
       "soft cinematic lighting, cherry blossoms in the background, highly detailed, high quality.")
NEG = "worst quality, low quality, blurry, watermark, text"

def wf(shift=None, steps=30, cfg=4.0, sampler="euler", sched="simple", w=1024, h=1024):
    n = {}
    n["1"] = {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "NetaYumev35_pretrained_all_in_one.safetensors"}}
    model = ["1", 0]
    if shift is not None:
        n["2"] = {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": shift}}
        model = ["2", 0]
    n["3"] = {"class_type": "CLIPTextEncode", "inputs": {"text": POS, "clip": ["1", 1]}}
    n["4"] = {"class_type": "CLIPTextEncode", "inputs": {"text": NEG, "clip": ["1", 1]}}
    n["5"] = {"class_type": "EmptyLatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}}
    n["6"] = {"class_type": "KSampler", "inputs": {"model": model, "seed": 12345, "steps": steps, "cfg": cfg,
        "sampler_name": sampler, "scheduler": sched, "positive": ["3", 0], "negative": ["4", 0],
        "latent_image": ["5", 0], "denoise": 1.0}}
    n["7"] = {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["1", 2]}}
    n["8"] = {"class_type": "SaveImage", "inputs": {"images": ["7", 0], "filename_prefix": "netaprobe"}}
    return n

CONFIGS = [
    ("cfg25_euler", dict(shift=None, cfg=2.5)),
    ("cfg15_euler", dict(shift=None, cfg=1.5)),
    ("auraflow6_cfg25", dict(shift=6.0, cfg=2.5)),
    ("dpm2m_cfg35", dict(shift=None, cfg=3.5, sampler="dpmpp_2m", sched="karras")),
]
for name, kw in CONFIGS:
    t0 = time.time()
    try:
        pid, job = c.queue_prompt(wf(**kw))
    except WorkflowError as e:
        print(name, "VALIDATE FAIL", e); continue
    hist = None
    dl = time.time() + 300
    while time.time() < dl:
        time.sleep(1.5)
        hist = c.get_history(pid)
        if hist and hist.get("outputs"):
            break
    files = []
    for no in (hist or {}).get("outputs", {}).values():
        for im in no.get("images", []) or []:
            d = c.get_image(im)
            fn = os.path.join(OUT, name + ".png")
            open(fn, "wb").write(d)
            files.append(fn)
    print(name, "%.1fs" % (time.time()-t0), files)
print("PROBE DONE")
