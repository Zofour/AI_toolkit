@echo off
chcp 936 >nul
setlocal
title 4 - 生成 kmodel
set "ROOT=%~dp0"
if not exist "%ROOT%export_onnx.py" set "ROOT=C:\chatbox_temp\"
cd /d "%ROOT%"
set PYTHONIOENCODING=gbk:replace
set HF_ENDPOINT=https://hf-mirror.com
set "PY=C:\Users\yourname\AppData\Local\Programs\Python\Python313\python.exe"
if not exist "%PY%" set "PY=python"

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
