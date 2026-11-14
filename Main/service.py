# -*- coding: utf-8 -*-
"""
Modus Sync - 24/7 Android Arka Plan Fiyat & Gösterge Alarm Servisi
Uygulama tamamen kapalıyken de her 2 dakikada bir piyasayı tarar ve kesişimlerde bildirim gönderir.
"""
import os
import sys
import time
import json
import math
import re
import requests

import i18n
import storage
from i18n import tr, trd
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from market_feed import YahooFeed, YAHOO_MACROS, MARKET_DYNAMICS, compute_dynamics
from fred_feed import FredStore, fetch_cnh_quote, required_series_for_names, mark_sync_errors
from alarm_logic import (alarm_key, evaluate_alarm, is_checkable, next_notification_id,
                         observe, save_changes)

print("[ModusService] Arka plan servisi baslatildi.")

def hex_color(h):
    return [1.0, 1.0, 1.0, 1.0]

def parse_metric_number(val_str):
    if not val_str:
        return 0.0
    s = str(val_str).replace(',', '').replace('%', '')
    match = re.search(r'[-+]?\d+(?:\.\d+)?', s)
    if match:
        try:
            return float(match.group(0))
        except Exception:
            return 0.0
    return 0.0

class ServiceNotificationEngine:
    CHANNEL_ID = "modus_alarms_channel"
    CHANNEL_NAME = "Modus Sync Alarmlar"

    @classmethod
    def send_notification(cls, title, message, subtext="Modus Sync Alarm"):
        try:
            from jnius import autoclass
            Context = autoclass('android.content.Context')
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            mActivity = PythonActivity.mActivity
            if not mActivity:
                # Service context
                PythonService = autoclass('org.kivy.android.PythonService')
                mService = PythonService.mService
                context = mService
            else:
                context = mActivity

            if not context:
                print(f"[Service Notif Fallback] {title} - {message}")
                return

            NotificationBuilder = autoclass('android.app.Notification$Builder')
            NotificationManager = autoclass('android.app.NotificationManager')
            NotificationChannel = autoclass('android.app.NotificationChannel')
            BuildVersion = autoclass('android.os.Build$VERSION')
            R = autoclass('android.R$drawable')

            notif_mgr = context.getSystemService(Context.NOTIFICATION_SERVICE)

            if BuildVersion.SDK_INT >= 26:
                importance = NotificationManager.IMPORTANCE_HIGH
                channel = NotificationChannel(cls.CHANNEL_ID, cls.CHANNEL_NAME, importance)
                channel.setDescription("Borsa ve GEX Fiyat/Gosterge Kesim Alarmlari")
                channel.enableVibration(True)
                channel.enableLights(True)
                notif_mgr.createNotificationChannel(channel)
                builder = NotificationBuilder(context, cls.CHANNEL_ID)
            else:
                builder = NotificationBuilder(context)

            builder.setContentTitle(str(title))
            builder.setContentText(str(message))
            if subtext:
                builder.setSubText(str(subtext))
            builder.setSmallIcon(R.stat_notify_more)
            builder.setAutoCancel(True)

            try:
                # Titreşim deseni
                builder.setVibrate([0, 500, 250, 500])
            except Exception:
                pass

            notif_id = next_notification_id()
            notif_mgr.notify(notif_id, builder.build())
            print(f"[Service Notification Sent] {title}: {message}")
        except Exception as e:
            print(f"[Service Notif Error] {e}")


class ServiceMarketFetcher:
    def __init__(self):
        self.feed = YahooFeed()

    def get_chart_history(self, sym, range_str='2d', interval='1d'):
        return [value for _, value in self.feed.observations(sym, range_str, interval)]

    def fetch_current_metrics(self, required_names=None):
        metrics_map = {}
        required = set(required_names or [])
        def needed(name, symbol=None):
            return not required or name in required or symbol in required

        observations = {}
        for name, sym in YAHOO_MACROS:
            if not needed(name, sym) and not (
                '10Y - 13 Haftalık Bono Faiz Farkı (yaklaşık, yüzde puan)' in required
                and sym in ('^TNX', '^IRX')
            ):
                continue
            item = self.feed.latest(sym)
            if item:
                metrics_map[name] = item['value']
                observations[sym] = item['value']
        if '^TNX' in observations and '^IRX' in observations:
            metrics_map['10Y - 13 Haftalık Bono Faiz Farkı (yaklaşık, yüzde puan)'] = observations['^TNX'] - observations['^IRX']

        # VIX Eğrisi
        if needed("VIX Eğrisi (Korku Yapısı)"):
            try:
                v_h = self.get_chart_history('^VIX', '1d')
                v3_h = self.get_chart_history('^VIX3M', '1d')
                if v_h and v3_h:
                    metrics_map["VIX Eğrisi (Korku Yapısı)"] = v3_h[-1] - v_h[-1]
            except Exception:
                pass

        # HYG/TLT
        if needed("HYG/TLT ETF Oranı Günlük Değişimi"):
            try:
                ratio = self.feed.ratio_change('HYG', 'TLT')
                if ratio:
                    metrics_map["HYG/TLT ETF Oranı Günlük Değişimi"] = ratio['change_pct']
            except Exception:
                pass

        # BTC
        if needed("BTC Günlük Değişimi"):
            try:
                btc = self.get_chart_history('BTC-USD', '5d')
                if len(btc) >= 2:
                    pct = ((btc[-1] - btc[-2]) / btc[-2]) * 100
                    metrics_map["BTC Günlük Değişimi"] = pct
            except Exception:
                pass

        # Bakır / Altın
        if needed("Bakır/Altın Vadeli Oranı Günlük Değişimi"):
            try:
                ratio = self.feed.ratio_change('HG=F', 'GC=F')
                if ratio:
                    metrics_map["Bakır/Altın Vadeli Oranı Günlük Değişimi"] = ratio['change_pct']
            except Exception:
                pass

        wanted = {key for key, label, *_ in MARKET_DYNAMICS if needed(label)}
        if wanted:
            try:
                for item in compute_dynamics(self.feed, wanted).values():
                    metrics_map[item['label']] = item['value']
            except Exception as exc:
                print(f"[Dynamics Error] {exc}")

        # Major Tickers (names match the app's GEX card names used as alarm symbols)
        assets = [
            ("S&P 500 (^GSPC)", "^GSPC"),
            ("Gold ETF (GLD)", "GLD"),
            ("Silver ETF (SLV)", "SLV"),
            ("Crude Oil ETF (USO)", "USO"),
            ("NDX (Nasdaq 100)", "^NDX"),
            ("NVDA (Nvidia)", "NVDA"),
            ("AAPL (Apple)", "AAPL"),
            ("TSLA (Tesla)", "TSLA")
        ]
        for name, sym in assets:
            if not needed(name, sym):
                continue
            h = self.get_chart_history(sym, '5d')
            if h:
                metrics_map[name] = h[-1]
                metrics_map[sym] = h[-1]

        fred_ids = required_series_for_names(required)
        if fred_ids:
            try:
                fred = FredStore()
                sync = fred.sync_many(fred_ids, workers=2)
                for item in mark_sync_errors(fred.metrics(), sync['errors']):
                    if item.get('value') is not None and not item.get('stale') and not item.get('sync_error') and needed(item['name'], item['id']):
                        metrics_map[item['name']] = item['value']
                        metrics_map[item['id']] = item['value']
            except Exception as exc:
                print(f"[FRED Alarm Error] {exc}")
        if needed('USD/CNH (Offshore)', 'CNH=X'):
            cnh = fetch_cnh_quote()
            if cnh and (datetime.now(timezone.utc).date() -
                        datetime.fromisoformat(cnh['date']).date()).days <= 10:
                metrics_map['USD/CNH (Offshore)'] = cnh['value']
                metrics_map['CNH=X'] = cnh['value']

        return metrics_map


def load_alarms():
    persistent = storage.data_path("alarms.json")
    paths = [
        persistent,
        "alarms.json",
        os.path.join(os.path.dirname(__file__), "alarms.json"),
        "/data/data/org.godmode.borsaradar/files/app/alarms.json"
    ]
    for p in paths:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f), p
            except Exception:
                pass
    return [], persistent

def save_alarms(alarms, path, changes=None):
    """Re-read the file so alarms the app added/edited meanwhile are not overwritten."""
    try:
        if changes is None:
            changes = {alarm_key(a): a for a in alarms}
        save_changes(path, alarms, changes)
    except Exception as e:
        print(f"[Save Alarms Error] {e}")


def check_and_trigger_alarms():
    alarms, path = load_alarms()
    active_alarms = [a for a in alarms if is_checkable(a)]
    if not active_alarms:
        return

    print(f"[ModusService] {len(active_alarms)} aktif alarm kontrol ediliyor...")
    fetcher = ServiceMarketFetcher()
    current_metrics = fetcher.fetch_current_metrics({a.get('symbol') for a in active_alarms})

    changes = {}
    for a in active_alarms:
        sym = a.get('symbol')
        cur_val = current_metrics.get(sym)
        if cur_val is None:
            continue
        cur_val = float(cur_val)
        previous = a.get('last_seen_value', a.get('last_price'))
        # GEX levels come from the latest app scan stored on the alarm (max 24h old).
        is_triggered, title, msg = evaluate_alarm(a, cur_val)
        alarm_changes = observe(a, cur_val, is_triggered)
        if is_triggered or previous != cur_val:
            changes[alarm_key(a)] = alarm_changes
        if is_triggered:
            ServiceNotificationEngine.send_notification(
                title or tr("ALARM TETIKLENDI: {sym}", sym=trd(sym)),
                a.get('note') or msg,
                subtext="Modus Sync Radar"
            )

    if changes:
        save_alarms(alarms, path, changes)


def main_loop():
    i18n.set_language(i18n.load_language(storage.data_path(i18n.PREFS_FILE)))
    print("[ModusService] 2 dakikalik arka plan alarm dongusu basladi.")
    while True:
        try:
            check_and_trigger_alarms()
        except Exception as e:
            print(f"[ModusService Cycle Error] {e}")
        time.sleep(120)  # 2 dakika bekleme


if __name__ == '__main__':
    main_loop()
