@echo off
chcp 65001 >nul
title EVE Killboard Analysis - 打包为 exe

echo ============================================================
echo   🚀 正在将 EVE Killboard Analysis 打包为 exe ...
echo ============================================================
echo.

:: 检查是否在虚拟环境中
if not defined VIRTUAL_ENV (
    if exist ".venv\Scripts\activate" (
        echo 🔄 检测到虚拟环境，正在激活 ...
        call .venv\Scripts\activate
    ) else (
        echo ⚠️  未检测到虚拟环境，使用系统 Python
    )
)

python build_exe.py

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ============================================================
    echo   ✅ 打包成功！
    echo   输出路径: %CD%\dist\EVE-Killboard-Analysis\
    echo   运行方式: 双击 EVE-Killboard-Analysis.exe
    echo ============================================================
) else (
    echo.
    echo ============================================================
    echo   ❌ 打包失败，请检查上方错误信息
    echo ============================================================
)

pause
