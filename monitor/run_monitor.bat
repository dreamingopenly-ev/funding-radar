@echo off
REM Daily run of the Funding Radar monitor (Task Scheduler or n8n "Execute Command").
cd /d "%~dp0.."
if "%OLLAMA_MODEL%"=="" set OLLAMA_MODEL=qwen2.5:14b
python monitor\local_monitor.py >> monitor\last_run.log 2>&1
