@echo off
rem Starts the Trade Depot capture mod. Double-click this file, or run it from a terminal.
rem The window stays open if the mod stops with an error, so you can read it.
cd /d "%~dp0"
py -3.13 system_capture.py
if errorlevel 1 pause
