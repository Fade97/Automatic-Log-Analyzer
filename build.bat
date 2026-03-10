@echo off
echo Installing PyInstaller...
pip install pyinstaller

echo Building executable...
pyinstaller --onefile --name log-analyzer analyze.py

echo.
echo Done! Executable is at dist\log-analyzer.exe
