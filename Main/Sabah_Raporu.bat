@echo off
chcp 65001
title Sabah Opsiyon Duvarlari Raporu
color 0A

echo Rapor hazirlaniyor, IBKR Gateway uzerinden veriler cekiliyor...
echo Lutfen bekleyin...
echo.

cd /d "%~dp0"
python sabah_duvarlari.py

echo.
echo Islem tamamlandi. Cikmak icin bir tusa basin...
pause >nul
