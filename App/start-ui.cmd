@echo off
setlocal enabledelayedexpansion

set "APP_DIR=%~dp0"
set "ROOT_DIR=%APP_DIR%..\"
set "CONFIG_FILE=%APP_DIR%venv_path.txt"
set "PYTHON_EXE="

:: Allow user to re-select folder by running: start-ui.cmd --select
if /i "%~1"=="--select" del /f /q "%CONFIG_FILE%" 2>nul
if /i "%~1"=="-s" del /f /q "%CONFIG_FILE%" 2>nul

:: 1. Check saved venv path in App\venv_path.txt
if exist "%CONFIG_FILE%" (
    set /p SAVED_LINE=<"%CONFIG_FILE%"
    for /f "delims=" %%p in ("!SAVED_LINE!") do (
        set "CANDIDATE=%%~p"
        if exist "!CANDIDATE!\Scripts\pythonw.exe" set "PYTHON_EXE=!CANDIDATE!\Scripts\pythonw.exe"
        if exist "!CANDIDATE!\Scripts\python.exe" set "PYTHON_EXE=!CANDIDATE!\Scripts\python.exe"
        if exist "!CANDIDATE!\venv\Scripts\pythonw.exe" set "PYTHON_EXE=!CANDIDATE!\venv\Scripts\pythonw.exe"
        if exist "!CANDIDATE!\venv\Scripts\python.exe" set "PYTHON_EXE=!CANDIDATE!\venv\Scripts\python.exe"
        if exist "!CANDIDATE!\.venv\Scripts\pythonw.exe" set "PYTHON_EXE=!CANDIDATE!\.venv\Scripts\pythonw.exe"
        if exist "!CANDIDATE!\.venv\Scripts\python.exe" set "PYTHON_EXE=!CANDIDATE!\.venv\Scripts\python.exe"
        if exist "!CANDIDATE!" (
            for %%x in ("!CANDIDATE!") do (
                if /i "%%~nxx"=="pythonw.exe" set "PYTHON_EXE=!CANDIDATE!"
                if /i "%%~nxx"=="python.exe" set "PYTHON_EXE=!CANDIDATE!"
            )
        )
    )
)

:: 2. Check local venv beside start-ui.cmd or in root or parent
if not defined PYTHON_EXE (
    if exist "%APP_DIR%venv\Scripts\pythonw.exe" set "PYTHON_EXE=%APP_DIR%venv\Scripts\pythonw.exe"
    if exist "%APP_DIR%venv\Scripts\python.exe" set "PYTHON_EXE=%APP_DIR%venv\Scripts\python.exe"
    if exist "%APP_DIR%.venv\Scripts\pythonw.exe" set "PYTHON_EXE=%APP_DIR%.venv\Scripts\pythonw.exe"
    if exist "%APP_DIR%.venv\Scripts\python.exe" set "PYTHON_EXE=%APP_DIR%.venv\Scripts\python.exe"
    if exist "%ROOT_DIR%venv\Scripts\pythonw.exe" set "PYTHON_EXE=%ROOT_DIR%venv\Scripts\pythonw.exe"
    if exist "%ROOT_DIR%venv\Scripts\python.exe" set "PYTHON_EXE=%ROOT_DIR%venv\Scripts\python.exe"
    if exist "%ROOT_DIR%.venv\Scripts\pythonw.exe" set "PYTHON_EXE=%ROOT_DIR%.venv\Scripts\pythonw.exe"
    if exist "%ROOT_DIR%.venv\Scripts\python.exe" set "PYTHON_EXE=%ROOT_DIR%.venv\Scripts\python.exe"
    if exist "%ROOT_DIR%..\venv\Scripts\pythonw.exe" set "PYTHON_EXE=%ROOT_DIR%..\venv\Scripts\pythonw.exe"
    if exist "%ROOT_DIR%..\venv\Scripts\python.exe" set "PYTHON_EXE=%ROOT_DIR%..\venv\Scripts\python.exe"
)

:: 4. Check known user and system locations
if not defined PYTHON_EXE (
    if exist "%USERPROFILE%\Qwen-Image-2.1\venv\Scripts\pythonw.exe" set "PYTHON_EXE=%USERPROFILE%\Qwen-Image-2.1\venv\Scripts\pythonw.exe"
    if exist "%USERPROFILE%\Qwen-Image-2.1\venv\Scripts\python.exe" set "PYTHON_EXE=%USERPROFILE%\Qwen-Image-2.1\venv\Scripts\python.exe"
)
if not defined PYTHON_EXE (
    if exist "C:\Users\d.chipashvili\Qwen-Image-2.1\venv\Scripts\pythonw.exe" set "PYTHON_EXE=C:\Users\d.chipashvili\Qwen-Image-2.1\venv\Scripts\pythonw.exe"
    if exist "C:\Users\d.chipashvili\Qwen-Image-2.1\venv\Scripts\python.exe" set "PYTHON_EXE=C:\Users\d.chipashvili\Qwen-Image-2.1\venv\Scripts\python.exe"
    if exist "C:\Users\d.chipashvili\Qwen-Image-2.1\.venv\Scripts\pythonw.exe" set "PYTHON_EXE=C:\Users\d.chipashvili\Qwen-Image-2.1\.venv\Scripts\pythonw.exe"
    if exist "C:\Users\d.chipashvili\Qwen-Image-2.1\.venv\Scripts\python.exe" set "PYTHON_EXE=C:\Users\d.chipashvili\Qwen-Image-2.1\.venv\Scripts\python.exe"
)
if not defined PYTHON_EXE (
    if exist "C:\Qwen-Image-2.1\venv\Scripts\pythonw.exe" set "PYTHON_EXE=C:\Qwen-Image-2.1\venv\Scripts\pythonw.exe"
    if exist "C:\Qwen-Image-2.1\venv\Scripts\python.exe" set "PYTHON_EXE=C:\Qwen-Image-2.1\venv\Scripts\python.exe"
)
if not defined PYTHON_EXE (
    if exist "D:\Qwen-Image-2.1\venv\Scripts\pythonw.exe" set "PYTHON_EXE=D:\Qwen-Image-2.1\venv\Scripts\pythonw.exe"
    if exist "D:\Qwen-Image-2.1\venv\Scripts\python.exe" set "PYTHON_EXE=D:\Qwen-Image-2.1\venv\Scripts\python.exe"
)

:: 5. If still not found, open Windows Folder Browser dialog
if not defined PYTHON_EXE (
    echo ========================================================
    echo  Qwen Python venv not found in default paths.
    echo  Opening folder selection dialog...
    echo ========================================================
    for /f "usebackq delims=" %%I in (`powershell -NoProfile -STA -Command "Add-Type -AssemblyName System.Windows.Forms; $f = New-Object System.Windows.Forms.FolderBrowserDialog; $f.Description = 'Select Qwen-Image-2.1 folder (or venv folder)'; $f.ShowNewFolderButton = $false; $top = New-Object System.Windows.Forms.Form; $top.TopMost = $true; if ($f.ShowDialog($top) -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $f.SelectedPath }"`) do (
        set "CHOSEN_PATH=%%I"
    )
    if defined CHOSEN_PATH (
        if exist "!CHOSEN_PATH!\Scripts\pythonw.exe" (
            set "PYTHON_EXE=!CHOSEN_PATH!\Scripts\pythonw.exe"
            echo !CHOSEN_PATH!> "%CONFIG_FILE%"
        ) else if exist "!CHOSEN_PATH!\Scripts\python.exe" (
            set "PYTHON_EXE=!CHOSEN_PATH!\Scripts\python.exe"
            echo !CHOSEN_PATH!> "%CONFIG_FILE%"
        ) else if exist "!CHOSEN_PATH!\venv\Scripts\pythonw.exe" (
            set "PYTHON_EXE=!CHOSEN_PATH!\venv\Scripts\pythonw.exe"
            echo !CHOSEN_PATH!\venv> "%CONFIG_FILE%"
        ) else if exist "!CHOSEN_PATH!\venv\Scripts\python.exe" (
            set "PYTHON_EXE=!CHOSEN_PATH!\venv\Scripts\python.exe"
            echo !CHOSEN_PATH!\venv> "%CONFIG_FILE%"
        ) else if exist "!CHOSEN_PATH!\.venv\Scripts\pythonw.exe" (
            set "PYTHON_EXE=!CHOSEN_PATH!\.venv\Scripts\pythonw.exe"
            echo !CHOSEN_PATH!\.venv> "%CONFIG_FILE%"
        ) else if exist "!CHOSEN_PATH!\.venv\Scripts\python.exe" (
            set "PYTHON_EXE=!CHOSEN_PATH!\.venv\Scripts\python.exe"
            echo !CHOSEN_PATH!\.venv> "%CONFIG_FILE%"
        ) else (
            echo Selected folder does not contain Scripts\pythonw.exe or python.exe.
            powershell -NoProfile -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show('The selected folder does not contain Scripts\pythonw.exe or python.exe.' + [Environment]::NewLine + 'Please select the Qwen-Image-2.1 folder containing venv.', 'Qwen Image Studio', 'OK', 'Error')"
            pause
            exit /b 1
        )
    ) else (
        echo Selection cancelled by user.
        pause
        exit /b 1
    )
)

:: Save detected path to config so next launches are instant
if defined PYTHON_EXE (
    if not exist "%CONFIG_FILE%" (
        for %%F in ("%PYTHON_EXE%\..\..") do echo %%~fF> "%CONFIG_FILE%"
    )
)

if not exist "%APP_DIR%launch_app.pyw" (
    echo Could not find %APP_DIR%launch_app.pyw. Ensure all files are extracted.
    pause
    exit /b 1
)

start "" "%PYTHON_EXE%" "%APP_DIR%launch_app.pyw"
exit /b
