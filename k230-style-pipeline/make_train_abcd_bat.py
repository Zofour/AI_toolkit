# -*- coding: utf-8 -*-
"""生成训练 bat（GBK+CRLF）"""
import os

PY = r"C:\Users\yourname\AppData\Local\Programs\Python\Python313\python.exe"
if not os.path.exists(PY):
    PY = "python"

DATA = r"C:\chatbox_temp\work\abcd_lora_data"
OUT = r"C:\chatbox_temp\work\lora\abcd_style"
LOG = r"C:\chatbox_temp\work\abcd_train.log"

bat = f'''@echo off
chcp 936 >nul
setlocal
title abcd LoRA training
cd /d C:\\chatbox_temp
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
set HF_ENDPOINT=https://hf-mirror.com
rem 数据目录：{DATA}
rem 输出目录：{OUT}
{chr(34)}{PY}{chr(34)} -u train_style_lora.py --data "{DATA}" --out "{OUT}" ^
  --base_model gsdf/Counterfeit-V2.5 --resolution 512 --rank 32 --lora_alpha 32 ^
  --max_steps 2400 --batch 1 --grad_accum 4 --lr_unet 1e-4 --lr_te 1e-5 ^
  --mixed_precision bf16 --gradient_checkpointing --train_text_encoder ^
  --save_every 400 --log_every 20 --caption "abcdstyle" --seed 42 > "{LOG}" 2>&1
echo EXITCODE=%ERRORLEVEL% >> "{LOG}"
'''
p = r"C:\chatbox_temp\run_train_abcd.bat"
with open(p, "wb") as f:
    f.write(bat.replace("\r\n", "\n").replace("\n", "\r\n").encode("gbk", "replace"))
print("written", p, os.path.getsize(p), "bytes")
