@echo off
echo Starting Lavalink server...
start cmd /k "python start_lavalink.py"
timeout /t 10 /nobreak
echo Starting Discord bot...
start cmd /k "python bot.py"
echo Both processes started. Press any key to exit this window...
pause > nul 