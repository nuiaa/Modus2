#!/bin/bash
set -e
export PATH=$PATH:~/.local/bin
export PIP_BREAK_SYSTEM_PACKAGES=1

echo "========================================================"
echo "  BORSA RADAR - NATIVE APK DERLEME (CACHE TEMIZLEMELI)  "
echo "========================================================"

mkdir -p ~/borsa_app
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 1. Windows'taki en guncel dosyalari kopyala
echo "[1/4] Guncel kod dosyalari Linux alanina aktariliyor..."
# Elle yazilmis liste yeni modulleri unutuyordu (extra_feeds.py eksik kalinca uygulama acilista coktu);
# testler ve masaustu araclari (pandas/streamlit kullanir, uygulama import etmez) disindaki tum .py dosyalarini kopyala.
# Eski calismalardan kalan .py dosyalari APK'ya girmesin
rm -f ~/borsa_app/*.py
for source in "$script_dir"/*.py; do
    case "$(basename "$source")" in
        test_*.py|sabah_duvarlari.py|streamlit_app.py|mobile_app.py) ;;
        *) cp -f "$source" ~/borsa_app/ ;;
    esac
done
cp -f "$script_dir/buildozer.spec" ~/borsa_app/
# Arayuz cevirileri ve Arapca font
rm -rf ~/borsa_app/locales ~/borsa_app/fonts
cp -r "$script_dir/locales" "$script_dir/fonts" ~/borsa_app/
cp -f "$script_dir/"*.png ~/borsa_app/ 2>/dev/null || true

cd ~/borsa_app

# 2. Eski onbellegi temizle (Yeni main.py ve iconlarin APK'ya zorunlu girmesini sagla)
echo "[2/4] Eski buildozer uygulama onbellegi temizleniyor..."
rm -rf ~/borsa_app/.buildozer/android/app
rm -rf ~/borsa_app/bin/*
rm -rf ~/borsa_app/.buildozer/android/platform/build-arm64-v8a_armeabi-v7a/dists/borsaradar/src/main/res/mipmap*
# Bayat bir Gradle daemon'i AAPT2'yi baslatamayabilir ("Daemon startup failed"); her derlemede durdur.
dist_dir=~/borsa_app/.buildozer/android/platform/build-arm64-v8a_armeabi-v7a/dists/borsaradar
if [ -x "$dist_dir/gradlew" ]; then
    (cd "$dist_dir" && ./gradlew --stop >/dev/null 2>&1) || true
fi

# 3. Buildozer ile APK derle
echo "[3/4] Buildozer Android APK derleniyor..."
buildozer android debug

# 4. Projenin APK klasorune aktar
output_dir="$(dirname "$script_dir")/APK"
mkdir -p "$output_dir"
echo "[4/4] Yeni APK $output_dir klasorune kopyalaniyor..."
cp -f bin/*.apk "$output_dir/"

echo "========================================================"
echo "  TEBRIKLER! Guncel APK $output_dir klasorune aktarildi."
echo "========================================================"
