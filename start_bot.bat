@echo off
echo Starting Lavalink server...
REM We use start /B to run Lavalink in the background without a new command window
start /B python start_lavalink.py

echo Waiting for Lavalink to initialize (10 seconds)...
timeout /t 10 /nobreak

echo Starting Discord bot...
REM Run the bot in the current window to see its output
python bot.py

REM The script will now terminate when the bot.py script terminates.
REM Removed the pause and final echo.