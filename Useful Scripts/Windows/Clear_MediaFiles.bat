@echo off
chcp 65001 >nul
setlocal

REM Определение пути к текущему скрипту
set "SCRIPT_DIR=%~dp0"

REM Путь к родительской папке на два уровня выше
for %%i in ("%SCRIPT_DIR%..\..") do set "PARENT_DIR=%%~fi"

REM Путь к папке Media
set "MEDIA_DIR=%PARENT_DIR%\Media"

REM Проверка, существует ли папка Media
if exist "%MEDIA_DIR%" (
    echo Папка "Media" найдена: "%MEDIA_DIR%"
    echo Очистка файлов в папке "%MEDIA_DIR%"

    REM Удаление файлов в папке Media, но не удаление самой папки
    del /q "%MEDIA_DIR%\*.*"
    
    REM Удаление содержимого под-папок, но не самих папок
    for /d %%D in ("%MEDIA_DIR%\*") do (
        echo Очистка папки: %%D
        del /q "%%D\*.*"
    )
    echo Очистка завершена.
) else (
    echo Папка "Media" не найдена.
)

pause
endlocal
