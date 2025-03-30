@echo off
title Telegram Monitor
echo ===================================
echo   Telegram Моніторинг Канал
echo ===================================
echo.

:: Перевірка наявності файлу config.yaml
if not exist config.yaml (
    echo [ПОМИЛКА] Файл config.yaml не знайдено!
    echo Перевірте, що ви запускаєте скрипт з правильної папки.
    pause
    exit /b 1
)

:: Перевірка наявності Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ПОМИЛКА] Python не встановлено або не додано до PATH!
    echo Встановіть Python та переконайтеся, що його додано до системного PATH.
    pause
    exit /b 1
)

:: Запуск скрипту
echo [ІНФО] Запуск моніторингу... %date% %time%
echo [ІНФО] Щоб зупинити, натисніть Ctrl+C та підтвердіть (Y)
echo.
python monitor.py
echo.

:: Обробка помилок
if %errorlevel% neq 0 (
    echo [ПОМИЛКА] Скрипт завершився з помилкою (код: %errorlevel%).
    echo Перевірте логи для додаткової інформації.
) else (
    echo [ІНФО] Скрипт завершено.
)

pause 