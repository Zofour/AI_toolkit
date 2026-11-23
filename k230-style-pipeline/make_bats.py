# -*- coding: utf-8 -*-
"""生成 4 个双击运行的 .bat（GBK + CRLF，cmd 才能正确解析中文）

要点：
  1) set /p 在「直接回车」时可能把变量设成**一个空格**，所以统一用 :ask 子程序
     （去首尾空格 + 空则用默认值），否则用户按回车就会得到「找不到文件夹」。
  2) 参数改动后不要手改 bat，改这里再跑一次本脚本。
"""
import os
import sys

ROOT = r"C:\chatbox_temp"

# 所有 bat 共用的头 + :ask 子程序
HEAD = r'''@echo off
chcp 936 >nul
setlocal
title {title}
set "ROOT=%~dp0"
if not exist "%ROOT%{anchor}" set "ROOT=C:\chatbox_temp\"
cd /d "%ROOT%"
set PYTHONIOENCODING=gbk:replace
set HF_ENDPOINT=https://hf-mirror.com
set "PY=C:\Users\yourname\AppData\Local\Programs\Python\Python313\python.exe"
if not exist "%PY%" set "PY=python"
'''

TAIL = r'''

exit /b 0

:ask
rem %1=变量名 %2=提示 %3=默认值（回车/空白都取默认值）
set "_IN="
set /p "_IN=%~2 [回车=%~3]："
set "_TMP="
for /f "tokens=* delims= " %%A in ("%_IN%") do set "_TMP=%%A"
if "%_TMP%"=="" set "_TMP=%~3"
set "%~1=%_TMP%"
exit /b
'''


BAT1 = HEAD.format(title="1 - 训练风格 LoRA", anchor="train_style_lora.py") + r'''
echo ==================================================================
echo   1 / 4   训练风格 LoRA   (底模 gsdf/Counterfeit-V2.5)
echo ==================================================================
echo.
echo  素材文件夹里放「成对的图」，命名规则：
echo      同一张图前缀相同，后缀 1 = 原图，后缀 2 = 风格化图
echo      例： 1.1.png  1.2.png     2.1.jpg  2.2.jpg     ...
echo.
echo  本步只把「.2 风格化图」拿去训 LoRA（.1 原图不参与）。
echo  小技巧：可以直接把文件夹拖到这个 bat 上松手，等于填好路径。
echo.
set "SRC=%~1"
if "%SRC%"=="" set "SRC=C:\chatbox_temp\style_pairs"
call :ask SRC "素材文件夹" "%SRC%"
echo.
if not exist "%SRC%\" (
  echo [错误] 找不到这个文件夹：%SRC%
  echo        把成对素材放进去，或直接把文件夹拖到 bat 上再试。
  echo.
  pause
  exit /b 1
)

set /a N1=0
set /a N2=0
for %%F in ("%SRC%\*.1.*") do if exist "%%~fF" set /a N1+=1
for %%F in ("%SRC%\*.2.*") do if exist "%%~fF" set /a N2+=1
echo   统计： 原图(*.1.*) = %N1% 个 ， 风格图(*.2.*) = %N2% 个
if "%N2%"=="0" (
  echo.
  echo [错误] 一个「*.2.*」风格图都没找到。
  echo        命名必须是  前缀.2.扩展名 ，例如 1.2.png
  echo.
  pause
  exit /b 1
)

echo.
echo   训练用哪一批图？
echo      [1] 只用 .2 风格图（推荐：风格 LoRA 只该学风格图）
echo      [2] .1 .2 都用（风格会被稀释，一般不要）
call :ask CH "请输入 1 或 2" "1"

set "STAGE=work\_lora_style_only"
if "%CH%"=="2" set "STAGE=work\_lora_all"
echo.
echo   整理素材到 %STAGE% ...
if exist "%STAGE%" rd /s /q "%STAGE%"
mkdir "%STAGE%" 2>nul
if "%CH%"=="2" (
  copy /y "%SRC%\*.1.*" "%STAGE%\" >nul
  copy /y "%SRC%\*.2.*" "%STAGE%\" >nul
) else (
  copy /y "%SRC%\*.2.*" "%STAGE%\" >nul
)
echo   完成。

set "LORAOUT=work\lora\style_Counterfeit-V2.5"
echo.
echo   === 开始训练 LoRA（1200 步 / rank 16 / 512px）===
echo   === 输出目录： %LORAOUT%
echo   === 大概 20~40 分钟，进度看屏幕上的 step 打印
echo.
%PY% train_style_lora.py --data "%STAGE%" --out "%LORAOUT%" --base_model gsdf/Counterfeit-V2.5 --resolution 512 --rank 16 --max_steps 1200 --batch 1 --grad_accum 4 --mixed_precision bf16 --gradient_checkpointing --train_text_encoder --save_every 300 --preview
if errorlevel 1 (
  echo.
  echo [失败] 训练返回错误，往上翻最后几十行看原因。
  echo.
  pause
  exit /b 1
)

echo.
echo ==================================================================
echo   [完成] LoRA 权重：
echo   %CD%\%LORAOUT%\pytorch_lora_weights.safetensors
echo ==================================================================
echo.
echo   [提示] 素材少很容易过拟合，%LORAOUT%\checkpoint-* 里有中间快照。
echo          想换一版：把那个目录里的权重文件复制成
echo          %LORAOUT%\pytorch_lora_weights.safetensors 即可。
echo.
start "" "%CD%\%LORAOUT%"
pause
''' + TAIL


BAT2 = HEAD.format(title="2 - 批量生图 teacher 造蒸馏数据", anchor="gen_m1.py") + r'''
echo ==================================================================
echo   2 / 4   批量生图（teacher 把实拍照片批量风格化 = 造蒸馏数据）
echo ==================================================================
echo.
echo  流程： 实拍照片 -^> ControlNet 锁结构 + LoRA 上风格 -^> 生成图
echo         输出目录里会得到 input / target / mask / qc / report.json
echo.
set "SRC=%~1"
if "%SRC%"=="" set "SRC=D:\zimage_persons_1000"
call :ask SRC "实拍照片文件夹" "%SRC%"
echo.
if not exist "%SRC%\" (
  echo [错误] 找不到这个文件夹：%SRC%
  echo.
  pause
  exit /b 1
)

set "OUTDIR=work\m1"
call :ask OUTDIR "输出目录" "%OUTDIR%"

set "LORADIR=work\lora\style_Counterfeit-V2.5"
set "LORADIRV1=work\lora\style_A3"
set "PV1=k230style, clean line art, lightened pastel palette, pale soft colors, light shading, detailed face, upper body portrait, plain white background"
set "NEGV1=anime, cel shading, big eyes, 3d render, blurry, soft focus, lowres, bad anatomy, deformed face, extra fingers, watermark, text, jpeg artifacts"
set "MAN=%SRC%\manifest.csv"
set "BASEMODEL=gsdf/Counterfeit-V2.5"

set /a NHAVE=0
for %%F in ("%OUTDIR%\target\*.png") do if exist "%%~fF" set /a NHAVE+=1

echo.
echo   配置：
echo     实拍目录  ： %SRC%
echo     输出目录  ： %OUTDIR%（已有 %NHAVE% 对）
if exist "%LORADIR%\pytorch_lora_weights.safetensors" (
  echo     风格 LoRA ： %LORADIR%
) else (
  echo     风格 LoRA ： 没找到！会用纯 ControlNet+img2img，风格会弱很多
  echo                 （先跑 1.训练Lora.bat）
)
if exist "%MAN%" (
  echo     逐图 prompt：%MAN%
) else (
  echo     逐图 prompt：没有 manifest.csv，用统一 prompt
)
echo     画风强度  ： strength 0.68 / cn_scale 0.8 / lora_scale 0.65（默认偏保守，
echo                 看着像「加了滤镜的照片」就选 [5] 或按下面提示调）
if %NHAVE% GTR 0 (
  echo.
  echo   [重要] 输出目录已经有了 %NHAVE% 对：选 [1] 会**全部跳过**，等于什么都没做，
  echo          你会看到「图片还是旧的 / 换了 LoRA 也没变」。
  echo          换过 LoRA、改过参数、想重新生成，都必须选 [2]（覆盖同名文件）。
)
echo.
echo      [1] 续跑（只补没生成过的，跑满 1000 张约 1~2 小时）
echo      [2] 从头重跑（覆盖同名文件，推荐换 LoRA 后用这个）
echo      [3] 快速试跑 10 张（先看效果）
echo      [4] 只做分割+裁剪，不跑模型（秒级，验证几何）
echo      [5] 加强风格版试跑 10 张（strength 0.78 / cn_scale 0.6 / lora_scale 0.75）
echo      [6] 线稿化 v1 配方（canny 1.1 + strength 1.0 + style_A3，已确认效果好；直接跑全部）
if %NHAVE% GTR 0 (
  call :ask CH "选择" "2"
) else (
  call :ask CH "选择" "1"
)

if not "%CH%"=="6" goto :args_not6
set ARGS=--src "%SRC%" --out "%OUTDIR%" --hw 768 608 --seg auto --control canny --aug_n 1 --steps 32 --cn_scale 1.1 --strength 1.00 --base_model %BASEMODEL% --prompt "%PV1%" --negative "%NEGV1%"
if exist "%LORADIRV1%\pytorch_lora_weights.safetensors" set ARGS=%ARGS% --lora "%LORADIRV1%" --lora_scale 1.0
if exist "%MAN%" set ARGS=%ARGS% --manifest "%MAN%"
goto :args_done
:args_not6
if not "%CH%"=="5" goto :args_normal
set ARGS=--src "%SRC%" --out "%OUTDIR%" --hw 768 608 --seg auto --control softedge --aug_n 1 --limit 10 --base_model %BASEMODEL% --lora_scale 0.75 --cn_scale 0.6 --strength 0.78
if exist "%LORADIR%\pytorch_lora_weights.safetensors" set ARGS=%ARGS% --lora "%LORADIR%"
if exist "%MAN%" set ARGS=%ARGS% --manifest "%MAN%"
goto :args_done
:args_normal
set ARGS=--src "%SRC%" --out "%OUTDIR%" --hw 768 608 --seg auto --control softedge --aug_n 1 --base_model %BASEMODEL%
if exist "%LORADIR%\pytorch_lora_weights.safetensors" set ARGS=%ARGS% --lora "%LORADIR%"
if exist "%MAN%" set ARGS=%ARGS% --manifest "%MAN%"
if "%CH%"=="1" set ARGS=%ARGS% --resume
if "%CH%"=="3" set ARGS=%ARGS% --limit 10
if "%CH%"=="4" set ARGS=%ARGS% --dry
:args_done

echo.
echo   === 执行： gen_m1.py %ARGS%
echo.
%PY% gen_m1.py %ARGS%
if errorlevel 1 (
  echo.
  echo [失败] 生成过程报错，往上翻看原因。
  echo        常见：显存不够（关掉别的占显存程序）、hf-mirror 拉模型失败（重跑一次）。
  echo.
  pause
  exit /b 1
)

set /a NP=0
for %%F in ("%OUTDIR%\input\*.png") do if exist "%%~fF" set /a NP+=1
echo.
echo ==================================================================
echo   [完成] 这个目录里现在有 %NP% 对
echo   数据目录： %CD%\%OUTDIR%
echo ==================================================================
echo.
echo   [提示] 打开 %OUTDIR%\qc 人眼抽检，剔除「背景被改 / 人脸崩」的样本，
echo          再跑 3.训练学生网络.bat。异常样本编号也在 report.json 里。
echo.
start "" "%CD%\%OUTDIR%"
pause
''' + TAIL


BAT3 = HEAD.format(title="3 - 训练学生网络", anchor="train_distill.py") + r'''
echo ==================================================================
echo   3 / 4   训练学生网络（把 teacher 的图画法蒸馏进小网络）
echo ==================================================================
echo.
echo  输入： 2.批量生图.bat 产出的 input/target/mask
echo  输出： student.pth / student_fused.pth / samples 预览 / train_log.json
echo.
set "PAIRS=work\m1"
call :ask PAIRS "M1 数据目录" "%PAIRS%"
echo.
if not exist "%PAIRS%\input\" (
  echo [错误] 找不到 %PAIRS%\input
  echo        先跑 2.批量生图.bat 把蒸馏数据造出来。
  echo.
  pause
  exit /b 1
)
set /a NP=0
for %%F in ("%PAIRS%\input\*.png") do if exist "%%~fF" set /a NP+=1
echo   找到 %NP% 对训练数据

set "OUTD=work\student_v4"
call :ask OUTD "输出目录" "%OUTD%"
echo.
echo      [1] 快速试跑（只用 40 对 + 2 epoch，几分钟，先确认不报错）
echo      [2] 正式跑（30 epoch，约 25~60 分钟）
call :ask CH "选择" "2"

set ARGS=--pairs "%PAIRS%" --out "%OUTD%" --hw 768 608 --batch 4 --grad_accum 2 --workers 4 --w_pix 0.5 --w_line 1.5 --w_adv 0.35 --adv_start 500 --residual
if "%CH%"=="1" (
  set ARGS=--pairs "%PAIRS%" --out "%OUTD%" --hw 768 608 --batch 4 --grad_accum 2 --workers 0 --epochs 2 --limit 40 --w_pix 0.5 --w_line 1.5 --residual
) else (
  set ARGS=%ARGS% --epochs 30
)

echo.
echo   === 执行： train_distill.py %ARGS%
echo   === 默认带 --residual（残差学习）与 w_line 1.5/w_adv 0.35，实测比旧配置清晰很多
 echo   === 若报 DataLoader / workers 相关错误，把 bat 里的 --workers 4 改成 0
echo.
%PY% train_distill.py %ARGS%
if errorlevel 1 (
  echo.
  echo [失败] 训练报错，往上翻看原因。
  echo        - 尺寸不匹配：--hw 必须和造数据时一致（768 608）
  echo        - 显存不够：把 bat 里的 --batch 4 改成 2
  echo.
  pause
  exit /b 1
)

echo.
echo ==================================================================
echo   [完成] 输出目录： %CD%\%OUTD%
echo      student.pth         （未折叠，给第 4 步导出用）
echo      student_fused.pth   （已折叠 BN 的备份）
echo      samples\final.jpg   （看效果：这一版学生网络的画风）
echo ==================================================================
echo.
echo   下一步：4.生成kmodl文件.bat
echo.
start "" "%CD%\%OUTD%"
pause
''' + TAIL


BAT4 = HEAD.format(title="4 - 生成 kmodel", anchor="export_onnx.py") + r'''
echo ==================================================================
echo   4 / 4   生成 kmodel（ONNX 导出 -^> WSL 里 nncase 编译）
echo ==================================================================
echo.
echo  第 1 步在 Windows 上把 pth 导成 ONNX 并抽校准集；
echo  第 2 步在 WSL(Ubuntu) 里用 nncase 2.11.0 编成 K230 能跑的 .kmodel。
echo.
set "SDIR=work\student_v4"
call :ask SDIR "学生网络目录" "%SDIR%"

set "PAIRS=work\m1"
call :ask PAIRS "M1 数据目录（抽校准集用）" "%PAIRS%"

set "EXPORT=work\export"
set "CKPT=%SDIR%\student.pth"
set "FLAG="
if not exist "%CKPT%" (
  set "CKPT=%SDIR%\student_fused.pth"
  set "FLAG=--already-fused"
)
if not exist "%CKPT%" (
  echo.
  echo [错误] 在 %SDIR% 里找不到 student.pth 或 student_fused.pth
  echo        先跑 3.训练学生网络.bat
  echo.
  pause
  exit /b 1
)

echo.
echo   === 第 1 步 / 2：导出 ONNX + 抽校准集 ===
echo   权重： %CKPT%  %FLAG%
echo   导出后会先跑 verify_onnx.py 终检（跟 target 算 MAE）——不正常就不会继续编译
echo   （--atol 3e-3：ONNX 与 PyTorch 的绝对误差时常在 1e-3 上下，相对误差仅 1e-6 量级，
echo     默认 1e-3 会误报卡住；如真出问题它会报很大的误差）
echo.
%PY% export_onnx.py --ckpt "%CKPT%" %FLAG% --pairs "%PAIRS%" --out "%EXPORT%" --hw 768 608 --atol 3e-3
if errorlevel 1 (
  echo.
  echo [失败] ONNX 导出或 ORT 对齐没过，往上翻看原因。
  echo.
  pause
  exit /b 1
)
if not exist "%EXPORT%\student_sim.onnx" (
  echo.
  echo [错误] 没生成 %EXPORT%\student_sim.onnx
  echo.
  pause
  exit /b 1
)
%PY% -u verify_onnx.py --onnx "%EXPORT%\student_sim.onnx" --pairs "%PAIRS%" --n 4 --save "%EXPORT%\verify.jpg"
if errorlevel 1 (
  echo.
  echo [错误] 导出终检没过（输出不像 target，很可能是残差没加回输入）。
  echo        检查：ckpt 旁是否有 model_info.json（residual=true），或手动加 --residual 重跑。
  echo.
  pause
  exit /b 1
)

echo.
echo   === 第 2 步 / 2：WSL 里编译 kmodel（约 2 分钟）===
echo   （若这步失败，可以先在 WSL 里手动跑： wsl  然后
echo     /home/yourpc/nn313/bin/python /mnt/c/chatbox_temp/compile_kmodel.py --help）
echo.
wsl bash -lc "export DOTNET_ROLL_FORWARD=LatestMajor; export DOTNET_ROLL_FORWARD_TO_PRERELEASE=1; export NNCASE_PLUGIN_PATH=/home/yourpc/nn313/lib/python3.13/site-packages/nncase_kpu; /home/yourpc/nn313/bin/python /mnt/c/chatbox_temp/compile_kmodel.py --onnx /mnt/c/chatbox_temp/work/export/student_sim.onnx --calib /mnt/c/chatbox_temp/work/export/calib.npy --out /mnt/c/chatbox_temp/work/export/style.kmodel --hw 768 608"
if errorlevel 1 (
  echo.
  echo [失败] WSL 编译失败。检查：
  echo       1) WSL 里有没有 /home/yourpc/nn313/bin/python （nncase 环境）
  echo       2) 项目是不是还在 C:\chatbox_temp （WSL 路径是写死的）
  echo.
  pause
  exit /b 1
)
if not exist "%EXPORT%\style.kmodel" (
  echo.
  echo [错误] WSL 跑完了但没看到 %EXPORT%\style.kmodel
  echo.
  pause
  exit /b 1
)

echo.
for %%F in ("%EXPORT%\style.kmodel") do echo   [完成] %%~fF   %%~zF 字节
copy /y "%EXPORT%\style.kmodel" "sd_payload\kmodel\style.kmodel" >nul
echo   已同步一份到 sd_payload\kmodel\style.kmodel
echo.
echo ==================================================================
echo   下一步：
echo     把 style.kmodel 拷到 SD 卡 /sdcard/kmodel/ 覆盖旧的，
echo     然后跑板端脚本 k230_style.py（CanMV IDE 打开运行）。
echo ==================================================================
echo.
start "" "%CD%\%EXPORT%"
pause
''' + TAIL


BATS = {
    "1.训练Lora.bat": BAT1,
    "2.批量生图.bat": BAT2,
    "3.训练学生网络.bat": BAT3,
    "4.生成kmodl文件.bat": BAT4,
}


def main():
    bad = 0
    for name, text in BATS.items():
        text = text.replace("\r\n", "\n").replace("\n", "\r\n")
        try:
            data = text.encode("gbk")
        except UnicodeEncodeError as e:
            print("!! %s 里有 GBK 编不出的字符: %r" % (name, text[e.start:e.end]))
            bad += 1
            continue
        p = os.path.join(ROOT, name)
        with open(p, "wb") as f:
            f.write(data)
        print("[ok] %s  (%d 字节, GBK+CRLF)" % (p, len(data)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
