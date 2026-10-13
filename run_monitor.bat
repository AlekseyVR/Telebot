@echo off

:: IMPORTANT: Path to your project folder
cd /d "D:\GitHub\Telebot\"

title Telegram Server Monitor

:loop
echo [%date% %time%] Starting monitoring bot...

".venv\Scripts\python.exe" avr_telebot.py

echo [%date% %time%] Script crashed or closed. Restarting in 5 seconds...
timeout /t 5
goto loop