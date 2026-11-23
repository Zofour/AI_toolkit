# -*- coding: utf-8 -*-
import json, struct, os
SD = r"C:\Users\yourname\Desktop\else\SD-WEBUI-AKI-V5.0\sd-webui-aki-v4.10\models\Stable-diffusion"
DOC = r"C:\Users\yourname\Documents\ComfyUI\models\checkpoints"
FILES = [
    os.path.join(SD, "HD-20-non-ema-fp32.safetensors"),
    os.path.join(SD, "cosfMix-v2.safetensors"),
    os.path.join(SD, "dreamlike-diffusion-1.0.safetensors"),
    os.path.join(SD, "sd1.5", "anything-v5.safetensors"),
    os.path.join(DOC, "NetaYumev35_pretrained_all_in_one.safetensors"),
]
def hdr(path):
    with open(path, "rb") as f:
        n = struct.unpack("<Q", f.read(8))[0]
        return json.loads(f.read(n))
for p in FILES:
    name = os.path.basename(p)
    h = hdr(p)
    keys = list(h.keys())
    toks = ["conditioner.embedders.1", "conditioner.embedders.0",
            "cond_stage_model.", "text_model", "open_clip", "input_blocks.0.0.weight",
            "double_blocks", "label_emb"]
    counts = {t: sum(1 for k in keys if t in k) for t in toks}
    # 找 input_blocks 的准确键名
    ib = [k for k in keys if k.endswith("input_blocks.0.0.weight")]
    print(f"--- {name} keys={len(keys)}")
    print("   tokens:", counts)
    print("   input_blocks.0.0 key:", ib[:1], "shape:", h[ib[0]]['shape'] if ib else None)
    print("   sample:", keys[:4])
