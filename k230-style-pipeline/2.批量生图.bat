@echo off
chcp 936 >nul
setlocal
title 2 - 批量生图 teacher 造蒸馏数据
set "ROOT=%~dp0"
if not exist "%ROOT%gen_m1.py" set "ROOT=C:\chatbox_temp\"
cd /d "%ROOT%"
set PYTHONIOENCODING=gbk:replace
set HF_ENDPOINT=https://hf-mirror.com
set "PY=C:\Users\yourname\AppData\Local\Programs\Python\Python313\python.exe"
if not exist "%PY%" set "PY=python"

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
