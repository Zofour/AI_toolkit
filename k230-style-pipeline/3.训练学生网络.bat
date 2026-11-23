@echo off
chcp 936 >nul
setlocal
title 3 - 训练学生网络
set "ROOT=%~dp0"
if not exist "%ROOT%train_distill.py" set "ROOT=C:\chatbox_temp\"
cd /d "%ROOT%"
set PYTHONIOENCODING=gbk:replace
set HF_ENDPOINT=https://hf-mirror.com
set "PY=C:\Users\yourname\AppData\Local\Programs\Python\Python313\python.exe"
if not exist "%PY%" set "PY=python"

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
