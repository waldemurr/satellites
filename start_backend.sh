#!/bin/bash
# Скрипт для запуска бэкенда

cd /home/redfox/programming/python/satellites
source venv/bin/activate
export PYTHONPATH="${PWD}/backend:${PWD}/backend/app:${PWD}/module"
python run.py