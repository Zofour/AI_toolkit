# -*- coding: utf-8 -*-
r"""
提示词生图工作台  Prompt Studio  ·  本机 ComfyUI 版
====================================================
功能
  1. 导入 {prompt}{prompt}... 格式的文本文件，自动切割成一条条独立提示词
  2. 选择本机模型（文生图 / 图生图），点列表里任意一条提示词即可生成
  3. 可设置一次生成的张数（1~20）
  4. **严格单模型驻留显存**：换模型前先 POST /free 卸载全部权重，任何时刻显存里只有一个模型
  5. 图生图只在「支持图生图」的模型上可用，输入图片视为主人公形象，
     系统提示词自动告诉模型「这张图是主人公」，保持人物一致性

用法
  双击 run.bat  （或 python app.py）
  自检：python app.py --selftest
"""
import configparser  # noqa: F401  (保证打包环境一致)
import json
import os
import random
import re
import subprocess
import sys
import threading
import time
import traceback
from queue import Queue, Empty

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
ERROR_LOG = os.path.join(APP_DIR, "app_error.log")

COMFY_BASE = "http://127.0.0.1:8000"
COMFY_START_BAT = r"C:\chatbox_temp\ai_toolkit\comfyui_start.bat"
GEN_STUDIO_DIR = r"C:\chatbox_temp\ai-gen-studio"

sys.path.insert(0, GEN_STUDIO_DIR)
try:
    from comfy import ComfyClient, build_workflow, WorkflowError  # noqa: E402
except Exception as _e:  # pragma: no cover
    _msg = "无法导入 ai-gen-studio/comfy.py：%s" % _e
    try:
        with open(ERROR_LOG, "a", encoding="utf-8") as _f:
            _f.write(time.strftime("\n===== %Y-%m-%d %H:%M:%S =====\n") + _msg + "\n"
                     + traceback.format_exc())
    except Exception:
        pass
    try:
        import tkinter as _tk
        import tkinter.messagebox as _mb
        _r = _tk.Tk()
        _r.withdraw()
        _mb.showerror("启动失败", _msg)
        _r.destroy()
    except Exception:
        pass
    raise SystemExit(_msg)

DEFAULT_OUT = r"D:\image_temp\prompt_studio"

NEG_BASE = ("worst quality, low quality, blurry, jpeg artifacts, watermark, text, signature, "
            "deformed, bad anatomy, extra fingers, extra limbs, lowres")

# 图生图的「系统提示词」：告诉模型这张图是主人公形象
DEFAULT_CHAR_SYS = (
    "The reference image is the main character (the protagonist) of this picture. "
    "Keep the same character identity: identical face, facial features, hairstyle, hair color, "
    "eye color, body type and signature outfit. Do not change who this person is. "
    "Only change pose, expression, camera angle, background, lighting and art style as described below."
)

# ------------------------------------------------------------------ 模型目录
# arch: checkpoint | z_image | anima ；style: tags(逗号标签) | sent(自然语言句)
MODEL_CATALOG = {
    "zetaturbo": dict(label="Z-Image Turbo", arch="z_image", style="sent",
                      unet="z_image_turbo_bf16.safetensors", clip="qwen_3_4b.safetensors",
                      vae="ae.safetensors",
                      defaults=dict(width=1024, height=1024, steps=8, cfg=1.0,
                                    sampler="res_multistep", scheduler="simple"),
                      note="8 步极快，写实/静物/风景最强；万能默认"),
    "anima": dict(label="Anima base v1.0", arch="anima", style="sent",
                  unet="anima-base-v1.0.safetensors", clip="qwen_3_06b_base.safetensors",
                  vae="qwen_image_vae.safetensors",
                  defaults=dict(width=1024, height=1024, steps=30, cfg=4.0,
                                sampler="euler", scheduler="simple"),
                  note="画质与指令遵从最强，速度慢（~30s/张）"),
    "cosfmix": dict(label="cosfMix-v2 (SD1.5 全能)", arch="checkpoint", style="tags",
                    ckpt="cosfMix-v2.safetensors",
                    defaults=dict(width=512, height=512, steps=25, cfg=7.0,
                                  sampler="dpmpp_2m", scheduler="karras"),
                    note="SD1.5 全能：动漫人物 + 写实风景 + 静物"),
    "anythingv5": dict(label="anything-v5 (日系动漫)", arch="checkpoint", style="tags",
                       ckpt=r"sd1.5\anything-v5.safetensors",
                       defaults=dict(width=512, height=512, steps=25, cfg=7.0,
                                     sampler="dpmpp_2m", scheduler="karras"),
                       note="纯正日系动漫人物，写实偏弱"),
    "ekmix": dict(label="Ekmix-gen3 (2.5D 角色)", arch="checkpoint", style="tags",
                  ckpt="Ekmix-gen3.ckpt",
                  defaults=dict(width=512, height=512, steps=25, cfg=7.0,
                                sampler="dpmpp_2m", scheduler="karras"),
                  note="日系动漫 / 2.5D 角色强，含 EMA 副本加载稍慢"),
    "netayume": dict(label="NetaYume v35 (梦幻二次元)", arch="checkpoint", style="sent",
                     ckpt="NetaYumev35_pretrained_all_in_one.safetensors",
                     defaults=dict(width=1024, height=1024, steps=30, cfg=2.2,
                                   sampler="euler", scheduler="simple"),
                     note="柔光梦幻粉彩二次元；cfg 必须 1.5~2.5"),
    "dreamlike": dict(label="dreamlike-diffusion-1.0 (油画)", arch="checkpoint", style="tags",
                      ckpt="dreamlike-diffusion-1.0.safetensors",
                      defaults=dict(width=512, height=512, steps=25, cfg=7.0,
                                    sampler="dpmpp_2m", scheduler="karras"),
                      note="油画 / 艺术化插画风"),
    "hd20": dict(label="HD-20-non-ema-fp32 (清新动漫)", arch="checkpoint", style="tags",
                 ckpt="HD-20-non-ema-fp32.safetensors",
                 defaults=dict(width=512, height=512, steps=25, cfg=7.0,
                               sampler="dpmpp_2m", scheduler="karras"),
                 note="清新动漫人物；多物体容易丢"),
}

# 图生图能力矩阵（架构级）：checkpoint 自带 VAE；unet 类需要对应的 VAE 文件存在
ARCH_IMG2IMG = {"checkpoint": True, "z_image": True, "anima": True}


def _norm(s):
    return str(s or "").replace("\\", "/").strip().lower()


def _enum_has(enum, name):
    if not name:
        return False
    tgt = _norm(name)
    base = os.path.basename(tgt)
    for e in enum or []:
        ne = _norm(e)
        if ne == tgt or ne.endswith("/" + tgt) or os.path.basename(ne) == base:
            return True
    return False


def _enum_find(enum, name):
    """在枚举里找到真实的名字（保持 ComfyUI 的目录分隔风格）"""
    tgt = _norm(name)
    base = os.path.basename(tgt)
    for e in enum or []:
        ne = _norm(e)
        if ne == tgt or ne.endswith("/" + tgt) or os.path.basename(ne) == base:
            return e
    return None


# ------------------------------------------------------------------ 提示词切割
BRACE_LINE_PREFIX = re.compile(r"^\s*\d+\s*[\.、\)．]\s*")


def _clean_prompt(txt):
    t = re.sub(r"[ \t\r\n]+", " ", str(txt or "")).strip()
    t = BRACE_LINE_PREFIX.sub("", t)
    return t.strip()


def split_prompts(text):
    """把文本切成提示词列表。

    优先按花括号切（{...}，支持嵌套与跨行）；
    若一个花括号都没有，退化为按行切（忽略空行与 # 开头的注释行）。
    """
    text = str(text or "")
    out = []
    depth = 0
    buf = []
    for ch in text:
        if ch == "{":
            depth += 1
            if depth == 1:
                buf = []
                continue
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0:
                    out.append("".join(buf))
                    continue
        if depth >= 1:
            buf.append(ch)
    items = [_clean_prompt(x) for x in out]
    items = [x for x in items if x]
    if not items:
        for line in text.splitlines():
            s = _clean_prompt(line)
            if s and not s.startswith("#"):
                items.append(s)
    return items


def read_text_auto(path):
    for enc in ("utf-8-sig", "utf-8", "gbk", "cp936", "big5"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
        except Exception:
            break
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


# ------------------------------------------------------------------ 模型清单
def fetch_models(client, log=None):
    """从 ComfyUI 读取真实可选模型，结合能力目录生成模型清单"""
    log = log or (lambda *_: None)
    ckpts = client.loader_enum("CheckpointLoaderSimple", "ckpt_name")
    unets = client.loader_enum("UNETLoader", "unet_name")
    vaes = client.loader_enum("VAELoader", "vae_name")
    clips = client.loader_enum("CLIPLoader", "clip_name")
    log("ComfyUI 枚举: ckpt=%d unet=%d vae=%d clip=%d" % (len(ckpts), len(unets), len(vaes), len(clips)))

    models = []
    used_ckpt = set()

    for key, m in MODEL_CATALOG.items():
        if m["arch"] == "checkpoint":
            real = _enum_find(ckpts, m["ckpt"])
            if not real:
                log("跳过 %s：找不到 %s" % (key, m["ckpt"]))
                continue
            used_ckpt.add(_norm(real))
            mm = dict(m)
            mm.update(key=key, ckpt=real)
        else:
            ru = _enum_find(unets, m["unet"])
            rc = _enum_find(clips, m["clip"])
            rv = _enum_find(vaes, m["vae"])
            if not (ru and rc and rv):
                log("跳过 %s：unet/clip/vae 不齐（%s/%s/%s）" % (key, bool(ru), bool(rc), bool(rv)))
                continue
            mm = dict(m)
            mm.update(key=key, unet=ru, clip=rc, vae=rv)
        ok = ARCH_IMG2IMG.get(mm["arch"], False)
        if mm["arch"] in ("z_image", "anima"):
            ok = ok and _enum_has(vaes, mm["vae"])
        mm["img2img"] = bool(ok)
        mm["builtin"] = True
        models.append(mm)

    # 额外发现的其他 checkpoint → 通用条目（架构同为 SD 系，支持文生图 + 图生图）
    for c in ckpts:
        if _norm(c) in used_ckpt:
            continue
        name = os.path.basename(c).rsplit(".", 1)[0]
        is_xl = ("xl" in _norm(c)) or ("sd3" in _norm(c))
        models.append(dict(
            key="ckpt:" + _norm(c), label=name, arch="checkpoint", style="sent" if is_xl else "tags",
            ckpt=c,
            defaults=dict(width=1024 if is_xl else 512, height=1024 if is_xl else 512,
                          steps=28 if is_xl else 25, cfg=6.5 if is_xl else 7.0,
                          sampler="dpmpp_2m", scheduler="karras"),
            img2img=True, builtin=False,
            note="自动发现的本机 checkpoint（参数为通用默认值，可按需调）"))

    skip = [u for u in unets if not any(m.get("unet") == u for m in models)]
    if skip:
        log("未列出的 UNET（架构未知，暂不提供）: %s" % ", ".join(skip[:6]))
    return models


# ------------------------------------------------------------------ 推理引擎
class Engine:
    """负责 ComfyUI 连接、显存互斥、单次/批量出图"""

    def __init__(self, base=COMFY_BASE):
        self.client = ComfyClient(base)
        self.loaded = None      # 当前驻留显存的模型 key
        self.lock = threading.Lock()
        self._file_seq = 0      # 文件名自增，避免同秒覆盖

    def ping(self):
        return self.client.ping()

    def ensure_online(self, wait=210, log=None):
        log = log or (lambda *_: None)
        ok, info = self.ping()
        if ok:
            return True, info
        log("ComfyUI 未运行，正在后台启动（首次约 20~60 秒）…")
        try:
            subprocess.Popen(["cmd", "/c", COMFY_START_BAT],
                             creationflags=0x08000000,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            return False, {"error": "启动失败: %s" % e}
        t0 = time.time()
        while time.time() - t0 < wait:
            time.sleep(3)
            ok, info = self.ping()
            if ok:
                log("ComfyUI 已就绪：%s / %s" % (info.get("version"), info.get("device")))
                return True, info
        return False, {"error": "ComfyUI 启动超时"}

    def free_vram(self):
        """卸载 ComfyUI 里所有模型权重，保证显存不叠加"""
        try:
            self.client._post("/free", {"unload_models": True, "free_memory": True}, timeout=40)
        except Exception:
            pass
        time.sleep(2.0)
        self.loaded = None

    def ensure_model(self, model, log=None):
        """换模型前先卸载：任何时刻显存里最多只有一个模型"""
        log = log or (lambda *_: None)
        with self.lock:
            if self.loaded == model["key"]:
                return
            if self.loaded:
                log("切换模型：先卸载显存中的「%s」" % self.loaded)
            else:
                log("清空显存后再载入「%s」" % model["label"])
            self.free_vram()
            self.loaded = model["key"]

    # ---------------- 输入图（主人公形象）
    def prepare_input_image(self, path):
        from PIL import Image
        img = Image.open(path).convert("RGB")
        w, h = img.size
        m = max(w, h)
        if m > 1024:
            k = 1024.0 / m
            img = img.resize((max(8, int(w * k)), max(8, int(h * k))), Image.LANCZOS)
        tmpdir = os.path.join(APP_DIR, "输入图")
        os.makedirs(tmpdir, exist_ok=True)
        dst = os.path.join(tmpdir, "ref_%dx%d.png" % img.size)
        img.save(dst, "PNG")
        with open(dst, "rb") as f:
            data = f.read()
        r = self.client.upload_image("ps_ref_%d.png" % int(time.time() * 1000), data)
        name = r.get("name") or os.path.basename(dst)
        sub = r.get("subfolder") or ""
        return (sub.replace("\\", "/") + "/" + name) if sub else name

    # ---------------- 组装 spec
    def build_spec(self, model, prompt, params, seed, src=None, denoise=1.0, loras=None):
        d = dict(model.get("defaults") or {})
        spec = dict(model_type=model["arch"], prompt=prompt, negative=params.get("negative", NEG_BASE),
                    seed=int(seed), batch=1,
                    width=int(params.get("width", d.get("width", 512))),
                    height=int(params.get("height", d.get("height", 512))),
                    steps=int(params.get("steps", d.get("steps", 25))),
                    cfg=float(params.get("cfg", d.get("cfg", 7.0))),
                    sampler=params.get("sampler") or d.get("sampler", "euler"),
                    scheduler=params.get("scheduler") or d.get("scheduler", "normal"),
                    denoise=float(denoise))
        if model["arch"] == "checkpoint":
            spec["ckpt"] = model["ckpt"]
        else:
            spec.update(unet=model["unet"], clip=model["clip"], vae=model["vae"])
        if src:
            spec["input_image"] = src
        if loras:
            spec["loras"] = list(loras)
        return spec

    def _wait(self, pid, timeout=900, stop=None, on_tick=None):
        c = self.client
        t0 = time.time()
        while time.time() - t0 < timeout:
            if stop is not None and stop.is_set():
                try:
                    c._post("/interrupt", {}, timeout=10)
                except Exception:
                    pass
                return None, "已取消"
            time.sleep(1.0)
            h = c.get_history(pid)
            if h:
                st = (h.get("status") or {}).get("status_str")
                if h.get("outputs"):
                    return h, None
                if st == "error":
                    return None, "执行出错: %s" % str((h.get("status") or {}).get("messages"))[:300]
            if on_tick:
                on_tick(int(time.time() - t0))
        return None, "超时（>%ds）" % timeout

    def _gen(self, model, prompt, n, params, src, denoise, char_sys, use_char_sys,
             stop=None, log=None, progress=None, base=0, total=None, loras=None):
        """单条提示词出 n 张（不负责模型载入/图片上传，由上层统一做）"""
        log = log or (lambda *_: None)
        progress = progress or (lambda *a, **k: None)
        total = total or max(1, int(n))
        c = self.client

        pos = prompt
        if src and use_char_sys and char_sys.strip():
            pos = char_sys.strip() + " " + prompt

        out_dir = params.get("out_dir") or DEFAULT_OUT
        os.makedirs(out_dir, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        seed_fixed = int(params.get("seed", -1))
        base_seed = seed_fixed if seed_fixed >= 0 else random.randint(1, 2 ** 31 - 1)
        files = []
        for i in range(max(1, int(n))):
            if stop is not None and stop.is_set():
                log("已取消剩余 %d 张" % (n - i))
                break
            seed = base_seed + i if seed_fixed >= 0 else random.randint(1, 2 ** 31 - 1)
            spec = self.build_spec(model, pos, params, seed, src, denoise, loras=loras)
            progress(base + i, total, "提交第 %d/%d 张（seed=%d）" % (i + 1, n, seed))
            wf = build_workflow(spec)
            pid, job = c.queue_prompt(wf)
            hist, err = self._wait(pid, timeout=900, stop=stop)
            if err:
                if "取消" in err:
                    break
                raise RuntimeError(err)
            got = 0
            for node_out in (hist.get("outputs") or {}).values():
                for im in node_out.get("images", []) or []:
                    data = c.get_image(im)
                    self._file_seq += 1
                    fn = os.path.join(out_dir, "%s_%s_%03d.png" % (
                        model["key"].replace(":", "_"), ts, self._file_seq))
                    with open(fn, "wb") as f:
                        f.write(data)
                    files.append(fn)
                    got += 1
            if got == 0:
                raise RuntimeError("没有拿到图片输出")
            self._write_history(out_dir, model, prompt, pos, seed, params,
                                src and params.get("_image_path"), denoise, files[-got:])
            progress(base + i + 1, total, "完成 %d/%d" % (i + 1, n))
        return files

    def generate(self, model, prompt, n, params, image_path=None, denoise=0.6,
                 char_sys="", use_char_sys=True, stop=None, log=None, progress=None,
                 loras=None):
        """单条提示词生成 n 张，返回文件路径列表。同一次调用里模型只载入一次。"""
        log = log or (lambda *_: None)
        progress = progress or (lambda *a, **k: None)
        ok, info = self.ping()
        if not ok:
            raise RuntimeError("ComfyUI 未连接：%s" % info.get("error"))
        self.ensure_model(model, log)
        src = None
        if image_path:
            params = dict(params, _image_path=image_path)
            src = self.prepare_input_image(image_path)
            log("已上传主人公形象图：%s" % os.path.basename(image_path))
        return self._gen(model, prompt, n, params, src,
                         denoise if src else 1.0, char_sys, use_char_sys,
                         stop=stop, log=log, progress=progress,
                         base=0, total=max(1, int(n)), loras=loras)

    def generate_batch(self, model, items, n, params, image_path=None, denoise=0.6,
                       char_sys="", use_char_sys=True, stop=None, log=None,
                       progress=None, on_item=None, loras=None):
        """批量：按 items 顺序逐条提示词生成，一条生成完再下一条。
        items: [(列表下标, 提示词文本), ...]；模型只载入一次，参考图只上传一次。
        """
        log = log or (lambda *_: None)
        progress = progress or (lambda *a, **k: None)
        on_item = on_item or (lambda *_: None)
        ok, info = self.ping()
        if not ok:
            raise RuntimeError("ComfyUI 未连接：%s" % info.get("error"))
        self.ensure_model(model, log)
        src = None
        if image_path:
            params = dict(params, _image_path=image_path)
            src = self.prepare_input_image(image_path)
            log("已上传主人公形象图：%s（本次批量重用）" % os.path.basename(image_path))

        total_items = len(items)
        total_imgs = total_items * max(1, int(n))
        all_files = []
        log("批量开始：%d 条 × %d 张 = %d 张，模型「%s」" % (total_items, n, total_imgs, model["label"]))
        for k, (idx, txt) in enumerate(items):
            if stop is not None and stop.is_set():
                log("批量已取消，跳过剩余 %d 条" % (total_items - k))
                break
            on_item(idx, k + 1, total_items)
            log("【%d/%d】%s" % (k + 1, total_items, txt[:80]))
            got = self._gen(model, txt, n, params, src, denoise if src else 1.0,
                            char_sys, use_char_sys, stop=stop, log=log,
                            progress=progress, base=k * max(1, int(n)), total=total_imgs,
                            loras=loras)
            all_files.extend(got)
        on_item(None, 0, total_items)
        log("批量结束：共出图 %d 张" % len(all_files))
        return all_files

    @staticmethod
    def _write_history(out_dir, model, prompt, full_prompt, seed, params, image_path, denoise, files):
        rec = dict(time=time.strftime("%Y-%m-%d %H:%M:%S"), model=model["key"],
                   model_label=model.get("label"), prompt=prompt, full_prompt=full_prompt,
                   seed=seed, width=params.get("width"), height=params.get("height"),
                   steps=params.get("steps"), cfg=params.get("cfg"),
                   img2img=bool(image_path), ref_image=image_path, denoise=denoise, files=files)
        try:
            with open(os.path.join(out_dir, "生成记录.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            pass


# ================================================================== GUI
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("提示词生图工作台 · Prompt Studio")
        self.geometry("1700x1120")
        self.minsize(1200, 800)

        self.cfg = self._load_cfg()
        self.engine = Engine()
        self.models = []
        self.model_by_label = {}
        self.prompts = []          # [{'text': 原文, 'edit': 当前编辑值}]
        self.view_idx = []         # 列表里显示的下标（过滤后）
        self.cur_idx = None
        self.src_image = None
        self.thumb_ref = None
        self.mounted_loras = []    # [{'name': ComfyUI 里的 lora 路径, 'strength': 0.8}]
        self.lora_avail = []       # ComfyUI 当前可用 LoRA
        self.lora_store = self._load_lora_store()
        self.lora_on = bool(self.lora_store.get("enabled", True))
        for it in (self.lora_store.get("mounted") or []):
            self.mounted_loras.append(dict(name=it.get("name", ""), strength=float(it.get("strength", 0.8))))
        self.dlg_lora = None
        self.results = []
        self.photo_refs = []
        self.ui_q = Queue()
        self.worker = None
        self.stop_flag = threading.Event()
        self.busy = False
        self.tick_t0 = None

        self._style()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(120, self._poll)
        self.after(300, self._boot)

    # ---------------- 基础
    def _style(self):
        # 优先用 Windows 原生主题：勾选框是清晰的 ✓，clam 主题的勾选记号像粗 ×，容易误判
        st = ttk.Style()
        for th in ("vista", "winnative", "clam"):
            try:
                st.theme_use(th)
                break
            except Exception:
                continue
        st.configure("Accent.TButton", font=("Microsoft YaHei UI", 11, "bold"), padding=(14, 8))
        st.configure("TButton", font=("Microsoft YaHei UI", 9), padding=(8, 4))
        st.configure("TLabel", font=("Microsoft YaHei UI", 9))
        st.configure("TLabelframe.Label", font=("Microsoft YaHei UI", 10, "bold"))
        st.configure("Hint.TLabel", foreground="#666")
        st.configure("Ok.TLabel", foreground="#1a7f37")
        st.configure("Bad.TLabel", foreground="#b42318")
        self.option_add("*Font", ("Microsoft YaHei UI", 9))

    def _load_cfg(self):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_cfg(self):
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ---------------- UI
    def _build_ui(self):
        top = ttk.Frame(self, padding=(10, 8, 10, 4))
        top.pack(side="top", fill="x")
        ttk.Label(top, text="模型：").pack(side="left")
        self.cmb_model = ttk.Combobox(top, state="readonly", width=46, font=("Microsoft YaHei UI", 9))
        self.cmb_model.pack(side="left")
        self.cmb_model.bind("<<ComboboxSelected>>", lambda e: self._on_model_change())
        ttk.Button(top, text="刷新模型", command=self.refresh_models).pack(side="left", padx=6)
        self.lbl_cap = ttk.Label(top, text="", style="Hint.TLabel")
        self.lbl_cap.pack(side="left", padx=8)

        ttk.Button(top, text="卸载显存", command=self._manual_free).pack(side="right", padx=4)
        self.lbl_comfy = ttk.Label(top, text="ComfyUI：检测中…", style="Hint.TLabel")
        self.lbl_comfy.pack(side="right", padx=8)

        body = ttk.PanedWindow(self, orient="horizontal")
        body.pack(side="top", fill="both", expand=True, padx=10, pady=4)

        # ---- 左：提示词列表
        left = ttk.Frame(body)
        body.add(left, weight=1)

        bar1 = ttk.Frame(left)
        bar1.pack(fill="x", pady=(0, 4))
        ttk.Button(bar1, text="导入文本文档…", command=self.import_file).pack(side="left")
        ttk.Button(bar1, text="全选", command=self.select_all).pack(side="left", padx=(4, 2))
        ttk.Button(bar1, text="全不选", command=self.select_none).pack(side="left")
        ttk.Button(bar1, text="清空", command=self.clear_prompts).pack(side="left", padx=4)
        self.lbl_count = ttk.Label(bar1, text="共 0 条", style="Hint.TLabel")
        self.lbl_count.pack(side="right")

        bar2 = ttk.Frame(left)
        bar2.pack(fill="x", pady=(0, 4))
        ttk.Label(bar2, text="过滤：").pack(side="left")
        self.var_filter = tk.StringVar()
        self.var_filter.trace_add("write", lambda *a: self._render_list())
        ttk.Entry(bar2, textvariable=self.var_filter).pack(side="left", fill="x", expand=True)

        box = ttk.Frame(left)
        box.pack(fill="both", expand=True)
        sb = ttk.Scrollbar(box, orient="vertical")
        self.listbox = tk.Listbox(box, activestyle="none", exportselection=False,
                                  selectmode="extended",
                                  font=("Consolas", 9), selectbackground="#cfe3ff",
                                  selectforeground="#000",
                                  yscrollcommand=sb.set, borderwidth=1, relief="solid",
                                  highlightthickness=0, height=30)
        sb.config(command=self.listbox.yview)
        sb.pack(side="right", fill="y")
        self.listbox.pack(side="left", fill="both", expand=True)
        self.listbox.bind("<<ListboxSelect>>", self._on_select)

        self.lbl_src = ttk.Label(left, text="未导入文件", style="Hint.TLabel", wraplength=340,
                                 justify="left")
        self.lbl_src.pack(fill="x", pady=(4, 0))

        # ---- 右：参数 + 结果
        right = ttk.Frame(body)
        body.add(right, weight=3)

        # 提示词编辑
        pf = ttk.LabelFrame(right, text="提示词（可直接输入 / 修改，也可从左侧选）", padding=6)
        pf.pack(fill="x")
        pfbar = ttk.Frame(pf)
        pfbar.pack(fill="x", pady=(0, 4))
        ttk.Button(pfbar, text="新建提示词（自由输入）", command=self.new_prompt).pack(side="left")
        ttk.Button(pfbar, text="加入左侧列表", command=self.add_prompt_to_list).pack(side="left", padx=4)
        ttk.Button(pfbar, text="清空输入", command=self.clear_input).pack(side="left")
        self.lbl_mode = ttk.Label(pfbar, text="← 不选任何条目时，这个框就是自由输入区", style="Hint.TLabel")
        self.lbl_mode.pack(side="left", padx=8)
        self.txt_prompt = tk.Text(pf, height=6, wrap="word", font=("Microsoft YaHei UI", 9),
                                  borderwidth=1, relief="solid")
        self.txt_prompt.pack(fill="x")

        # 参数
        pg = ttk.LabelFrame(right, text="生成参数", padding=6)
        pg.pack(fill="x", pady=(6, 0))
        r1 = ttk.Frame(pg)
        r1.pack(fill="x")
        ttk.Label(r1, text="张数").pack(side="left")
        self.var_n = tk.IntVar(value=1)
        tk.Spinbox(r1, from_=1, to=20, width=4, textvariable=self.var_n).pack(side="left", padx=(2, 12))
        ttk.Label(r1, text="宽").pack(side="left")
        self.var_w = tk.IntVar(value=1024)
        tk.Spinbox(r1, from_=256, to=2048, increment=64, width=6, textvariable=self.var_w).pack(side="left", padx=(2, 8))
        ttk.Label(r1, text="高").pack(side="left")
        self.var_h = tk.IntVar(value=1024)
        tk.Spinbox(r1, from_=256, to=2048, increment=64, width=6, textvariable=self.var_h).pack(side="left", padx=(2, 12))
        ttk.Label(r1, text="步数").pack(side="left")
        self.var_steps = tk.IntVar(value=8)
        tk.Spinbox(r1, from_=1, to=80, width=5, textvariable=self.var_steps).pack(side="left", padx=(2, 12))
        ttk.Label(r1, text="CFG").pack(side="left")
        self.var_cfg = tk.DoubleVar(value=1.0)
        tk.Spinbox(r1, from_=0.5, to=20, increment=0.5, width=5, textvariable=self.var_cfg).pack(side="left", padx=(2, 12))
        ttk.Label(r1, text="种子(-1=随机)").pack(side="left")
        self.var_seed = tk.IntVar(value=-1)
        tk.Spinbox(r1, from_=-1, to=2 ** 31, width=12, textvariable=self.var_seed).pack(side="left", padx=(2, 0))

        r1b = ttk.Frame(pg)
        r1b.pack(fill="x", pady=(4, 0))
        ttk.Label(r1b, text="LoRA").pack(side="left")
        self.lbl_lora = ttk.Label(r1b, text="未挂载", style="Hint.TLabel")
        self.lbl_lora.pack(side="left", padx=(6, 8))
        ttk.Button(r1b, text="LoRA 挂载…", command=self.open_lora_dialog).pack(side="left")
        self.btn_lora_off = ttk.Button(r1b, text="停止挂载", command=self.stop_loras)
        self.btn_lora_off.pack(side="left", padx=6)
        # 图生图
        self.lf_i2i = ttk.LabelFrame(right, text="图生图 · 主人公形象", padding=6)
        self.lf_i2i.pack(fill="x", pady=(6, 0))
        r2 = ttk.Frame(self.lf_i2i)
        r2.pack(fill="x")
        self.var_i2i = tk.BooleanVar(value=False)
        self.chk_i2i = ttk.Checkbutton(r2, text="启用图生图", variable=self.var_i2i,
                                       command=self._on_i2i_toggle)
        self.chk_i2i.pack(side="left")
        self.btn_pick = ttk.Button(r2, text="选择主人公图片…", command=self.pick_image)
        self.btn_pick.pack(side="left", padx=6)
        self.lbl_img = ttk.Label(r2, text="（未选择图片）", style="Hint.TLabel")
        self.lbl_img.pack(side="left", padx=4)
        ttk.Label(r2, text="重绘强度").pack(side="left", padx=(12, 2))
        self.var_denoise = tk.DoubleVar(value=0.65)
        self.sc_denoise = ttk.Scale(r2, from_=0.15, to=0.95, variable=self.var_denoise,
                                    orient="horizontal", length=130)
        self.sc_denoise.pack(side="left")
        self.lbl_denoise = ttk.Label(r2, text="0.65", width=5)
        self.lbl_denoise.pack(side="left")
        self.var_denoise.trace_add("write", lambda *a: self.lbl_denoise.config(
            text="%.2f" % float(self.var_denoise.get())))

        r3 = ttk.Frame(self.lf_i2i)
        r3.pack(fill="x", pady=(6, 0))
        self.canvas_thumb = tk.Canvas(r3, width=84, height=84, bg="#f2f2f2", highlightthickness=1,
                                      highlightbackground="#cfcfcf")
        self.canvas_thumb.pack(side="left")
        col = ttk.Frame(r3)
        col.pack(side="left", fill="both", expand=True, padx=(8, 0))
        self.var_use_sys = tk.BooleanVar(value=True)
        ttk.Checkbutton(col, text="把「主人公说明」写进正向提示词（系统提示词）",
                        variable=self.var_use_sys).pack(anchor="w")
        self.txt_sys = tk.Text(col, height=4, wrap="word", font=("Microsoft YaHei UI", 8),
                               borderwidth=1, relief="solid")
        self.txt_sys.pack(fill="both", expand=True, pady=(2, 0))
        self.txt_sys.insert("1.0", self.cfg.get("char_sys") or DEFAULT_CHAR_SYS)
        ttk.Label(self.lf_i2i, text="提示：图生图时画布尺寸以输入图为准（自动缩到长边 1024）；重绘强度越低越像原图，0.5~0.7 适合换背景/换姿势，0.75+ 会明显重画人物。",
                  style="Hint.TLabel", wraplength=760, justify="left").pack(fill="x", pady=(4, 0))

        # 操作条
        act = ttk.Frame(right)
        act.pack(fill="x", pady=8)
        self.btn_gen = ttk.Button(act, text="生  成", style="Accent.TButton", command=self.start_generate)
        self.btn_gen.pack(side="left")
        self.btn_batch = ttk.Button(act, text="批量生成所选", command=self.start_batch)
        self.btn_batch.pack(side="left", padx=6)
        self.btn_stop = ttk.Button(act, text="停止", command=self.stop_generate, state="disabled")
        self.btn_stop.pack(side="left", padx=6)
        self.prog = ttk.Progressbar(act, mode="determinate", maximum=100)
        self.prog.pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(act, text="打开输出目录", command=self.open_outdir).pack(side="right")
        ttk.Button(act, text="输出目录…", command=self.choose_outdir).pack(side="right", padx=4)
        self.bind_all("<Control-Return>", lambda e: self.start_generate())
        self.lbl_status = ttk.Label(right, text="就绪：先在左侧「导入文本文档…」，再点一条提示词即可生成",
                                   style="Hint.TLabel", anchor="w")
        self.lbl_status.pack(fill="x", pady=(0, 4))

        # 结果
        rf = ttk.LabelFrame(right, text="生成结果（点缩略图看大图）", padding=4)
        rf.pack(fill="both", expand=True)
        self.res_canvas = tk.Canvas(rf, bg="#fbfbfb", highlightthickness=0, height=190)
        vsb = ttk.Scrollbar(rf, orient="vertical", command=self.res_canvas.yview)
        self.res_canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.res_canvas.pack(side="left", fill="both", expand=True)
        self.res_inner = ttk.Frame(self.res_canvas)
        self.res_canvas.create_window((0, 0), window=self.res_inner, anchor="nw")
        self.res_inner.bind("<Configure>", lambda e: self.res_canvas.configure(
            scrollregion=self.res_canvas.bbox("all")))
        self.res_canvas.bind("<Configure>", lambda e: self._relayout_results())

        self._on_model_change(init=True)
        self._on_i2i_toggle()
        self._update_lora_label()

    # ---------------- 启动
    def _boot(self):
        def run():
            ok, info = self.engine.ensure_online(log=lambda m: self.ui_q.put(("log", m)))
            self.ui_q.put(("comfy", (ok, info)))
            if ok:
                try:
                    ms = fetch_models(self.engine.client, log=lambda m: self.ui_q.put(("log", m)))
                    self.ui_q.put(("models", ms))
                    self.ui_q.put(("loras", self.engine.client.loader_enum("LoraLoader", "lora_name")))
                except Exception as e:
                    self.ui_q.put(("log", "读取模型失败：%s" % e))
        threading.Thread(target=run, daemon=True).start()

    def refresh_models(self):
        def run():
            ok, info = self.engine.ping()
            self.ui_q.put(("comfy", (ok, info)))
            if not ok:
                ok2, info2 = self.engine.ensure_online(log=lambda m: self.ui_q.put(("log", m)))
                self.ui_q.put(("comfy", (ok2, info2)))
                if not ok2:
                    return
            try:
                ms = fetch_models(self.engine.client, log=lambda m: self.ui_q.put(("log", m)))
                self.ui_q.put(("models", ms))
                self.ui_q.put(("loras", self.engine.client.loader_enum("LoraLoader", "lora_name")))
            except Exception as e:
                self.ui_q.put(("log", "读取模型失败：%s" % e))
        threading.Thread(target=run, daemon=True).start()

    # ---------------- 事件轮询
    def _poll(self):
        try:
            while True:
                kind, payload = self.ui_q.get_nowait()
                if kind == "log":
                    self.set_status(payload)
                elif kind == "comfy":
                    ok, info = payload
                    self.lbl_comfy.config(text="ComfyUI：%s" % ("在线" if ok else "离线"),
                                          style="Ok.TLabel" if ok else "Bad.TLabel")
                    if not ok:
                        self.set_status("ComfyUI 未连接：%s" % (info or {}).get("error", ""))
                elif kind == "models":
                    self._apply_models(payload)
                elif kind == "loras":
                    self.lora_avail = list(payload or [])
                    self.set_status("LoRA 清单：%d 个" % len(self.lora_avail))
                    try:
                        if self.dlg_lora is not None and self.dlg_lora.winfo_exists():
                            self.dlg_lora._refresh()
                    except Exception:
                        pass
                elif kind == "progress":
                    done, total, msg = payload
                    self.prog.config(maximum=max(1, total), value=done)
                    self.set_status(msg)
                elif kind == "batch_item":
                    idx, k, tot = payload
                    self._mark_batch(idx)
                    if idx is not None:
                        self.set_status("批量：第 %d/%d 条（列表第 %d 条）" % (k, tot, idx + 1))
                elif kind == "done":
                    files = payload
                    self._on_gen_done(files)
                elif kind == "error":
                    self._on_gen_error(payload)
                elif kind == "tick":
                    if self.tick_t0:
                        self.set_status("生成中… 已用 %ds" % (time.time() - self.tick_t0))
        except Empty:
            pass
        self.after(120, self._poll)

    def set_status(self, msg):
        self.lbl_status.config(text=str(msg)[:300])

    # ---------------- 模型
    def _apply_models(self, models):
        self.models = models
        self.model_by_label = {}
        labels = []
        for m in models:
            cap = "图文" if m.get("img2img") else "仅文"
            short = {"checkpoint": "SD", "z_image": "Z-Img", "anima": "Anima"}.get(m["arch"], m["arch"])
            lb = "%s  [%s·%s]" % (m["label"][:22], short, cap)
            labels.append(lb)
            self.model_by_label[lb] = m
        self.cmb_model["values"] = labels
        if labels:
            want = self.cfg.get("model_label")
            idx = labels.index(want) if want in labels else 0
            self.cmb_model.current(idx)
            self._on_model_change()
        self.set_status("已载入 %d 个模型" % len(models))

    def cur_model(self):
        lb = self.cmb_model.get()
        return self.model_by_label.get(lb)

    def _on_model_change(self, init=False):
        m = self.cur_model()
        if not m:
            return
        d = m.get("defaults") or {}
        self.var_w.set(int(d.get("width", 512)))
        self.var_h.set(int(d.get("height", 512)))
        self.var_steps.set(int(d.get("steps", 25)))
        self.var_cfg.set(float(d.get("cfg", 7.0)))
        if not init:
            self.cfg["model_label"] = self.cmb_model.get()
            self._save_cfg()
        self._refresh_cap()

    def _refresh_cap(self):
        m = self.cur_model()
        if not m:
            return
        if m.get("img2img"):
            self.lbl_cap.config(text="能力：文生图 ✓   图生图 ✓", style="Ok.TLabel")
            for w in (self.chk_i2i, self.btn_pick, self.sc_denoise):
                w.state(["!disabled"])
        else:
            self.lbl_cap.config(text="能力：文生图 ✓   图生图 ✗（该模型不支持）", style="Bad.TLabel")
            self.var_i2i.set(False)
            for w in (self.chk_i2i, self.btn_pick, self.sc_denoise):
                w.state(["disabled"])
        self._on_i2i_toggle()

    def _on_i2i_toggle(self):
        m = self.cur_model()
        usable = bool(m and m.get("img2img")) and bool(self.var_i2i.get())
        st = "normal" if usable else "disabled"
        self.btn_pick.config(state=st)
        self.sc_denoise.state(["!disabled"] if usable else ["disabled"])
        self.txt_sys.config(state="normal" if usable else "disabled")
        if usable and not self.src_image:
            self.set_status("图生图已启用：请选择一张「主人公形象」图片")
        if not usable:
            self.var_i2i.set(False)

    # ---------------- 提示词
    def import_file(self):
        p = filedialog.askopenfilename(
            title="选择提示词汇总文本",
            filetypes=[("文本文件", "*.txt *.md *.text"), ("所有文件", "*.*")])
        if not p:
            return
        try:
            txt = read_text_auto(p)
        except Exception as e:
            messagebox.showerror("读取失败", str(e))
            return
        items = split_prompts(txt)
        if not items:
            messagebox.showwarning("没切出提示词", "文件中没有找到可用提示词。\n支持的格式：{提示词}{提示词}… 或每行一条。")
            return
        self.prompts = [{"text": x, "edit": x} for x in items]
        self.cur_idx = None
        self.cfg["last_file"] = p
        self._save_cfg()
        self.lbl_src.config(text="文件：%s" % p)
        self._render_list()
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(0)
        self.listbox.activate(0)
        self._on_select()
        self.set_status("已导入 %d 条提示词（来自 %s）" % (len(items), os.path.basename(p)))

    def clear_prompts(self):
        if self.prompts and not messagebox.askyesno("确认", "清空当前提示词列表？"):
            return
        self.prompts = []
        self.cur_idx = None
        self.txt_prompt.delete("1.0", "end")
        self._render_list()
        self.lbl_src.config(text="未导入文件")

    def _render_list(self):
        kw = self.var_filter.get().strip().lower()
        self.listbox.delete(0, "end")
        self.view_idx = []
        for i, it in enumerate(self.prompts):
            t = it["text"]
            if kw and kw not in t.lower():
                continue
            self.view_idx.append(i)
            one = re.sub(r"\s+", " ", t)
            self.listbox.insert("end", "%4d  %s" % (i + 1, one[:120] + ("…" if len(one) > 120 else "")))
        self._update_selcount()
        # 恢复选中
        if self.cur_idx is not None and self.cur_idx in self.view_idx:
            pos = self.view_idx.index(self.cur_idx)
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(pos)
            self.listbox.see(pos)

    def _on_select(self, event=None):
        sel = self.listbox.curselection()
        self._update_selcount()
        if not sel:
            return
        pos = sel[0]
        if pos >= len(self.view_idx):
            return
        idx = self.view_idx[pos]
        if self.cur_idx == idx:
            return
        if self.cur_idx is not None and 0 <= self.cur_idx < len(self.prompts):
            self.prompts[self.cur_idx]["edit"] = self.txt_prompt.get("1.0", "end").strip()
        self.cur_idx = idx
        self.txt_prompt.delete("1.0", "end")
        self.txt_prompt.insert("1.0", self.prompts[idx].get("edit") or self.prompts[idx]["text"])
        nsel = len(sel)
        self.set_status("第 %d/%d 条提示词%s" % (idx + 1, len(self.prompts),
                                                ("（已选中 %d 条，可点「批量生成所选」）" % nsel) if nsel > 1 else ""))

    # ---------------- 多选 / 批量
    def selected_idxs(self):
        return [self.view_idx[p] for p in self.listbox.curselection()
                if 0 <= p < len(self.view_idx)]

    def select_all(self):
        if not self.view_idx:
            return
        self.listbox.selection_set(0, "end")
        self._update_selcount()
        self.set_status("已全选 %d 条，点「批量生成所选」按列表顺序逐条生图" % len(self.view_idx))

    def select_none(self):
        self.listbox.selection_clear(0, "end")
        self._update_selcount()

    def _update_selcount(self):
        kw = self.var_filter.get().strip() if hasattr(self, "var_filter") else ""
        txt = "共 %d 条" % len(self.prompts)
        if kw:
            txt += "，筛出 %d 条" % len(self.view_idx)
        n = len(self.selected_idxs()) if hasattr(self, "listbox") else 0
        if n:
            txt += "，已选 %d 条" % n
        self.lbl_count.config(text=txt)

    # ---------------- 自由输入
    def new_prompt(self):
        """取消选中，提示词框变成自由输入区"""
        self.cur_idx = None
        self.listbox.selection_clear(0, "end")
        self.txt_prompt.delete("1.0", "end")
        self.txt_prompt.focus_set()
        self._update_selcount()
        self.lbl_mode.config(text="自由输入中：直接写提示词，点「生 成」（不会改动左侧列表）",
                            style="Ok.TLabel")
        self.set_status("自由输入模式：写任意提示词后点「生 成」")

    def add_prompt_to_list(self):
        txt = self.txt_prompt.get("1.0", "end").strip()
        if not txt:
            messagebox.showinfo("没有内容", "提示词框是空的，先写点东西。")
            return
        self.prompts.append({"text": txt, "edit": txt})
        self.cur_idx = len(self.prompts) - 1
        self._render_list()
        if self.cur_idx in self.view_idx:
            pos = self.view_idx.index(self.cur_idx)
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(pos)
            self.listbox.see(pos)
        self._update_selcount()
        self.lbl_mode.config(text="已存入左侧列表（第 %d 条）" % len(self.prompts), style="Hint.TLabel")
        self.set_status("已加入列表，现共 %d 条" % len(self.prompts))

    def clear_input(self):
        self.cur_idx = None
        self.listbox.selection_clear(0, "end")
        self.txt_prompt.delete("1.0", "end")
        self.txt_prompt.focus_set()
        self._update_selcount()
        self.lbl_mode.config(text="← 不选任何条目时，这个框就是自由输入区", style="Hint.TLabel")
        self.set_status("已清空输入框")

    # ---------------- LoRA 挂载
    def _lora_store_path(self):
        return os.path.join(APP_DIR, "lora_store.json")

    def _load_lora_store(self):
        try:
            with open(self._lora_store_path(), "r", encoding="utf-8") as f:
                return json.load(f) or {}
        except Exception:
            return {}

    def _save_lora_store(self):
        self.lora_store = dict(
            enabled=bool(self.lora_on),
            mounted=[dict(name=x["name"], strength=float(x["strength"])) for x in self.mounted_loras],
            known=self.lora_store.get("known") or [],
            aliases=self.lora_store.get("aliases") or {})
        try:
            with open(self._lora_store_path(), "w", encoding="utf-8") as f:
                json.dump(self.lora_store, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def lora_display(self, name):
        """显示名：有自定义名就用自定义名，否则用文件名"""
        al = (self.lora_store.get("aliases") or {}).get(name)
        return al or os.path.basename(name)

    def set_lora_alias(self, name, alias):
        al = dict(self.lora_store.get("aliases") or {})
        alias = (alias or "").strip()
        if alias and alias != os.path.basename(name):
            al[name] = alias
        else:
            al.pop(name, None)
        self.lora_store["aliases"] = al
        self._save_lora_store()
        self._update_lora_label()

    def _remember_lora(self, name, strength):
        """挂过一次就记住路径，下次直接从下拉里选"""
        known = [k for k in (self.lora_store.get("known") or []) if k.get("name") != name]
        known.insert(0, dict(name=name, strength=float(strength),
                             last=time.strftime("%Y-%m-%d %H:%M")))
        self.lora_store["known"] = known[:50]
        self._save_lora_store()

    def _active_loras(self):
        if not self.lora_on:
            return []
        out = []
        for it in self.mounted_loras:
            s = float(it.get("strength", 0.8))
            out.append(dict(name=it["name"], strength=s, strength_clip=s))
        return out

    def _update_lora_label(self):
        n = len(self.mounted_loras)
        if n == 0:
            txt, sty = "未挂载", "Hint.TLabel"
        elif not self.lora_on:
            txt, sty = "已停止挂载（保留 %d 个）" % n, "Bad.TLabel"
        else:
            names = "、".join(self.lora_display(x["name"])[:18] for x in self.mounted_loras[:3])
            txt, sty = "已挂 %d 个 · 启用中：%s" % (n, names), "Ok.TLabel"
        self.lbl_lora.config(text=txt, style=sty)
        self.btn_lora_off.config(text="停止挂载" if self.lora_on else "恢复挂载")
        self.btn_lora_off.config(state="normal" if n else "disabled")

    def stop_loras(self):
        """一键停止/恢复 LoRA 挂载（列表保留，不删）"""
        if not self.mounted_loras:
            messagebox.showinfo("没有挂载", "当前没有挂载任何 LoRA。点「LoRA 挂载…」添加。")
            return
        self.lora_on = not self.lora_on
        self._save_lora_store()
        self._update_lora_label()
        self.set_status("LoRA 已停止挂载：后续生成不再加载（列表保留）" if not self.lora_on
                        else "LoRA 已恢复挂载：后续生成会重新加载")

    def open_lora_dialog(self):
        if self.dlg_lora is not None:
            try:
                if self.dlg_lora.winfo_exists():
                    self.dlg_lora.lift()
                    self.dlg_lora.focus_set()
                    return
            except Exception:
                pass
        self.dlg_lora = LoraDialog(self)

    # ---------------- 图生图
    def pick_image(self):
        p = filedialog.askopenfilename(title="选择主人公形象图片",
                                       filetypes=[("图片", "*.png *.jpg *.jpeg *.webp *.bmp"),
                                                  ("所有文件", "*.*")])
        if not p:
            return
        self.src_image = p
        self.cfg["ref_image"] = p
        self._save_cfg()
        self.lbl_img.config(text=os.path.basename(p))
        self.var_i2i.set(True)
        self._on_i2i_toggle()
        self._show_thumb(p)
        self.set_status("主人公形象：%s（重绘强度 %.2f）" % (p, float(self.var_denoise.get())))

    def _show_thumb(self, path):
        try:
            from PIL import Image, ImageTk
            im = Image.open(path)
            im.thumbnail((80, 80))
            self.thumb_ref = ImageTk.PhotoImage(im)
            self.canvas_thumb.delete("all")
            self.canvas_thumb.create_image(42, 42, image=self.thumb_ref)
        except Exception:
            pass

    # ---------------- 生成
    def _common_args(self):
        """校验模型/参数/图生图，返回公共参数或 None"""
        m = self.cur_model()
        if not m:
            messagebox.showwarning("没有模型", "请先选择模型（或点「刷新模型」）。")
            return None
        if self.var_i2i.get() and not m.get("img2img"):
            messagebox.showwarning("该模型不支持图生图", "请换一个支持图生图的模型。")
            return None
        img2img = bool(self.var_i2i.get()) and bool(m.get("img2img"))
        if img2img and not self.src_image:
            messagebox.showwarning("缺少图片", "图生图需要先选择主人公形象图片。")
            return None
        try:
            n = max(1, int(self.var_n.get()))
            params = dict(width=int(self.var_w.get()), height=int(self.var_h.get()),
                          steps=int(self.var_steps.get()), cfg=float(self.var_cfg.get()),
                          seed=int(self.var_seed.get()),
                          out_dir=self.cfg.get("out_dir") or DEFAULT_OUT)
        except Exception as e:
            messagebox.showerror("参数有误", str(e))
            return None
        char_sys = self.txt_sys.get("1.0", "end").strip()
        self.cfg["char_sys"] = char_sys
        self._save_cfg()
        return dict(model=m, n=n, params=params,
                    denoise=float(self.var_denoise.get()),
                    use_sys=bool(self.var_use_sys.get()),
                    char_sys=char_sys, img2img=img2img,
                    image_path=self.src_image if img2img else None,
                    loras=self._active_loras())

    def _begin(self, total):
        self.busy = True
        self.stop_flag.clear()
        self.btn_gen.config(state="disabled")
        self.btn_batch.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.prog.config(value=0, maximum=max(1, total))
        self.tick_t0 = time.time()

    def _save_cur_edit(self):
        if self.cur_idx is not None and 0 <= self.cur_idx < len(self.prompts):
            self.prompts[self.cur_idx]["edit"] = self.txt_prompt.get("1.0", "end").strip()

    def _worker(self, fn):
        def run():
            try:
                files = fn()
                self.ui_q.put(("done", files))
            except WorkflowError as e:
                self.ui_q.put(("error", "工作流校验失败：%s" % e))
            except Exception as e:
                self.ui_q.put(("error", "%s\n%s" % (e, traceback.format_exc()[-1200:])))
        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()

    def start_generate(self):
        if self.busy:
            return
        prompt = self.txt_prompt.get("1.0", "end").strip()
        if not prompt:
            messagebox.showwarning("没有提示词", "请在左侧选一条提示词，或直接在提示词框里输入。")
            return
        self._save_cur_edit()
        a = self._common_args()
        if not a:
            return
        self._begin(a["n"])
        self.set_status("开始生成…" if not a["loras"] else
                        "开始生成（LoRA %d 个）…" % len(a["loras"]))
        eng, m = self.engine, a["model"]

        def fn():
            return eng.generate(
                m, prompt, a["n"], a["params"], image_path=a["image_path"], denoise=a["denoise"],
                char_sys=a["char_sys"], use_char_sys=a["use_sys"], stop=self.stop_flag,
                loras=a["loras"],
                log=lambda s: self.ui_q.put(("log", s)),
                progress=lambda d, t, s: self.ui_q.put(("progress", (d, t, s))))
        self._worker(fn)

    def start_batch(self):
        if self.busy:
            return
        self._save_cur_edit()
        idxs = self.selected_idxs()
        if not idxs:
            messagebox.showinfo("先选提示词", "在左侧按住 Ctrl / Shift 多选，或点「全选」。")
            return
        a = self._common_args()
        if not a:
            return
        items = [(i, (self.prompts[i].get("edit") or self.prompts[i]["text"]).strip())
                 for i in sorted(idxs)]
        items = [(i, t) for i, t in items if t]
        if not items:
            messagebox.showwarning("没有内容", "选中的提示词是空的。")
            return
        total = len(items) * a["n"]
        if total > 10 and not messagebox.askyesno(
                "确认批量生成",
                "将按列表顺序逐条生成：\n\n%d 条 × %d 张 = 共 %d 张\n模型：%s\n\n要开始吗？"
                % (len(items), a["n"], total, a["model"]["label"])):
            return
        self._begin(total)
        self.set_status("批量开始：%d 条 × %d 张 = %d 张" % (len(items), a["n"], total))
        eng, m = self.engine, a["model"]

        def fn():
            return eng.generate_batch(
                m, items, a["n"], a["params"], image_path=a["image_path"], denoise=a["denoise"],
                char_sys=a["char_sys"], use_char_sys=a["use_sys"], stop=self.stop_flag,
                loras=a["loras"],
                log=lambda s: self.ui_q.put(("log", s)),
                progress=lambda d, t, s: self.ui_q.put(("progress", (d, t, s))),
                on_item=lambda idx, k, tot: self.ui_q.put(("batch_item", (idx, k, tot))))
        self._worker(fn)

    def stop_generate(self):
        self.stop_flag.set()
        self.set_status("正在停止…（当前这张会被中断）")

    def _on_gen_done(self, files):
        self.busy = False
        self.tick_t0 = None
        self.btn_gen.config(state="normal")
        self.btn_batch.config(state="normal")
        self.btn_stop.config(state="disabled")
        self._mark_batch(None)
        if files:
            for f in files:
                self._add_result(f)
            self.set_status("完成：生成 %d 张，保存在 %s" % (len(files), os.path.dirname(files[0])))
            self.prog.config(value=self.prog["maximum"])
        else:
            self.set_status("已停止，没有新图")

    def _on_gen_error(self, msg):
        self.busy = False
        self.tick_t0 = None
        self.btn_gen.config(state="normal")
        self.btn_batch.config(state="normal")
        self.btn_stop.config(state="disabled")
        self._mark_batch(None)
        self.set_status("出错：" + str(msg).splitlines()[0][:160])
        messagebox.showerror("生成失败", str(msg)[:1500])

    def _manual_free(self):
        def run():
            self.engine.free_vram()
            self.ui_q.put(("log", "已请求 ComfyUI 卸载全部模型，显存已释放"))
        threading.Thread(target=run, daemon=True).start()

    # ---------------- 结果区
    def _mark_batch(self, idx):
        """批量时把当前正在生成的条目高亮"""
        try:
            for pos in range(self.listbox.size()):
                self.listbox.itemconfig(pos, background="", foreground="")
            if idx is not None and idx in self.view_idx:
                pos = self.view_idx.index(idx)
                self.listbox.itemconfig(pos, background="#ffe7a3", foreground="#000")
                self.listbox.see(pos)
        except Exception:
            pass

    def _add_result(self, path):
        from PIL import Image, ImageTk
        try:
            im = Image.open(path)
            im.thumbnail((150, 150))
            ph = ImageTk.PhotoImage(im)
        except Exception:
            return
        self.photo_refs.append(ph)
        card = ttk.Frame(self.res_inner, padding=4, relief="solid", borderwidth=1)
        lb = tk.Label(card, image=ph, cursor="hand2", bg="#ffffff")
        lb.pack()
        ttk.Label(card, text=os.path.basename(path)[-28:], style="Hint.TLabel").pack()
        lb.bind("<Button-1>", lambda e, p=path: os.startfile(p))
        i = len(self.results)
        card.grid(row=i // 5, column=i % 5, padx=6, pady=6, sticky="n")
        self.results.append(path)

    def _relayout_results(self):
        pass

    def open_outdir(self):
        d = self.cfg.get("out_dir") or DEFAULT_OUT
        os.makedirs(d, exist_ok=True)
        os.startfile(d)

    def choose_outdir(self):
        d = filedialog.askdirectory(title="选择输出图片目录",
                                    initialdir=self.cfg.get("out_dir") or DEFAULT_OUT)
        if d:
            self.cfg["out_dir"] = os.path.normpath(d)
            self._save_cfg()
            self.set_status("输出目录：%s" % self.cfg["out_dir"])

    def _on_close(self):
        try:
            self.cfg["char_sys"] = self.txt_sys.get("1.0", "end").strip()
            self._save_cfg()
        except Exception:
            pass
        self.destroy()


# ------------------------------------------------------------------ LoRA 挂载面板
class LoraDialog(tk.Toplevel):
    """挂一次记住路径，下次直接在下拉里选；可随时停止 / 恢复挂载"""

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("LoRA 挂载")
        self.transient(app)
        self.geometry("860x540")
        self.minsize(640, 420)
        self.map = {}
        self._build()
        self._refresh()
        self.var_on.set(bool(app.lora_on))
        self.protocol("WM_DELETE_WINDOW", self._close)
        # 不抓取焦点（非模态）：面板开着也能直接回主窗口点生成
        self.attributes("-topmost", False)

    def _build(self):
        top = ttk.LabelFrame(self, text="① 选择要挂的 LoRA（挂过一次就记进 lora_store.json，下次直接选）", padding=8)
        top.pack(fill="x", padx=10, pady=(10, 4))

        r1 = ttk.Frame(top)
        r1.pack(fill="x")
        r1.columnconfigure(1, weight=1)
        ttk.Label(r1, text="LoRA").grid(row=0, column=0, sticky="w")
        self.cmb = ttk.Combobox(r1, state="readonly", width=34)
        self.cmb.grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Label(r1, text="强度").grid(row=0, column=2, sticky="w")
        self.var_w = tk.DoubleVar(value=0.8)
        tk.Spinbox(r1, from_=0.0, to=2.0, increment=0.05, width=6,
                   textvariable=self.var_w).grid(row=0, column=3, sticky="w", padx=(2, 8))
        # 用 grid 固定列，窗口再窄也不会把「挂载」按钮挤出去
        self.btn_mount = ttk.Button(r1, text="挂 载 →", command=self.add)
        self.btn_mount.grid(row=0, column=4, sticky="e")
        self.cmb.bind("<Return>", lambda e: self.add())

        r2 = ttk.Frame(top)
        r2.pack(fill="x", pady=(6, 0))
        ttk.Button(r2, text="刷新清单", command=self.refresh_avail).pack(side="left")
        ttk.Button(r2, text="手动填路径…", command=self.add_manual).pack(side="left", padx=6)
        ttk.Button(r2, text="改自定义名称…", command=self.rename).pack(side="left")
        ttk.Label(r2, text="SD 系同时作用于 CLIP；Z-Image / Anima 只作用于 UNET",
                  style="Hint.TLabel").pack(side="left", padx=6)

        mid = ttk.LabelFrame(self, text="② 已挂载（按顺序串到模型后面，可挂多个）", padding=8)
        mid.pack(fill="both", expand=True, padx=10, pady=4)
        box = ttk.Frame(mid)
        box.pack(fill="both", expand=True)
        sb = ttk.Scrollbar(box, orient="vertical")
        self.lst = tk.Listbox(box, selectmode="extended", font=("Consolas", 9),
                              yscrollcommand=sb.set, activestyle="none")
        sb.config(command=self.lst.yview)
        sb.pack(side="right", fill="y")
        self.lst.pack(side="left", fill="both", expand=True)
        self.lst.bind("<Double-Button-1>", lambda e: self.remove_sel())

        bar = ttk.Frame(mid)
        bar.pack(fill="x", pady=(6, 0))
        ttk.Button(bar, text="卸下所选", command=self.remove_sel).pack(side="left")
        ttk.Button(bar, text="全部卸下（停止挂载）", command=self.clear_all).pack(side="left", padx=6)
        self.var_on = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="启用 LoRA", variable=self.var_on,
                        command=self.toggle).pack(side="left", padx=8)
        ttk.Button(bar, text="关闭", command=self._close).pack(side="right")

    # ---------- 刷新
    def _refresh(self):
        app = self.app
        avail = list(app.lora_avail or [])
        known = [k.get("name") for k in (app.lora_store.get("known") or []) if k.get("name")]
        items, self.map = [], {}
        for n in avail:
            disp = app.lora_display(n)
            d = ("%s  ←  %s   ✔ 可用" % (disp, n)) if disp != os.path.basename(n) \
                else ("%s   ✔ 可用" % n)
            items.append(d)
            self.map[d] = n
        for n in known:
            if n in avail:
                continue
            disp = app.lora_display(n)
            d = ("%s  ←  %s   ⚠ 文件未找到" % (disp, n)) if disp != os.path.basename(n) \
                else ("%s   ⚠ 文件未找到" % n)
            items.append(d)
            self.map[d] = n
        if not items:
            items = ["（没发现可用 LoRA，点「刷新清单」或「手动填路径…」）"]
        self.cmb["values"] = items
        self.cmb.current(0)
        self._refresh_list()

    def _refresh_list(self):
        self.lst.delete(0, "end")
        app = self.app
        for it in app.mounted_loras:
            base = os.path.basename(it["name"])
            disp = app.lora_display(it["name"])
            if disp != base:
                self.lst.insert("end", "%-30s ( %s ) × %.2f" % (disp, base, float(it["strength"])))
            else:
                self.lst.insert("end", "%-58s × %.2f" % (base, float(it["strength"])))
        if not app.mounted_loras:
            self.lst.insert("end", "（还没有挂载任何 LoRA）选好上面的 LoRA 后点「挂 载 →」")

    # ---------- 自定义名称
    def rename(self):
        """给选中的 LoRA（已挂载行优先，否则下拉当前项）起个自定义名字"""
        import tkinter.simpledialog as sd
        app = self.app
        sel = [p for p in self.lst.curselection() if p < len(app.mounted_loras)]
        if sel:
            name = app.mounted_loras[sel[0]]["name"]
        else:
            name = self.map.get(self.cmb.get())
        if not name:
            messagebox.showinfo("先选一个 LoRA",
                                "在「已挂载」里点一行，或在上面下拉里选一个，再点这个按钮。", parent=self)
            return
        cur = (app.lora_store.get("aliases") or {}).get(name, "")
        new = sd.askstring("改自定义名称",
                           "给这个 LoRA 起个名字（列表 / 下拉 / 主界面都显示它）：\n\n%s\n\n留空或填原文件名 = 恢复默认" % name,
                           initialvalue=cur or os.path.basename(name), parent=self)
        if new is None:
            return
        app.set_lora_alias(name, new)
        app._save_lora_store()
        self._refresh()
        disp = app.lora_display(name)
        if disp != os.path.basename(name):
            app.set_status("LoRA 名称已设为「%s」" % disp)
        else:
            app.set_status("LoRA「%s」已恢复默认名称" % os.path.basename(name))

    # ---------- 操作
    def add(self):
        name = self.map.get(self.cmb.get())
        if not name:
            messagebox.showinfo("先选一个 LoRA", "下拉里没有可用项，点「刷新清单」或「手动填路径…」。", parent=self)
            return
        self._mount(name, float(self.var_w.get()))

    def add_manual(self):
        from tkinter import simpledialog
        p = simpledialog.askstring("手动填 LoRA 路径",
                                   "填 ComfyUI 里的相对路径，例如：\nsubdir\\my_lora.safetensors",
                                   parent=self)
        if p and p.strip():
            self._mount(p.strip(), float(self.var_w.get()))

    def _mount(self, name, strength):
        app = self.app
        for it in app.mounted_loras:
            if it["name"] == name:
                it["strength"] = strength
                app._save_lora_store()
                app._update_lora_label()
                self._refresh_list()
                app.set_status("已更新 LoRA 强度：%s × %.2f" % (os.path.basename(name), strength))
                return
        app.mounted_loras.append(dict(name=name, strength=strength))
        app._remember_lora(name, strength)
        if not app.lora_on:
            app.lora_on = True
            self.var_on.set(True)
        app._save_lora_store()
        app._update_lora_label()
        self._refresh_list()
        app.set_status("已挂载 LoRA：%s × %.2f（路径已记入 lora_store.json）"
                       % (os.path.basename(name), strength))

    def remove_sel(self):
        app = self.app
        if not app.mounted_loras:
            return
        sel = sorted([p for p in self.lst.curselection() if p < len(app.mounted_loras)], reverse=True)
        if not sel:
            messagebox.showinfo("先选一条", "在上面的列表里选中要卸下的 LoRA。", parent=self)
            return
        for p in sel:
            app.mounted_loras.pop(p)
        app._save_lora_store()
        app._update_lora_label()
        self._refresh_list()

    def clear_all(self):
        app = self.app
        app.mounted_loras = []
        app.lora_on = False
        self.var_on.set(False)
        app._save_lora_store()
        app._update_lora_label()
        self._refresh_list()
        app.set_status("已全部卸下：LoRA 停止挂载，生成不再加载任何 LoRA")

    def toggle(self):
        self.app.lora_on = bool(self.var_on.get())
        self.app._save_lora_store()
        self.app._update_lora_label()

    def refresh_avail(self):
        try:
            ls = self.app.engine.client.loader_enum("LoraLoader", "lora_name")
            self.app.lora_avail = ls
            self._refresh()
            messagebox.showinfo("LoRA 清单", "ComfyUI 当前识别到 %d 个 LoRA。" % len(ls), parent=self)
        except Exception as e:
            messagebox.showerror("刷新失败", str(e)[:300], parent=self)

    def _close(self):
        self.app.dlg_lora = None
        self.destroy()


# ================================================================== 自检
def selftest():
    from PIL import Image
    print("=== Prompt Studio 自检 ===")
    d = os.path.join(APP_DIR, "_selftest")
    os.makedirs(d, exist_ok=True)

    # 1) 切割
    sample = """{a cute anime girl, silver hair, red eyes, cherry blossom}{ 1. a photorealistic
mountain lake at golden hour }
{portrait, oil painting style}"""
    items = split_prompts(sample)
    print("[1] 切割得到 %d 条: %s" % (len(items), items))
    assert len(items) == 3, "切割结果不对"
    assert items[1].startswith("a photorealistic"), items[1]

    # 2) 空花括号 / 纯行文本
    assert split_prompts("line one\n#line two\n\nline three") == ["line one", "line three"]
    print("[2] 无花括号时按行切割 OK")

    eng = Engine()
    ok, info = eng.ensure_online(log=lambda m: print(" ", m))
    print("[3] ComfyUI:", ok, info)
    if not ok:
        print("自检中止：ComfyUI 未就绪")
        return 1

    models = fetch_models(eng.client, log=lambda m: print(" ", m))
    print("[4] 模型 %d 个:" % len(models))
    for m in models:
        print("    %-24s arch=%-10s img2img=%s ckpt=%s" %
              (m["label"][:24], m["arch"], m["img2img"], m.get("ckpt") or m.get("unet")))

    out = os.path.join(d, "img")
    os.makedirs(out, exist_ok=True)
    params = dict(width=768, height=768, steps=8, cfg=1.0, seed=12345, out_dir=out)

    # 3) 文生图
    m = next((x for x in models if x["key"] == "zetaturbo"), models[0])
    print("[5] 文生图 模型=%s" % m["label"])
    f1 = eng.generate(m, "a photorealistic mountain lake at golden hour, mist, ultra detailed",
                      1, params, log=lambda s: print("   ", s))
    print("    产出:", f1)

    # 4) 图生图（换模型 → 必须先卸载显存）
    ref = os.path.join(d, "ref.png")
    if not os.path.exists(ref):
        Image.new("RGB", (640, 640), (235, 232, 228)).save(ref)
    m2 = next((x for x in models if x["key"] == "cosfmix"), None)
    if m2 is None:
        m2 = next((x for x in models if x["img2img"] and x is not m), None)
    if m2:
        print("[6] 图生图 模型=%s" % m2["label"])
        p2 = dict(width=512, height=512, steps=20, cfg=7.0, seed=777, out_dir=out)
        f2 = eng.generate(m2, "the main character standing in a sunny park, full body",
                          1, p2, image_path=ref, denoise=0.6,
                          char_sys=DEFAULT_CHAR_SYS, use_char_sys=True,
                          log=lambda s: print("   ", s))
        print("    产出:", f2)
        print("    显存互斥记录: 当前驻留模型 =", eng.loaded)
    print("=== 自检完成 ===")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    try:
        if os.name == "nt":
            import ctypes
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except Exception:
                pass
        App().mainloop()
    except Exception:
        tb = traceback.format_exc()
        try:
            with open(ERROR_LOG, "a", encoding="utf-8") as f:
                f.write(time.strftime("\n===== %Y-%m-%d %H:%M:%S =====\n") + tb)
        except Exception:
            pass
        try:
            messagebox.showerror("程序异常", tb[-1500:])
        except Exception:
            print(tb)
