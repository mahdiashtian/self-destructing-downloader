@echo off
chcp 65001 >nul
setlocal

REM Определение пути к текущему скрипту
set "SCRIPT_DIR=%~dp0"

REM Путь к родительской папке на два уровня выше
for %%i in ("%SCRIPT_DIR%..\..") do set "PARENT_DIR=%%~fi"

REM Путь к папке Logs
set "LOGS_DIR=%PARENT_DIR%\Logs"

REM Проверка, существует ли папка Logs
if exist "%LOGS_DIR%" (
    echo Папка "Logs" найдена: "%LOGS_DIR%"
    echo Очистка файлов в папке "%LOGS_DIR%"

    REM Удаление файлов в папке Logs, но не удаление самой папки
    del /q "%LOGS_DIR%\*.*"
    
    REM Удаление содержимого под-папок, но не самих папок
    for /d %%D in ("%LOGS_DIR%\*") do (
        echo Очистка папки: %%D
        del /q "%%D\*.*"
    )
    echo Очистка завершена.
) else (
    echo Папка "Logs" не найдена.
)

pause
endlocal
