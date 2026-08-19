@echo off
cd /d %~dp0\..
if not exist .venv py -m venv .venv
call .venv\Scripts\activate
python -m pip install -r requirements.txt
if not exist .env copy .env.example .env
if not exist data\repository mkdir data\repository
uvicorn app.main:app --reload --host 127.0.0.1 --port 8090
