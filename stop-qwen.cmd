@echo off
echo Stopping any running Qwen / Python servers...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :7860 ^| findstr LISTENING') do (
    taskkill /f /pid %%a 2>nul
)
taskkill /f /im pythonw.exe 2>nul
echo Servers stopped.
timeout /t 2 >nul
