@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_celery_worker.ps1"
