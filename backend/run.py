#!/usr/bin/env python3
"""Скрипт запуска веб-приложения."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import create_app

if __name__ == '__main__':
    create_app().run(debug=True, host='0.0.0.0', port=5002, threaded=True)
