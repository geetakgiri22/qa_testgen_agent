@echo off
REM One-time setup on Windows 11 (run from the project folder)
python -m venv .venv || goto :err
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt || goto :err
if not exist .env copy .env.example .env
echo.
echo Setup complete. Next: ollama pull qwen2.5:3b   then   run.bat
exit /b 0
:err
echo Setup failed. Check the messages above.
exit /b 1
