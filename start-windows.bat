@echo off
if not exist ".venv\Scripts\python.exe" (
    echo Bitte zuerst setup-windows.bat ausfuehren.
    pause & exit /b 1
)
call .venv\Scripts\activate.bat
start "" pythonw -c "import main; main.main()"
