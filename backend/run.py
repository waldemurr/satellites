#!/usr/bin/env python3
"""
Скрипт для запуска веб-приложения
"""
import os
import sys

# Добавляем путь к модулям
sys.path.insert(0, os.path.dirname(__file__))

from app.main import create_app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=5001)