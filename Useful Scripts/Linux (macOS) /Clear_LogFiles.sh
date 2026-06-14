#!/bin/bash

# Установка пути к текущему скрипту
SCRIPT_DIR="$(dirname "$(realpath "$0")")"

# Определение пути к родительской папке на два уровня выше
PARENT_DIR="$(realpath "$SCRIPT_DIR/../../")"
LOGS_DIR="$PARENT_DIR/Logs"

# Проверка, существует ли папка Logs
if [ -d "$LOGS_DIR" ]; then
    echo "Папка 'Logs' найдена: $LOGS_DIR"
    echo "Очистка файлов в папке $LOGS_DIR"

    # Удаление всех файлов в папке Logs
    find "$LOGS_DIR" -type f -print -delete
    
    echo "Очистка завершена."
else
    echo "Папка 'Logs' не найдена."
fi

# Ожидание ввода пользователя перед закрытием
read -p "Нажмите Enter, чтобы закрыть..."
