@echo off
echo Installing PyInstaller...
python -m pip install pyinstaller

echo Installing dependencies...
python -m pip install -r requirements.txt

echo Building executable...
python -m PyInstaller --onefile --name log-analyzer analyze/__main__.py

echo.
echo Done! Executable is at dist\log-analyzer.exe
