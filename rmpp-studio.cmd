@echo off
rem Start rmpp-studio without a console window (needs Python 3 with Pillow on PATH).
start "" pythonw "%~dp0rmpp-studio.pyw" %*
