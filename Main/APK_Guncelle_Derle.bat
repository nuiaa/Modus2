@echo off
chcp 65001 >nul
echo ========================================================
echo   BORSA RADAR - APK DERLEME VE GUNCELLEME BASLATILIYOR
echo ========================================================
echo.
echo WSL Ubuntu uzerinde Buildozer calistiriliyor...
rem Betigin bulundugu klasorden calistir; kullaniciya ozel sabit yol yok.
wsl -d Ubuntu --cd "%~dp0." -e bash build_native.sh
if errorlevel 1 (
    echo.
    echo HATA: APK derlemesi basarisiz oldu. Yukaridaki hata mesajini kontrol edin.
    pause
    exit /b 1
)
echo.
echo ========================================================
echo   ISLEM TAMAMLANDI! APK: %~dp0..\APK
echo ========================================================
pause
