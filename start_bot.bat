@echo off
start cmd /k "python start_lavalink.py"
timeout /t 5
start cmd /k "python bot.py" 