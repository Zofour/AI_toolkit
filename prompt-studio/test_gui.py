# -*- coding: utf-8 -*-
"""GUI 端到端冒烟测试：导入→选提示词→设张数→生成（文生图）→切模型→图生图"""
import os
import sys
import time
import traceback

APP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP_DIR)

import app as A  # noqa


def pump(a, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        a.update()
        time.sleep(0.05)


def wait_until(a, cond, secs, what):
    t0 = time.time()
    while time.time() - t0 < secs:
        a.update()
        time.sleep(0.05)
        if cond():
            return True
    print("!! 等待超时:", what)
    return False


def main():
    d = os.path.join(APP_DIR, "_selftest")
    os.makedirs(d, exist_ok=True)
    demo = os.path.join(d, "prompts_demo.txt")
    refp = os.path.join(d, "ref.png")
    if not os.path.exists(refp):
        from PIL import Image
        Image.new("RGB", (640, 640), (233, 228, 222)).save(refp)
    with open(demo, "w", encoding="utf-8") as f:
        f.write("{1. a photorealistic mountain lake at golden hour, mist, ultra detailed}"
                "{a cute anime girl, silver hair, red eyes, cherry blossoms}\n"
                "{cyberpunk street at night, neon signs, rain, cinematic}\n")

    a = A.App()
    a.update()
    ok = wait_until(a, lambda: bool(a.models), 240, "载入模型列表")
    print("模型数:", len(a.models), "ok=", ok)

    # 模拟导入
    txt = A.read_text_auto(demo)
    items = A.split_prompts(txt)
    a.prompts = [{"text": x, "edit": x} for x in items]
    a.lbl_src.config(text=demo)
    a._render_list()
    a.listbox.selection_clear(0, "end")
    a.listbox.selection_set(0)
    a._on_select()
    pump(a, 0.5)
    print("导入切割:", len(items), items[0][:40])
    print("提示词框内容:", a.txt_prompt.get("1.0", "end").strip()[:50])

    # 选 Z-Image 文生图, 2 张
    labels = list(a.cmb_model["values"])
    zl = [x for x in labels if x.startswith("Z-Image")]
    if zl:
        a.cmb_model.set(zl[0])
        a._on_model_change()
    a.var_n.set(2)
    a.var_w.set(768)
    a.var_h.set(768)
    a.start_generate()
    wait_until(a, lambda: not a.busy, 300, "文生图 2 张")
    print("文生图结果:", a.results)

    # 切模型 + 图生图
    cl = [x for x in labels if x.startswith("cosfMix")]
    if cl:
        a.cmb_model.set(cl[0])
        a._on_model_change()
    a.src_image = os.path.join(d, "ref.png")
    a._show_thumb(a.src_image)
    a.lbl_img.config(text="ref.png")
    a.var_i2i.set(True)
    a._on_i2i_toggle()
    a.var_n.set(1)
    a.var_w.set(512)
    a.var_h.set(512)
    a.var_steps.set(20)
    a.var_cfg.set(7.0)
    a.start_generate()
    wait_until(a, lambda: not a.busy, 300, "图生图 1 张")
    print("图生图结果:", a.results[-1:])
    print("当前显存驻留模型:", a.engine.loaded)

    # 批量：全选 3 条 × 1 张（继承当前模型/图生图设置）
    a.select_all()
    print("已选条数:", len(a.selected_idxs()), "| 计数标签:", a.lbl_count.cget("text"))
    a.var_n.set(1)
    before = len(a.results)
    a.start_batch()
    wait_until(a, lambda: not a.busy, 420, "批量生成")
    print("批量新增:", len(a.results) - before, a.results[before:])
    print("状态栏:", a.lbl_status.cget("text"))

    # LoRA 挂载：挂一个 → 生成 → 停止挂载
    a.lora_avail = a.engine.client.loader_enum("LoraLoader", "lora_name")
    print("可用 LoRA:", a.lora_avail)
    pick = next((n for n in a.lora_avail if "cozy" in n.lower()), None) or \
        next((n for n in a.lora_avail if "anima" in n.lower()), None) or \
        (a.lora_avail[0] if a.lora_avail else None)
    if pick:
        a.mounted_loras = [dict(name=pick, strength=0.6)]
        a._remember_lora(pick, 0.6)
        a.lora_on = True
        a._save_lora_store()
        a._update_lora_label()
        print("挂载后标签:", a.lbl_lora.cget("text"))
        a.set_lora_alias(pick, "测试别名")
        print("自定义名称:", a.lora_display(pick), "| 主界面:", a.lbl_lora.cget("text"))
        print("生效 LoRA:", a._active_loras())
        a.var_i2i.set(False)
        a.var_n.set(1)
        a.var_steps.set(12)
        before = len(a.results)
        a.start_generate()
        wait_until(a, lambda: not a.busy, 300, "LoRA 生图")
        print("LoRA 出图:", a.results[before:])
        a.stop_loras()
        print("停止挂载后标签:", a.lbl_lora.cget("text"), "| 生效 LoRA:", a._active_loras())
        print("lora_store.json 存在:", os.path.exists(a._lora_store_path()))

    # 自由输入 → 加入列表
    a.new_prompt()
    a.txt_prompt.insert("1.0", "a red bicycle leaning on a brick wall, morning light, 35mm")
    print("自由输入:", a.txt_prompt.get("1.0", "end").strip()[:40], "| cur_idx=", a.cur_idx)
    a.add_prompt_to_list()
    print("加入列表后条数:", len(a.prompts), "cur_idx=", a.cur_idx)
    print("状态栏:", a.lbl_status.cget("text"))
    print("状态栏:", a.lbl_status.cget("text"))
    pump(a, 1.0)
    print("SMOKE OK")
    if "--keep" in sys.argv:
        pump(a, 120)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
