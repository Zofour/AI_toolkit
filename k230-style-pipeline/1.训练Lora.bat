@echo off
chcp 936 >nul
setlocal
title 1 - 训练风格 LoRA
set "ROOT=%~dp0"
if not exist "%ROOT%train_style_lora.py" set "ROOT=C:\chatbox_temp\"
cd /d "%ROOT%"
set PYTHONIOENCODING=gbk:replace
set HF_ENDPOINT=https://hf-mirror.com
set "PY=C:\Users\yourname\AppData\Local\Programs\Python\Python313\python.exe"
if not exist "%PY%" set "PY=python"

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
