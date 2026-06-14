#!/bin/bash

# Установка пути к текущему скрипту
SCRIPT_DIR="$(dirname "$(realpath "$0")")"

# Определение пути к родительской папке на два уровня выше
PARENT_DIR="$(realpath "$SCRIPT_DIR/../../")"
MEDIA_DIR="$PARENT_DIR/Media"

# Проверка, существует ли папка Media
if [ -d "$MEDIA_DIR" ]; then
    echo "Папка 'Media' найдена: $MEDIA_DIR"
    echo "Очистка файлов в папке $MEDIA_DIR"

    # Очистка файлов в под-папках, исключая любые не-папки
    for subfolder in "$MEDIA_DIR"/*; do
        if [ -d "$subfolder" ]; then
            echo "Очистка папки: $subfolder"
            # Удаление всех файлов внутри каждой под-папки
            find "$subfolder" -type f -print -exec rm -f {} +
        fi
    done
    
    echo "Очистка завершена."
else
    echo "Папка 'Media' не найдена."
fi

# Ожидание ввода пользователя перед закрытием
read -p "Нажмите Enter, чтобы закрыть..."
