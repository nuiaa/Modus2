"""
Modus Sync - Wall Street Profesyonel Terminali & Modus AI Asistani
V9: Modern Glassmorphic UI, Gelismis Radius & TradingView Temasi
"""
import os
import sys
import math
import json
import re
import threading
import time
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from concurrent.futures import ThreadPoolExecutor

from market_feed import YahooFeed, YAHOO_MACROS, MARKET_DYNAMICS, compute_dynamics
from fred_feed import FredStore, FRED_GROUPS, fetch_cnh_quote, mark_sync_errors, default_database_path as fred_database_path
from ai_client import AIClientError, fetch_models, probe_connection, send_chat
from market_trends import MarketTrendStore
from analysis_focus import FRED_LEVEL_SERIES, fred_for_focus, levels_for_focus, resolve_focus, symbols_for_focus
from macro_analytics import dated_correlation, matched_ratio
from context_features import (format_gex_position, format_history_position, format_sma_position,
                              gex_position, history_position, parse_level, sma_position)
from external_feed import ExternalMacroFeed, cross_metrics, GROUP_ORDER as EXTERNAL_GROUP_ORDER
from extra_feeds import fetch_headlines, parse_week_calendar
from gex import dollar_gamma, expiry_date, gamma_flip, years_to_expiry
from alarm_logic import (GEX_CONDITIONS, alarm_key, evaluate_alarm, is_checkable, next_notification_id,
                         observe, read_alarms, save_changes, write_alarms)

import i18n
from i18n import tr, trd

from kivy.core.window import Window
Window.softinput_mode = 'below_target'
import ui_text

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.image import Image
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.widget import Widget
from kivy.uix.textinput import TextInput
from kivy.uix.scrollview import ScrollView
from kivy.uix.modalview import ModalView
from kivy.uix.screenmanager import NoTransition, ScreenManager, Screen, SlideTransition
from kivy.clock import Clock
from kivy.utils import get_color_from_hex
from kivy.metrics import dp
from kivy.graphics import Color, Rectangle, RoundedRectangle, Line, Ellipse
from kivy.core.clipboard import Clipboard
import theme
from ui_style import (Background, Checkmark, Chevron, Hairline, IconButton, LargeTitleHeader, ModernButton,
                      ModernTextInput, ResponsiveLabel, SectionLabel, SegmentedControl, SendButton,
                      Sheet, StatusPill, Surface, TabBar, TextAction)

# Colour names (WHITE, CARD_BG, BLUE, ...) are semantic tokens kept current by theme.
theme.register(globals())


def hex_color(h):
    return get_color_from_hex(theme.resolve(h))


def markup_hex(h):
    """Colour for [color=...] markup (no alpha), resolved to the active theme."""
    return theme.resolve(h)[:7]


def themed_icon(name):
    return f'{name}_dark.png' if theme.name == 'dark' else f'{name}.png'


def centered(widget):
    holder = AnchorLayout(size_hint_x=None, width=widget.width, anchor_y='center')
    holder.add_widget(widget)
    return holder


def bell_icon_source():
    return themed_icon('bell')


# ---------------------------------------------------------
# METRİK EĞİTİCİ SÖZLÜĞÜ
# ---------------------------------------------------------
METRIC_EXPLANATIONS = {
    "ABD 5 Yıllık Tahvil Faizi (%)": "ABD 5 yıllık tahvil faizidir; 2 yıllık faizle aynı gösterge değildir.",
    "10-Year Yield": "Dunyanin en onemli risksiz faiz gostergesidir. Global degerleme modellerinin temelidir.",
    "30-Year Yield": "Uzun vadeli enflasyon ve buyume beklentilerini gosterir.",
    "VIX Endeksi": "S&P 500 opsiyonlarina dayali 30 gunluk oynaklik beklentisidir ('Korku Endeksi').",
    "MOVE Endeksi (Tahvil Korkusu)": "Tahvil piyasasinin VIX'idir. Tahvildeki stres hisse senetlerinden once buraya yansir.",
    "TIP (Reel Faiz Stresi)": "Enflasyona endeksli ABD tahvilidir. TIP dususu altin ve hisseler icin negatif baskidir.",
    "EEM (Gelişen Piyasalar Likiditesi)": "Gelisen piyasalar ETF'idir. Global dolar likiditesini gosterir.",
    "Dolar Endeksi (DXY)": "Dolarin 6 major para birimine karsi gucudur. 100 uzeri risk istahini azaltir.",
    "VIX Eğrisi (Korku Yapısı)": "VIX ile VIX3M kontratlari farkidir. Contango sakin, Backwardation panik gostergesidir.",
    "Volatilite Skew (Çöküş Sigortası)": "Put IV / Call IV oranidir. 1.30 uzeri kurumsal cokus sigortasi alimini gosterir.",
    "S&P 500 Put/Call Oranı (PCR)": "Put hacminin Call hacmine oranidir. 1.0 uzeri asiri korku ve satis baskisidir.",
    "Filin Ayak İzi (Balina İşlemi)": "Gun icinde tek bir strike'ta acilan en buyuk kurumsal opsiyon hacmidir.",
    "Çöp Tahvil Stresi (HYG/TLT)": "Riskli sirket tahvillerinin hazine tahviline oranidir. Artis risk istahini gosterir.",
    "Kripto Öncü Sinyali (BTC)": "Bitcoin 7/24 islem gordugu icin piyasa oncesi en hizli likidite sinyalidir.",
    "Doktor Bakır / Altın (Resesyon)": "Bakir/Altin orani dususu kuresel resesyon riskini isaret eder.",
    "Piyasa Genişliği (Dow > 50MA)": "Dow Jones hisselerinin yuzde kacinin 50 gunluk ortalamasinin uzerinde oldugudur.",
    "Put Wall (Destek Duvarı)": "Market Maker'larin en buyuk Put gamma yukumlulugudur. Guclu taban destektir.",
    "Call Wall (Direnç Duvarı)": "Market Maker'larin en buyuk Call gamma tasidigi tavan direnc seviyesidir.",
    "Gamma Flip (Rejim Sınırı)": "Pozitif ve Negatif Gamma arasindaki kirilma cizgisidir. Uzeri sakin, alti selaledir.",
    "Net GEX": "Piyasa yapicilarin toplam net gamma maruziyetidir. Pozitif olmasi tamponlu piyasadir."
}


# ---------------------------------------------------------
# GLOBAL HAFIZA & AYARLAR (STORAGE & STATE)
# ---------------------------------------------------------
# ---------------------------------------------------------
class AppState:
    last_market_data = {}
    config_file = "ai_config.json"
    market_cache_file = "market_cache.json"
    engine_mode = "free"     # "free" (Dahili Quant) veya "custom" (Kendi API'si)
    api_provider = "gemini"
    api_key = ""
    provider_configs = {}
    thinking_level = 2       # 1: Hizli, 2: Derin Quant, 3: Hedge Fonu (Maksimum Dusunme)
    selected_model = ""
    available_models = []

    @classmethod
    def load_all(cls):
        try:
            if os.path.exists(cls.config_file):
                with open(cls.config_file, "r", encoding="utf-8") as f:
                    d = json.load(f)
                    cls.engine_mode = d.get("engine_mode", "free")
                    cls.api_provider = d.get("provider", "gemini")
                    cls.api_key = d.get("key", "")
                    cls.provider_configs = d.get("provider_configs", {})
                    if cls.api_key and cls.api_provider not in cls.provider_configs:
                        cls.provider_configs[cls.api_provider] = {"key": cls.api_key, "model": d.get("selected_model", ""), "models": d.get("available_models", [])}
                    cls.thinking_level = d.get("thinking_level", 2)
                    cls.selected_model = d.get("selected_model", "")
                    cls.available_models = d.get("available_models", [])
        except Exception:
            pass

        try:
            if os.path.exists(cls.market_cache_file):
                with open(cls.market_cache_file, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                    cls.last_market_data = cached if market_data_is_fresh(cached) else {}
        except Exception:
            pass

    @classmethod
    def save_config(cls, engine_mode, provider, key, thinking_level, selected_model=None, available_models=None):
        cls.engine_mode = engine_mode
        cls.api_provider = provider
        cls.api_key = key
        cls.provider_configs[provider] = {"key": key, "model": selected_model or cls.selected_model, "models": available_models if available_models is not None else cls.available_models}
        cls.thinking_level = thinking_level
        if selected_model:
            cls.selected_model = selected_model
        if available_models is not None:
            cls.available_models = available_models
        try:
            with open(cls.config_file, "w", encoding="utf-8") as f:
                json.dump({
                    "engine_mode": engine_mode,
                    "provider": provider,
                    "key": key,
                    "thinking_level": thinking_level,
                    "selected_model": cls.selected_model,
                    "available_models": cls.available_models,
                    "provider_configs": cls.provider_configs
                }, f)
        except Exception:
            pass

    @classmethod
    def save_market_data(cls, data):
        cls.last_market_data = data
        try:
            with open(cls.market_cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except Exception:
            pass


def market_data_is_fresh(data, max_age_seconds=300):
    if not data or not (data.get('macro_observations') or
                       any(item.get('value') is not None and not item.get('stale') and not item.get('sync_error')
                           for item in data.get('fred_metrics', []))):
        return False
    try:
        fetched = datetime.fromisoformat(data['fetched_at'])
        return 0 <= (datetime.now(timezone.utc) - fetched).total_seconds() <= max_age_seconds
    except (KeyError, TypeError, ValueError):
        return False


# ---------------------------------------------------------
# AI PROVIDER CONNECTION AND CONVERSATION
# ---------------------------------------------------------
def sanitize_api_key(key):
    return str(key or "").strip().strip('"').strip("'").strip()


def display_ai_text(value):
    """Convert the small Markdown subset models commonly emit to readable plain text."""
    value = str(value)
    value = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", value)
    value = re.sub(r"(?m)^\s*[-*]\s+", "• ", value)
    value = re.sub(r"\*\*(.*?)\*\*|__(.*?)__", lambda match: match.group(1) or match.group(2), value)
    value = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", value)
    return value.replace("`", "")


def fetch_available_models(api_key, provider):
    return fetch_models(sanitize_api_key(api_key), provider)


def test_api_connection(key, provider, callback):
    """Test candidate credentials without changing working settings on failure."""
    def worker():
        clean_key = sanitize_api_key(key)
        if not clean_key:
            Clock.schedule_once(lambda dt: callback(False, tr("API anahtarını girin."), clean_key, provider, "", []))
            return
        try:
            models = fetch_available_models(clean_key, provider)
            if not models:
                raise AIClientError("Bu sağlayıcıda uygun metin modeli bulunamadı.")
            saved_model = AppState.provider_configs.get(provider, {}).get("model")
            ok, reply, tag, model = probe_connection(clean_key, provider, models, saved_model)
            if ok:
                Clock.schedule_once(lambda dt: callback(True, tr("{name} bağlantısı kuruldu.", name=tag), clean_key, provider, model, models))
            else:
                Clock.schedule_once(lambda dt: callback(False, trd(reply), clean_key, provider, model, models))
        except AIClientError as exc:
            Clock.schedule_once(lambda dt: callback(False, trd(str(exc)), clean_key, provider, "", []))
        except Exception:
            Clock.schedule_once(lambda dt: callback(False, tr("Bağlantı kurulamadı. Ağınızı ve anahtarı denetleyin."), clean_key, provider, "", []))
    threading.Thread(target=worker, daemon=True).start()


def query_ai_service(user_prompt, market_context, callback, special_mode=None, chat_history=None):
    """Send bounded dialogue and the latest dated market snapshot."""
    provider, model, key = AppState.api_provider, AppState.selected_model, sanitize_api_key(AppState.api_key)
    history = list(chat_history or [])[-12:]
    messages = history + [{"role": "user", "content": str(user_prompt)}]
    detail = {1: "Kısa yanıt ver.", 2: "Gerekçeli ve anlaşılır analiz yap.",
              3: "Birden çok senaryo, varsayım ve riskleri açıkla."}.get(AppState.thinking_level, "Gerekçeli analiz yap.")
    mode = {"summary": "Erişilebilen piyasa verilerini özetle.",
            "spx_plan": "S&P 500 verilerini ve varsa opsiyon verilerini değerlendir."}.get(special_mode, "")
    language = i18n.ai_language_name()
    system = (
        f"Piyasa analizi asistanısın. Kullanıcının uygulama dili {language}; "
        f"always write your entire answer in {language}, even though the data below is in Turkish. "
        "Kısa takip sorularını önceki konuşmadaki varlığa ve konuya bağla; gerçekten belirsizse sor. "
        "Kullanıcının sorduğu varlığa odaklan; ilgisiz GEX veya S&P 500 analizine kayma. "
        "Veri ile yorumunu ayır. Yalnızca sağlanan tarihli gözlemleri kullan; eksik veya eski veriyi güncel sayma. "
        "Fiyatın 1 ay, 3 ay ve 1 yıl karşılaştırmalarını yalnızca verilen baz tarihlerle yorumla. "
        "Hareketi açıklamak için ilgili reel faiz, enflasyon beklentisi, dolar veya finansal koşulların aynı dönem değişimlerini incele. "
        "Eş hareketi nedensellik diye sunma; mekanizma, karşı kanıt, eksik veri ve izlenecek göstergeleri açıkla. "
        "SMA, 52 hafta aralığı ve düşüşü yalnızca mevcutsa teknik bağlam olarak kullan. "
        "GEX için geçmiş zaman serisi yoksa geçmiş GEX trendi iddia etme. "
        "Kesin fiyat hedefi, opsiyon duvarı veya veri uydurma. Uzun vadede koşullu senaryolar, varsayımlar ve riskleri açıkla. "
        "Düz metin kullan; Markdown başlığı, yıldız veya köşeli biçimlendirme kullanma. "
        + detail + " " + mode + f" Answer in {language}."
        + "\n\nGÜNCEL PİYASA GÖZLEMLERİ:\n" + str(market_context)
    )
    def worker():
        if not key or not model:
            Clock.schedule_once(lambda dt: callback(tr("Ayarlar bölümünden API anahtarını ve modeli bağlayın."), RED, tr("Sistem"), False))
            return
        try:
            ok, answer, tag = send_chat(key, provider, model, messages, system)
            Clock.schedule_once(lambda dt: callback(answer if ok else trd(answer), WHITE if ok else RED, tag, ok))
        except Exception:
            Clock.schedule_once(lambda dt: callback(tr("Yapay zeka bağlantısında hata oluştu."), RED, tr("Sistem"), False))
    threading.Thread(target=worker, daemon=True).start()


class ModernAISettingsModal(Sheet):
    def __init__(self, on_success_callback=None, **kwargs):
        super(ModernAISettingsModal, self).__init__(tr("Yapay zekâ bağlantısı"),
                                                    height=min(Window.height * 0.9, dp(470)), **kwargs)
        self.on_success_callback = on_success_callback
        self.cur_thinking = AppState.thinking_level if AppState.thinking_level else 2
        self.chosen_provider = AppState.api_provider
        layout = self.body

        layout.add_widget(ResponsiveLabel(text=tr("Sağlayıcıyı seçin ve API anahtarınızı girin."),
                                          font_size='14sp', color=hex_color(GRAY_LIGHT), min_height=22))

        options = [("gemini", "Gemini"), ("openai", "GPT"), ("anthropic", "Claude"), ("openrouter", "OpenRouter")]
        selected = self.chosen_provider if self.chosen_provider in dict(options) else "gemini"
        self.provider_control = SegmentedControl(options, selected, on_change=self._select_provider)
        layout.add_widget(self.provider_control)

        key_row = BoxLayout(orientation='horizontal', size_hint_y=None, height=dp(50), spacing=dp(8))
        self.key_input = ModernTextInput(text=AppState.api_key, hint_text=tr("API anahtarı"),
                                         multiline=False, password=True)
        key_row.add_widget(self.key_input)
        paste_btn = ModernButton(text=tr("Yapıştır"), font_size='15sp', size_hint_x=None, width=dp(96),
                                 bg_hex=FILL, color=hex_color(BLUE))
        paste_btn.bind(on_press=self._paste_clipboard)
        key_row.add_widget(paste_btn)
        layout.add_widget(key_row)

        self.status_lbl = ResponsiveLabel(text=tr("Anahtar yalnızca bu cihazda saklanır."),
                                          font_size='13sp', color=hex_color(GRAY_LIGHT), min_height=40)
        layout.add_widget(self.status_lbl)
        layout.add_widget(Widget())

        self.connect_btn = ModernButton(text=tr("Bağlan ve devam et"), font_size='16sp',
                                        size_hint_y=None, height=dp(50), bg_hex=BLUE, radius_val=12)
        self.connect_btn.bind(on_press=self._on_connect_and_proceed)
        layout.add_widget(self.connect_btn)

    def _select_provider(self, provider):
        self.chosen_provider = provider
        self.key_input.text = AppState.provider_configs.get(provider, {}).get("key", "")
        self.status_lbl.text = tr("{name} anahtarını girin.", name=dict(PROVIDERS_UI).get(provider, provider))
        self.status_lbl.color = hex_color(GRAY_LIGHT)

    def _paste_clipboard(self, *args):
        try:
            p = Clipboard.paste()
            if p:
                self.key_input.text = p.strip()
                self.status_lbl.text = tr("Panodan yapıştırıldı. Bağlanmak için aşağıdaki düğmeye dokunun.")
                self.status_lbl.color = hex_color(GRAY_LIGHT)
        except Exception:
            pass

    def _on_connect_and_proceed(self, *args):
        k = sanitize_api_key(self.key_input.text)
        if not k:
            self.status_lbl.text = tr("Bir API anahtarı girin veya panodan yapıştırın.")
            self.status_lbl.color = hex_color(RED)
            return
        self.status_lbl.text = tr("Bağlantı test ediliyor…")
        self.status_lbl.color = hex_color(GRAY_LIGHT)
        self.connect_btn.disabled = True
        test_api_connection(k, self.chosen_provider, self._on_connect_done)

    def _on_connect_done(self, ok, msg, valid_key, provider, model, models):
        self.connect_btn.disabled = False
        if ok:
            self.status_lbl.text = msg + " " + tr("Sohbete geçiliyor…")
            self.status_lbl.color = hex_color(GREEN)
            self.key_input.text = valid_key
            AppState.save_config("custom", provider, valid_key, self.cur_thinking, selected_model=model, available_models=models)
            Clock.schedule_once(lambda dt: self._finish_success(), 0.35)
        else:
            self.status_lbl.text = msg
            self.status_lbl.color = hex_color(RED)

    def _finish_success(self):
        self.dismiss()
        if self.on_success_callback:
            self.on_success_callback()


PROVIDERS_UI = (("gemini", "Gemini"), ("openai", "OpenAI"), ("anthropic", "Claude"), ("openrouter", "OpenRouter"))


class ListRow(ButtonBehavior, BoxLayout):
    """Tappable grouped-list row: title, optional subtitle, trailing text and chevron/check."""
    def __init__(self, title, subtitle="", trailing="", trailing_color=None, accessory="chevron",
                 title_markup=False, **kwargs):
        kwargs.setdefault('orientation', 'horizontal')
        kwargs.setdefault('size_hint_y', None)
        kwargs.setdefault('padding', (dp(16), dp(10), dp(14), dp(10)))
        kwargs.setdefault('spacing', dp(10))
        super(ListRow, self).__init__(**kwargs)
        with self.canvas.before:
            self._press = Color(0, 0, 0, 0)
            self._press_rect = Rectangle()
        self.bind(pos=self._sync, size=self._sync, state=self._paint)
        texts = BoxLayout(orientation='vertical', spacing=dp(2))
        self.title_label = ResponsiveLabel(text=str(title), font_size='16sp', markup=title_markup)
        texts.add_widget(self.title_label)
        self.subtitle_label = None
        if subtitle:
            self.subtitle_label = ResponsiveLabel(text=str(subtitle), font_size='13sp', color=hex_color(GRAY_LIGHT))
            texts.add_widget(self.subtitle_label)
        self.add_widget(texts)
        if trailing:
            tail = Label(text=str(trailing), font_size='15sp', color=hex_color(trailing_color or GRAY_LIGHT),
                         size_hint_x=None, halign='right', valign='middle')
            # Single line, sized to its text (no text_size, so it never wraps).
            tail.bind(texture_size=lambda inst, size: setattr(inst, 'width', min(size[0], dp(190))))
            self.add_widget(tail)
        if accessory == "chevron":
            holder = AnchorLayout(size_hint_x=None, width=dp(14))
            holder.add_widget(Chevron())
            self.add_widget(holder)
        elif accessory == "check":
            holder = AnchorLayout(size_hint_x=None, width=dp(20))
            holder.add_widget(Checkmark())
            self.add_widget(holder)

        def fit(*_):
            content = self.title_label.height + (self.subtitle_label.height + dp(2) if self.subtitle_label else 0)
            self.height = max(dp(48), content + dp(20))
        self.title_label.bind(height=fit)
        if self.subtitle_label:
            self.subtitle_label.bind(height=fit)
        Clock.schedule_once(fit, 0)

    def _sync(self, *args):
        self._press_rect.pos = self.pos
        self._press_rect.size = self.size

    def _paint(self, *args):
        self._press.rgba = hex_color(theme.palette['fill_pressed']) if self.state == 'down' else (0, 0, 0, 0)


class GroupedList(Surface):
    """Card of rows separated by inset hairlines (iOS inset-grouped table)."""
    def __init__(self, **kwargs):
        kwargs.setdefault('size_hint_y', None)
        kwargs.setdefault('padding', 0)
        kwargs.setdefault('spacing', 0)
        super(GroupedList, self).__init__(radius_val=12, **kwargs)
        self.bind(minimum_height=self.setter('height'))
        self.row_count = 0

    def add_row(self, row):
        if self.row_count:
            self.add_widget(Hairline())
        self.row_count += 1
        self.add_widget(row)
        return row


def scrolling_list():
    """ScrollView containing a vertical stack that sizes to its content."""
    scroll = ScrollView(do_scroll_x=False, do_scroll_y=True, bar_width=dp(3))
    stack = GridLayout(cols=1, spacing=dp(8), size_hint_y=None, padding=(0, 0, 0, dp(12)))
    stack.bind(minimum_height=stack.setter('height'))
    scroll.add_widget(stack)
    return scroll, stack


# ---------------------------------------------------------
# MODEL SEÇİMİ
# ---------------------------------------------------------
class ModelSelectorModal(Sheet):
    def __init__(self, on_selected_callback=None, **kwargs):
        super(ModelSelectorModal, self).__init__(tr("Model"), height_ratio=0.75, **kwargs)
        self.on_selected_callback = on_selected_callback
        scroll, stack = scrolling_list()
        group = GroupedList()
        models = AppState.available_models
        if not models:
            group.add_row(ListRow(tr("Model listesi boş"), tr("Ayarlardan yeniden bağlanın."), accessory=None))
        for m in models:
            m_id = m.get('id', '')
            row = ListRow(m.get('name', m_id), trd(m.get('desc', '')),
                          accessory="check" if m_id == AppState.selected_model else None)

            def _make_select(selected_id):
                def _select(*a):
                    AppState.selected_model = selected_id
                    AppState.save_config(AppState.engine_mode, AppState.api_provider, AppState.api_key,
                                         AppState.thinking_level, selected_model=selected_id)
                    self.dismiss()
                    if self.on_selected_callback:
                        self.on_selected_callback(selected_id)
                return _select
            row.bind(on_press=_make_select(m_id))
            group.add_row(row)
        stack.add_widget(group)
        self.body.add_widget(scroll)


# ---------------------------------------------------------
# ANDROID YEREL BİLDİRİM MOTORU (Pyjnius Notification Engine)
# ---------------------------------------------------------
class NotificationEngine:
    _channel_created = False

    @classmethod
    def init_engine(cls):
        """Android 13+ izin kontrolü ve bildirim kanalını başlatır."""
        try:
            from kivy.utils import platform
            if platform == 'android':
                from android.permissions import request_permissions, Permission
                request_permissions([
                    Permission.POST_NOTIFICATIONS,
                    Permission.VIBRATE,
                    Permission.WAKE_LOCK
                ])
                cls._create_notification_channel()
        except Exception as e:
            print(f"[NotificationEngine] Init error: {e}")

    @classmethod
    def _create_notification_channel(cls):
        if cls._channel_created:
            return
        try:
            from kivy.utils import platform
            if platform == 'android':
                from jnius import autoclass
                from android import mActivity
                
                Build = autoclass('android.os.Build$VERSION')
                if Build.SDK_INT >= 26:
                    Context = autoclass('android.content.Context')
                    NotificationChannel = autoclass('android.app.NotificationChannel')
                    NotificationManager = autoclass('android.app.NotificationManager')
                    String = autoclass('java.lang.String')

                    channel_id = String("modus_sync_alerts")
                    channel_name = String(tr("Modus Sync Borsa Alarmlari"))
                    importance = NotificationManager.IMPORTANCE_HIGH

                    channel = NotificationChannel(channel_id, channel_name, importance)
                    channel.setDescription(tr("Kritik GEX Seviyeleri ve Ozel Fiyat Alarmlari"))
                    channel.enableVibration(True)
                    channel.enableLights(True)

                    notification_service = mActivity.getSystemService(Context.NOTIFICATION_SERVICE)
                    notification_service.createNotificationChannel(channel)
                    cls._channel_created = True
        except Exception as e:
            print(f"[NotificationEngine] Channel error: {e}")

    @classmethod
    def send_notification(cls, title, message, subtext="Modus Sync"):
        """Android durum çubuğuna başlık, mesaj ve ikonla zengin bildirim gönderir."""
        try:
            from kivy.utils import platform
            if platform == 'android':
                cls._create_notification_channel()
                from jnius import autoclass
                from android import mActivity

                Context = autoclass('android.content.Context')
                Intent = autoclass('android.content.Intent')
                PendingIntent = autoclass('android.app.PendingIntent')
                NotificationCompat = autoclass('androidx.core.app.NotificationCompat$Builder')
                String = autoclass('java.lang.String')

                package_manager = mActivity.getPackageManager()
                app_intent = package_manager.getLaunchIntentForPackage(mActivity.getPackageName())
                if app_intent:
                    app_intent.setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP)
                    # FLAG_IMMUTABLE = 0x04000000 | FLAG_UPDATE_CURRENT = 0x08000000
                    pending_intent = PendingIntent.getActivity(mActivity, 0, app_intent, 0x04000000 | 0x08000000)
                else:
                    pending_intent = None

                app_info = mActivity.getApplicationInfo()
                icon_res_id = app_info.icon

                builder = NotificationCompat(mActivity, String("modus_sync_alerts"))
                builder.setContentTitle(String(str(title)))
                builder.setContentText(String(str(message)))
                builder.setSubText(String(str(subtext)))
                builder.setSmallIcon(icon_res_id)
                builder.setAutoCancel(True)
                if pending_intent:
                    builder.setContentIntent(pending_intent)
                builder.setPriority(NotificationCompat.PRIORITY_HIGH)
                builder.setDefaults(NotificationCompat.DEFAULT_ALL)

                manager = mActivity.getSystemService(Context.NOTIFICATION_SERVICE)
                notification_id = next_notification_id()
                manager.notify(notification_id, builder.build())
                print(f"[NotificationEngine] Bildirim gonderildi: {title} - {message}")
                return True
            else:
                print(f"[Masaustu Bildirim] {title}: {message}")
                return True
        except Exception as e:
            print(f"[NotificationEngine] Gonderim hatasi: {e}")
            return False


# ---------------------------------------------------------
# ---------------------------------------------------------
# TERMİNAL METRİKLERİ VE HESAPLANAN ENDEKSLERİN AYRIŞTIRILMASI
# ---------------------------------------------------------
def parse_metric_number(val_str):
    if not val_str or str(val_str).startswith('Veri yok'):
        return None
    s = str(val_str)
    
    # VIX eğrisi alarmı, spot VIX yerine VIX3M-VIX farkını izler.
    m_curve = re.search(r'VIX3M-VIX:\s*([-+]?\d+(?:\.\d+)?)', s)
    if m_curve:
        return float(m_curve.group(1))

    # Eski önbellekteki eğri metinleri alarm verisi değildir.
    if 'VIX:' in s and 'VIX3M:' in s:
        return None

    # 1. VIX Eğrisi: eski metinler kullanılmaz.
    m_vix = re.search(r'VIX:\s*([0-9]+\.?[0-9]*)', s)
    if m_vix:
        try: return float(m_vix.group(1))
        except Exception: pass

    # 2. Balina İşlemi: "7750.0 CALL" -> 7750.0
    m_call = re.search(r'([0-9]+\.?[0-9]*)\s*(CALL|PUT)', s, re.IGNORECASE)
    if m_call:
        try: return float(m_call.group(1))
        except Exception: pass

    # 3. Yüzde, işaret ve parantez temizleme ("+0.42% (Risk-On)", "-1.69%", "1.25 (Aşırı Korku)", "%53 Katılım")
    clean = s.replace('%', '').replace(',', '').strip()
    m_num = re.search(r'[-+]?[0-9]*\.?[0-9]+', clean)
    if m_num:
        try: return float(m_num.group(0))
        except Exception: return None
    return None


def get_terminal_metrics(data=None):
    if not data:
        data = AppState.last_market_data or {}
    metrics = []

    # 1. Sabah Makro Göstergeleri ((i) Simgeli Endeksler)
    for item in data.get('macros', []):
        name = item[0]
        val_str = str(item[1])
        val_num = parse_metric_number(val_str)
        if val_num is not None:
            metrics.append({'id': name, 'name': name, 'val': val_num, 'val_str': val_str, 'category': 'Makro Endeks'})

    for item in data.get('fred_metrics', []):
        value = item.get('value')
        if value is not None and not item.get('stale') and not item.get('sync_error'):
            label = item['name']
            metrics.append({'id': label, 'name': label, 'val': value,
                            'val_str': f"{value:,.2f} {item.get('unit', '')} ({item.get('date', 'tarih yok')})",
                            'category': item.get('source', 'FRED')})

    # 2. Wall Street Profesyonel Dinamikleri ((i) Simgeli Hesaplanan Endeksler)
    dynamics = [
        (name, data[key][0]) for name, key in (
            ("VIX Eğrisi (Korku Yapısı)", "vix_curve"),
            ("S&P 500 İlk Vade Put/Call Oranı", "spx_pcr"),
            ("En Yüksek Opsiyon Hacmi", "spx_whale"),
            ("HYG/TLT ETF Oranı Günlük Değişimi", "junk_stress"),
            ("BTC Günlük Değişimi", "btc_momentum"),
            ("Bakır/Altın Vadeli Oranı Günlük Değişimi", "cu_au"),
        ) + tuple((label, key) for key, label, *_ in MARKET_DYNAMICS) if key in data and data[key][0] != "Veri yok"
    ]
    for d_name, d_val in dynamics:
        val_str = str(d_val)
        val_num = parse_metric_number(val_str)
        if val_num is not None:
            metrics.append({'id': d_name, 'name': d_name, 'val': val_num, 'val_str': val_str, 'category': 'Hesaplanan Endeks'})

    # 3. Multi GEX Kartları (SPX, GLD, SLV, USO vb.)
    for g in data.get('multi_gex_cards', []):
        name = g.get('name', '').strip()
        spot_str = str(g.get('spot_str', '0.00'))
        val_num = parse_metric_number(spot_str)
        if val_num is not None and val_num > 0:
            metrics.append({'id': name, 'name': name, 'val': val_num, 'val_str': spot_str, 'category': 'Spot & GEX'})

    return metrics


# ---------------------------------------------------------
# ÖZEL FİYAT VE GEX ALARM YÖNETİCİSİ (AlarmManager)
# ---------------------------------------------------------
class AlarmManager:
    alarm_file = "alarms.json"
    alarms = []
    last_known_prices = {}

    @classmethod
    def load_alarms(cls):
        """Always re-read: the background service also updates this file."""
        loaded = read_alarms(cls.alarm_file) if os.path.exists(cls.alarm_file) else []
        if loaded is not None:
            cls.alarms = loaded

    @classmethod
    def save_alarms(cls):
        try:
            write_alarms(cls.alarm_file, cls.alarms)
        except Exception:
            pass

    @classmethod
    def add_alarm(cls, symbol, cond_type, target_value, note="", trigger_mode="once"):
        cls.load_alarms()
        alarm_id = f"alm_{int(datetime.now().timestamp() * 1000)}"
        alarm = {
            "id": alarm_id,
            "symbol": symbol.strip(),
            "cond_type": cond_type,       # 'crossing', 'crossing_up', 'crossing_down', 'above', 'below', 'put_wall', 'call_wall', 'gamma_flip'
            "target_value": float(target_value) if target_value else 0.0,
            "note": note.strip() or f"{symbol} Kesişme {target_value}",
            "trigger_mode": trigger_mode, # 'once' veya 'every'
            "is_active": True,
            "triggered": False,
            "last_price": cls.last_known_prices.get(symbol.strip()),
            "created_at": datetime.now().strftime("%d.%m %H:%M")
        }
        cls.alarms.append(alarm)
        cls.save_alarms()
        return alarm

    @classmethod
    def delete_alarm(cls, alarm_id):
        cls.load_alarms()
        cls.alarms = [a for a in cls.alarms if a.get('id') != alarm_id]
        cls.save_alarms()

    @classmethod
    def toggle_alarm(cls, alarm_id):
        cls.load_alarms()
        for a in cls.alarms:
            if a.get('id') == alarm_id:
                a['is_active'] = not a.get('is_active', True)
                if a['is_active']:
                    a['triggered'] = False
                break
        cls.save_alarms()

    @classmethod
    def check_market_data(cls, data):
        if not data:
            return
        cls.load_alarms()
        if not cls.alarms:
            return

        # Anlık taranan ve hesaplanan tüm metrikleri çek
        metrics = get_terminal_metrics(data)
        current_prices = {m['id']: m['val'] for m in metrics}

        # GEX Seviyeleri (ilk vade); servis kapalı uygulamada bunları alarm üzerinden kullanır
        gex_levels = {}
        for g in data.get('multi_gex_cards', []):
            name = g.get('name', '').strip()
            horizons = g.get('horizons', [])
            if horizons:
                h0 = horizons[0]
                gex_levels[name] = {'put_wall': parse_metric_number(h0.get('put_w')),
                                    'call_wall': parse_metric_number(h0.get('call_w')),
                                    'flip': parse_metric_number(h0.get('flip_lvl')),
                                    'updated_at': time.time()}

        changes = {}
        for a in cls.alarms:
            if not is_checkable(a):
                continue
            sym = a.get('symbol', 'SPX')
            curr_val = current_prices.get(sym)
            if curr_val is None:
                continue
            g_info = gex_levels.get(sym)
            alarm_changes = {}
            if g_info and a.get('cond_type') in GEX_CONDITIONS:
                a['gex_levels'] = g_info
                alarm_changes['gex_levels'] = g_info
            previous = a.get('last_seen_value', a.get('last_price'))
            triggered, title, msg = evaluate_alarm(a, curr_val, g_info)
            alarm_changes.update(observe(a, curr_val, triggered))
            if triggered or previous != curr_val or 'gex_levels' in alarm_changes:
                changes[alarm_key(a)] = alarm_changes
            if triggered:
                NotificationEngine.send_notification(title, msg, subtext=f"Modus Sync - {sym}")

        # Global son fiyatları güncelle
        cls.last_known_prices.update(current_prices)
        if changes:
            try:
                cls.alarms = save_changes(cls.alarm_file, cls.alarms, changes)
            except Exception:
                pass


# ---------------------------------------------------------
# VARLIK SEÇİM MODALI (Terminaldeki Tüm (i) Varlıkları)
# ---------------------------------------------------------
class AssetSelectModal(Sheet):
    def __init__(self, on_selected_callback=None, **kwargs):
        super(AssetSelectModal, self).__init__(tr("Gösterge seçin"), height_ratio=0.86, **kwargs)
        self.on_selected_callback = on_selected_callback
        scroll, stack = scrolling_list()
        metrics = get_terminal_metrics()
        by_category = {}
        for m in metrics:
            by_category.setdefault(m['category'], []).append(m)
        if not metrics:
            group = GroupedList()
            group.add_row(ListRow(tr("Gösterge yok"), tr("Önce piyasa verilerini yenileyin."), accessory=None))
            stack.add_widget(group)
        for category, items in by_category.items():
            stack.add_widget(SectionLabel(trd(category)))
            group = GroupedList()
            for m in items:
                row = ListRow(trd(m['name']), tr("Güncel: {value}", value=trd(m['val_str'])), accessory="chevron")

                def _make_pick(picked):
                    def _pick(*a):
                        self.dismiss()
                        if self.on_selected_callback:
                            self.on_selected_callback(picked)
                    return _pick
                row.bind(on_press=_make_pick(m))
                group.add_row(row)
            stack.add_widget(group)
        self.body.add_widget(scroll)


ALARM_CONDITIONS = (
    ("crossing", "Kesişme"),
    ("crossing_up", "Yukarı kesişme"),
    ("crossing_down", "Aşağı kesişme"),
    ("above", "Değerin üzerinde"),
    ("below", "Değerin altında"),
    ("put_wall", "Put wall desteğine temas"),
    ("call_wall", "Call wall direncine temas"),
    ("gamma_flip", "Gamma flip altına iniş"),
)
CONDITION_LABELS = dict(ALARM_CONDITIONS)


def condition_label(value):
    return tr(CONDITION_LABELS.get(value, value))


def condition_options():
    return tuple((value, tr(label)) for value, label in ALARM_CONDITIONS)


class ChoiceSheet(Sheet):
    """Single-choice list with a checkmark on the current value."""
    def __init__(self, title, options, selected, on_choice, **kwargs):
        super(ChoiceSheet, self).__init__(title, height=min(Window.height * 0.8, dp(120 + 49 * len(options))), **kwargs)
        group = GroupedList()
        for value, label in options:
            row = ListRow(label, accessory="check" if value == selected else None)
            row.bind(on_press=lambda _r, v=value: (self.dismiss(), on_choice(v)))
            group.add_row(row)
        scroll, stack = scrolling_list()
        stack.add_widget(group)
        self.body.add_widget(scroll)


class AlarmListModal(Sheet):
    def __init__(self, **kwargs):
        super(AlarmListModal, self).__init__(tr("Alarmlar"), height_ratio=0.8, **kwargs)
        self.scroll, self.list_box = scrolling_list()
        self.body.add_widget(self.scroll)
        self.body.add_widget(ResponsiveLabel(
            text=tr("Satıra dokunarak alarmı açıp kapatın."), font_size='12.5sp',
            color=hex_color(GRAY), halign='center', min_height=18))
        self._refresh()

    def _refresh(self):
        AlarmManager.load_alarms()
        self.list_box.clear_widgets()
        group = GroupedList()
        if not AlarmManager.alarms:
            group.add_row(ListRow(tr("Kurulu alarm yok"), tr("Bir göstergenin satırına dokunup alarm kurabilirsiniz."),
                                  accessory=None))
        for a in AlarmManager.alarms:
            a_id = a.get('id')
            target = a.get('target_value', 0.0)
            is_act = a.get('is_active', True)
            is_trig = a.get('triggered', False)
            status, tone = ((tr("Tetiklendi"), YELLOW) if is_trig else (tr("Aktif"), GREEN) if is_act else (tr("Kapalı"), GRAY))
            cond = condition_label(a.get('cond_type', 'crossing'))
            row = BoxLayout(orientation='horizontal', size_hint_y=None, spacing=dp(6))
            item = ListRow(trd(a.get('symbol', '')), f"{cond} · {target:,.2f}", trailing=status,
                           trailing_color=tone, accessory=None)
            item.bind(on_press=lambda _r, aid=a_id: self._toggle_cb(aid))
            item.bind(height=row.setter('height'))
            row.add_widget(item)
            delete = TextAction(tr("Sil"))
            delete.color = hex_color(RED)
            delete.bind(on_press=lambda _b, aid=a_id: self._del_cb(aid))
            holder = AnchorLayout(size_hint_x=None, width=dp(56))
            holder.add_widget(delete)
            row.add_widget(holder)
            group.add_row(row)
        self.list_box.add_widget(group)

    def _toggle_cb(self, aid):
        AlarmManager.toggle_alarm(aid)
        self._refresh()

    def _del_cb(self, aid):
        AlarmManager.delete_alarm(aid)
        self._refresh()


class TradingViewAlertModal(Sheet):
    """Alarm editor laid out as an iOS form."""
    def __init__(self, initial_asset=None, **kwargs):
        super(TradingViewAlertModal, self).__init__(tr("Yeni alarm"), height_ratio=0.9, **kwargs)
        metrics = get_terminal_metrics()
        self.current_asset = initial_asset or (metrics[0] if metrics else
                                               {'id': '', 'name': 'Gösterge seçin', 'val': 0.0,
                                                'val_str': 'Veri yok', 'category': ''})
        self.selected_cond = "crossing"
        self.trigger_mode = "once"
        list_action = TextAction(tr("Alarmlar"))
        list_action.bind(on_press=lambda *a: AlarmListModal().open())
        action_holder = AnchorLayout(size_hint_x=None, width=dp(110), anchor_x='right')
        action_holder.add_widget(list_action)
        self.header.add_widget(action_holder, index=1)

        scroll, form = scrolling_list()
        form.spacing = dp(6)

        form.add_widget(SectionLabel(tr("Gösterge ve koşul")))
        group = GroupedList()
        self.asset_row = group.add_row(ListRow(trd(self.current_asset['name']),
                                               tr("Güncel: {value}", value=trd(self.current_asset.get('val_str', '')))))
        self.asset_row.bind(on_press=self._open_asset_selector)
        self.cond_row = group.add_row(ListRow(tr("Koşul"), trailing=condition_label(self.selected_cond)))
        self.cond_row.bind(on_press=self._pick_condition)
        form.add_widget(group)

        form.add_widget(SectionLabel(tr("Hedef değer")))
        val = self.current_asset.get('val') or 0.0
        self.val_input = ModernTextInput(text=f"{val:.4f}" if val else "0.00", multiline=False,
                                         input_filter='float', size_hint_y=None, height=dp(50))
        self.val_input.bind(text=self._on_value_typed)
        form.add_widget(self.val_input)

        form.add_widget(SectionLabel(tr("Tekrar")))
        self.trigger_control = SegmentedControl((("once", tr("Bir kez")), ("every", tr("Her seferinde"))),
                                                self.trigger_mode, on_change=self._set_trigger_mode)
        form.add_widget(self.trigger_control)

        form.add_widget(SectionLabel(tr("Bildirim metni")))
        self.msg_input = ModernTextInput(multiline=False, size_hint_y=None, height=dp(50))
        form.add_widget(self.msg_input)
        form.add_widget(ResponsiveLabel(text=tr("Alarm uygulama kapalıyken de arka plan servisiyle izlenir."),
                                        font_size='12.5sp', color=hex_color(GRAY), min_height=30,
                                        padding=(dp(16), 0)))
        self.body.add_widget(scroll)

        save_btn = ModernButton(text=tr("Alarmı kaydet"), font_size='16sp', bg_hex=BLUE,
                                size_hint_y=None, height=dp(50))
        save_btn.bind(on_press=self._save_alarm)
        self.body.add_widget(save_btn)
        self._update_message()

    def _open_asset_selector(self, *args):
        AssetSelectModal(on_selected_callback=self._on_asset_picked).open()

    def _on_asset_picked(self, picked_asset):
        self.current_asset = picked_asset
        self.asset_row.title_label.text = trd(picked_asset['name'])
        if self.asset_row.subtitle_label:
            self.asset_row.subtitle_label.text = tr("Güncel: {value}", value=trd(picked_asset.get('val_str', '')))
        val = picked_asset.get('val') or 0.0
        self.val_input.text = f"{val:.4f}" if val else "0.00"
        self._update_message()

    def _pick_condition(self, *args):
        ChoiceSheet(tr("Koşul"), condition_options(), self.selected_cond, self._set_condition).open()

    def _set_condition(self, value):
        self.selected_cond = value
        trailing = [w for w in self.cond_row.children if isinstance(w, Label) and w is not self.cond_row.title_label]
        for label in trailing:
            label.text = condition_label(value)
        self._update_message()

    def _set_trigger_mode(self, value):
        self.trigger_mode = value

    def _on_value_typed(self, instance, text):
        self._update_message()

    def _update_message(self):
        self.msg_input.text = f"{trd(self.current_asset['name'])} · {condition_label(self.selected_cond)} {self.val_input.text.strip()}"

    def _save_alarm(self, *args):
        val_str = self.val_input.text.strip().replace(',', '')
        try:
            val_float = float(val_str)
        except Exception:
            val_float = 0.0
        AlarmManager.add_alarm(self.current_asset['name'], self.selected_cond, val_float,
                               note=self.msg_input.text.strip(), trigger_mode=self.trigger_mode)
        self.dismiss()
        NotificationEngine.send_notification(
            tr("Alarm kuruldu: {name}", name=trd(self.current_asset['name'])),
            f"{condition_label(self.selected_cond)} · {val_float:,.2f}",
            subtext="Modus")


# ---------------------------------------------------------
# GÖSTERGE AYRINTISI
# ---------------------------------------------------------
def show_info_popup(title, value_text, explanation_text):
    modal = Sheet(trd(title), height=min(Window.height * 0.66, dp(500)))
    layout = modal.body
    value = ResponsiveLabel(text=trd(value_text), font_size='26sp', bold=True, min_height=36)
    layout.add_widget(value)

    details = ScrollView(do_scroll_x=False, do_scroll_y=True, bar_width=dp(3))
    card = Surface(size_hint_y=None, padding=dp(16))
    card.bind(minimum_height=card.setter('height'))
    card.add_widget(ResponsiveLabel(text=trd(explanation_text), font_size='15sp', valign='top',
                                    color=hex_color(WHITE), markup=True))
    details.add_widget(card)
    layout.add_widget(details)

    set_alarm_btn = ModernButton(text=tr("Alarm kur"), font_size='16sp', bg_hex=BLUE,
                                 size_hint_y=None, height=dp(50))
    if parse_metric_number(value_text) is None:
        set_alarm_btn.disabled = True
        set_alarm_btn.text = tr("Alarm için sayısal veri yok")

    def _open_alarm_for_this(*a):
        modal.dismiss()
        asset_obj = {'id': title, 'name': title, 'val': parse_metric_number(value_text),
                     'val_str': str(value_text), 'category': 'Hesaplanan Endeks'}
        TradingViewAlertModal(initial_asset=asset_obj).open()

    set_alarm_btn.bind(on_press=_open_alarm_for_this)
    layout.add_widget(set_alarm_btn)
    modal.open()


class ClickableRow(ListRow):
    """Metric row: name with its value underneath in the value colour; tap for details."""
    def __init__(self, title, value, val_color=None, val_bold=True, explanation="", **kwargs):
        super(ClickableRow, self).__init__(trd(title), trd(value) if str(value) else "—", **kwargs)
        self.row_title = title
        self.row_value = value
        self.explanation = explanation or METRIC_EXPLANATIONS.get(
            title, "Yahoo Finance kaynaklı son erişilebilir piyasa gözlemidir; işlem saatine göre gecikmiş olabilir.")
        self.title_label.font_size = '15sp'
        self.title_label.color = hex_color(GRAY_LIGHT)
        self.subtitle_label.font_size = '17sp'
        self.subtitle_label.bold = val_bold
        self.subtitle_label.color = hex_color(val_color or WHITE)
        self.bind(on_press=self._on_click)

    def _on_click(self, *args):
        show_info_popup(self.row_title, self.row_value, self.explanation)


class SectionCard(GridLayout):
    """Section caption above an inset-grouped card of rows."""
    def __init__(self, title, **kwargs):
        super(SectionCard, self).__init__(**kwargs)
        self.cols = 1
        self.size_hint_y = None
        self.spacing = dp(2)
        self.bind(minimum_height=self.setter('height'))
        if title:
            super(SectionCard, self).add_widget(SectionLabel(title))
        self.group = GroupedList()
        super(SectionCard, self).add_widget(self.group)

    @property
    def row_count(self):
        return self.group.row_count

    def add_widget(self, widget, *args, **kwargs):
        """Content added directly goes inside the card, padded like a row."""
        box = BoxLayout(size_hint_y=None, padding=(dp(16), dp(12)))
        widget.bind(height=lambda *_: setattr(box, 'height', widget.height + dp(24)))
        box.height = widget.height + dp(24)
        box.add_widget(widget)
        self.group.add_row(box)

    def add_clickable_row(self, title, value, val_color=None, val_bold=True, explanation=""):
        self.group.add_row(ClickableRow(title, value, val_color, val_bold, explanation))

    def add_multi_row(self, title, value, val_color=None):
        row = ListRow(title, str(value), accessory=None)
        row.title_label.font_size = '15sp'
        row.title_label.color = hex_color(GRAY_LIGHT)
        row.subtitle_label.font_size = '15sp'
        row.subtitle_label.color = hex_color(val_color or WHITE)
        self.group.add_row(row)


class CollapsibleSectionCard(GroupedList):
    """Card whose header row expands to show its rows."""
    def __init__(self, title, collapsed=True, **kwargs):
        super(CollapsibleSectionCard, self).__init__(**kwargs)
        self.title = title
        self.expanded = not collapsed
        self.header = ListRow(title, accessory=None)
        self.header.title_label.bold = True
        self.chevron = Chevron(open=self.expanded)
        holder = AnchorLayout(size_hint_x=None, width=dp(14))
        holder.add_widget(self.chevron)
        self.header.add_widget(holder)
        self.header.bind(on_press=lambda *_: self.toggle())
        self.add_row(self.header)
        self.body = GridLayout(cols=1, size_hint_y=None)
        self.body.bind(minimum_height=self.body.setter('height'))
        self._divider = Hairline()
        if self.expanded:
            self.add_widget(self._divider)
            self.add_widget(self.body)

    def toggle(self):
        self.expanded = not self.expanded
        if self.expanded:
            self.add_widget(self._divider)
            self.add_widget(self.body)
        else:
            self.remove_widget(self.body)
            self.remove_widget(self._divider)
        self.chevron.open = self.expanded

    def add_clickable_row(self, title, value, val_color=None, val_bold=True, explanation=""):
        if self.body.children:
            self.body.add_widget(Hairline())
        self.body.add_widget(ClickableRow(title, value, val_color, val_bold, explanation))

    def add_multi_row(self, title, value, val_color=None):
        if self.body.children:
            self.body.add_widget(Hairline())
        row = ListRow(title, str(value), accessory=None)
        row.title_label.font_size = '15sp'
        row.title_label.color = hex_color(GRAY_LIGHT)
        row.subtitle_label.font_size = '15sp'
        row.subtitle_label.color = hex_color(val_color or WHITE)
        self.body.add_widget(row)


class MetricTile(Surface):
    """Summary tile: caption, large value and a tinted change badge."""
    def __init__(self, title, value, change, tone=None, **kwargs):
        super(MetricTile, self).__init__(size_hint_y=None, height=dp(104),
                                         padding=(dp(14), dp(12), dp(14), dp(12)), spacing=dp(4),
                                         radius_val=14, **kwargs)
        heading = Label(text=title, font_size='13sp', color=hex_color(GRAY_LIGHT),
                        size_hint_y=None, height=dp(18), halign='left', valign='middle')
        number = Label(text=str(value), font_size='24sp', bold=True, color=hex_color(WHITE),
                       size_hint_y=None, height=dp(32), halign='left', valign='middle')
        for label in (heading, number):
            label.bind(size=label.setter('text_size'))
            self.add_widget(label)
        badge_row = BoxLayout(size_hint_y=None, height=dp(24))
        if change and change != "N/A":
            badge_row.add_widget(StatusPill(text=str(change), tone=theme.resolve(tone or GRAY)))
        badge_row.add_widget(Widget())
        self.add_widget(badge_row)


class CompactExpiryCard(SectionCard):
    """Option summary per expiry; tap a row for the full explanation."""
    def __init__(self, asset_name, spot_str, **kwargs):
        super(CompactExpiryCard, self).__init__(asset_name, **kwargs)
        self.add_clickable_row(tr("Dayanak fiyat"), spot_str)

    def add_expiry_row(self, horizon_label, put_w, flip_lvl, call_w, gex_str, gex_color):
        flip_note = tr("(tahmini: net GEX'in sıfırlandığı spot; yalnızca bant içindeki strike'lar)")
        detail = ("[b]" + tr("Vade:") + "[/b] " + str(horizon_label) + "\n"
                  "[b]" + tr("En yüksek put OI gamma seviyesi:") + "[/b] " + str(put_w) + "\n"
                  "[b]Gamma flip:[/b] " + str(flip_lvl) + " " + flip_note + "\n"
                  "[b]" + tr("En yüksek call OI gamma seviyesi:") + "[/b] " + str(call_w) + "\n"
                  "[b]" + tr("Yaklaşık net GEX:") + "[/b] " + trd(gex_str) + "; "
                  + tr("açık pozisyon ve model varsayımlarına dayanır."))
        self.add_clickable_row(tr("Vade {date}", date=horizon_label),
                               f"Put {put_w} · Flip {flip_lvl} · Call {call_w}\nGEX {trd(gex_str)}",
                               gex_color, False, detail)


# ---------------------------------------------------------
# BLACK-SCHOLES MOTORU
# ---------------------------------------------------------

# ---------------------------------------------------------
# VERİ TOPLAMA MOTORU
# ---------------------------------------------------------
class MarketDataFetcher:
    def __init__(self):
        self.feed = YahooFeed()
        self.session = self.feed.session
        self.crumb = self._get_crumb()

    def _get_crumb(self):
        try:
            # fc.yahoo.com can reply 404 while still setting the cookie needed by getcrumb.
            self.session.get('https://fc.yahoo.com', timeout=4)
            r = self.session.get('https://query2.finance.yahoo.com/v1/test/getcrumb', timeout=4)
            r.raise_for_status()
            c = r.text.strip()
            return c if (c and len(c) < 100 and '<' not in c and '{' not in c) else ''
        except Exception:
            return ''

    def get_chart_history(self, sym, range_str='2d', interval='1d'):
        return [value for _, value in self.feed.observations(sym, range_str, interval)]

    def fetch_all(self):
        result = {}

        result['fetched_at'] = datetime.now(timezone.utc).isoformat()
        macro_records = []
        observations = {}
        with ThreadPoolExecutor(max_workers=6) as pool:
            latest_quotes = list(pool.map(lambda pair: self.feed.latest(pair[1]), YAHOO_MACROS))
        for (name, sym), item in zip(YAHOO_MACROS, latest_quotes):
            if item:
                observations[sym] = item
                previous = item['previous']
                pct = ((item['value'] / previous) - 1) * 100 if previous else None
                is_yield = sym in ('^IRX', '^FVX', '^TNX', '^TYX')
                change = (f"{(item['value'] - previous) * 100:+.0f} bp" if is_yield
                          else f"{pct:+.2f}%") if pct is not None else "N/A"
                macro_records.append((name, f"{item['value']:.2f}", change,
                                      GREEN if pct is not None and pct > 0 else RED if pct is not None and pct < 0 else WHITE))
            else:
                macro_records.append((name, "Veri yok", "N/A", GRAY))
        if '^TNX' in observations and '^IRX' in observations:
            spread = observations['^TNX']['value'] - observations['^IRX']['value']
            macro_records.append(("10Y - 13 Haftalık Bono Faiz Farkı (yaklaşık, yüzde puan)",
                                  f"{spread:+.2f}", "N/A", GREEN if spread > 0 else RED))
        result['macros'] = macro_records
        result['macro_observations'] = {sym: {'value': item['value'], 'timestamp': item['timestamp']}
                                        for sym, item in observations.items()}

        try:
            v_h = self.get_chart_history('^VIX', '1d')
            v3_h = self.get_chart_history('^VIX3M', '1d')
            if v_h and v3_h:
                v, v3 = v_h[-1], v3_h[-1]
                st = "CONTANGO (Sakin)" if v3 > v else "BACKWARDATION (Panik)"
                result['vix_curve'] = (f"VIX3M-VIX: {v3-v:+.2f} ({st}; VIX {v:.2f}, VIX3M {v3:.2f})", GREEN if v3 > v else RED)
            else:
                result['vix_curve'] = ("Veri yok", GRAY)
        except Exception:
            result['vix_curve'] = ("Veri yok", GRAY)

        try:
            ratio = self.feed.ratio_change('HYG', 'TLT')
            if ratio:
                pct = ratio['change_pct']
                result['junk_stress'] = (f"{pct:+.2f}%", RED if pct < 0 else GREEN)
            else:
                result['junk_stress'] = ("Veri yok", GRAY)
        except Exception:
            result['junk_stress'] = ("Veri yok", GRAY)

        try:
            btc = self.get_chart_history('BTC-USD', '5d')
            if len(btc) >= 2:
                pct = ((btc[-1] - btc[-2]) / btc[-2]) * 100
                result['btc_momentum'] = (f"{pct:+.2f}% ({'Pozitif' if pct > 0 else 'Negatif'})", GREEN if pct > 0 else RED)
            else:
                result['btc_momentum'] = ("Veri yok", GRAY)
        except Exception:
            result['btc_momentum'] = ("Veri yok", GRAY)

        try:
            ratio = self.feed.ratio_change('HG=F', 'GC=F')
            if ratio:
                pct = ratio['change_pct']
                # Alarm değeri ilk sayıdır: metrik adı "Günlük Değişimi" olduğu için önce yüzde gelir.
                result['cu_au'] = (f"{pct:+.2f}% günlük (oran {ratio['value']:.6f}; USD/lb ÷ USD/ons)",
                                   GREEN if pct > 0 else RED)
            else:
                result['cu_au'] = ("Veri yok", GRAY)
        except Exception:
            result['cu_au'] = ("Veri yok", GRAY)

        dynamics = compute_dynamics(self.feed)
        for key, *_ in MARKET_DYNAMICS:
            item = dynamics.get(key)
            result[key] = ((item['display'], GREEN if item['tone'] > 0 else RED if item['tone'] < 0 else WHITE)
                           if item else ("Veri yok", GRAY))

        result['breadth'] = ("Veri yok", GRAY)
        result['sectors'] = {}

        try:
            r = self.session.get('https://nfs.faireconomy.media/ff_calendar_thisweek.xml', timeout=4)
            root = ET.fromstring(r.content)
            today_str = datetime.now().strftime('%m-%d-%Y')
            events = [f"{ev.find('time').text} - {ev.find('title').text}" for ev in root.findall('event') if ev.find('country').text == 'USD' and ev.find('impact').text == 'High' and ev.find('date').text == today_str]
            result['calendar'] = " | ".join(events) if events else "Bugun kritik bir veri beklenmiyor."
            result['calendar_week'] = parse_week_calendar(r.content, datetime.now().date())
        except Exception:
            result['calendar'] = "Ekonomik takvim alınamadı."
            result['calendar_week'] = []

        try:
            result['headlines'] = fetch_headlines(self.session)
        except Exception:
            result['headlines'] = []

        assets_config = [
            {"name": "S&P 500 (^GSPC)", "symbol": "^GSPC", "options_symbol": "^SPX", "mult": 100, "band": 0.04},
            {"name": "Gold ETF (GLD)", "symbol": "GLD", "mult": 100, "band": 0.05},
            {"name": "Silver ETF (SLV)", "symbol": "SLV", "mult": 100, "band": 0.06},
            {"name": "Crude Oil ETF (USO)", "symbol": "USO", "mult": 100, "band": 0.06},
        ]
        multi_gex_cards = []
        pcr_text, pcr_color = "Veri yok", GRAY
        whale_text, whale_color = "Veri yok", GRAY

        for asset in assets_config:
            name, sym, mult, band = asset['name'], asset['symbol'], asset['mult'], asset['band']
            spot = 0.0
            h = self.get_chart_history(sym, '5d')
            if h: spot = h[-1]
            horizons = []
            if not spot:
                multi_gex_cards.append({'name': name, 'spot_str': 'Veri yok', 'horizons': []})
                continue

            try:
                options_sym = asset.get('options_symbol', sym)
                opt_url = f"https://query2.finance.yahoo.com/v7/finance/options/{options_sym}"
                opt_resp = self.session.get(opt_url, params={'crumb': self.crumb} if self.crumb else {}, timeout=7)
                opt_resp.raise_for_status()
                opt_data = opt_resp.json()['optionChain']['result'][0]
                exp_ts_list = opt_data.get('expirationDates', [])

                if exp_ts_list:
                    exp_0dte = exp_ts_list[0]
                    exp_weekly = next((ts for ts in exp_ts_list[1:] if expiry_date(ts).weekday() == 4), exp_ts_list[1] if len(exp_ts_list)>1 else exp_0dte)
                    exp_monthly = next((ts for ts in exp_ts_list[2:] if expiry_date(ts).weekday() == 4 and 15 <= expiry_date(ts).day <= 21), exp_ts_list[-1])

                    def process_chain(opt_block, exp_ts, label):
                        if '^IRX' not in observations:
                            return {'label': label, 'put_w': '-', 'flip_lvl': '-',
                                    'call_w': '-', 'gex_str': 'Faiz verisi yok', 'gex_color': GRAY}
                        # Yahoo vade zamanı 00:00 UTC; gerçek kapanış 16:00 New York.
                        T_val = years_to_expiry(exp_ts)
                        risk_free_rate = observations['^IRX']['value'] / 100.0
                        calls, puts = opt_block.get('calls', []), opt_block.get('puts', [])
                        call_gex, put_gex, records, positions = {}, {}, [], []

                        for c in calls:
                            k = c.get('strike', 0)
                            if spot * (1.0 - band) <= k <= spot * (1.0 + band):
                                iv, oi = c.get('impliedVolatility', 0) or 0, c.get('openInterest', 0) or 0
                                if oi > 0 and iv > 0:
                                    g = dollar_gamma(spot, k, T_val, risk_free_rate, iv, oi, mult)
                                    call_gex[k] = call_gex.get(k, 0) + g
                                    records.append({'strike': k, 'net_gex': g})
                                    positions.append((k, iv, oi, 1))

                        for p in puts:
                            k = p.get('strike', 0)
                            if spot * (1.0 - band) <= k <= spot * (1.0 + band):
                                iv, oi = p.get('impliedVolatility', 0) or 0, p.get('openInterest', 0) or 0
                                if oi > 0 and iv > 0:
                                    g = dollar_gamma(spot, k, T_val, risk_free_rate, iv, oi, mult)
                                    put_gex[k] = put_gex.get(k, 0) + g
                                    records.append({'strike': k, 'net_gex': -g})
                                    positions.append((k, iv, oi, -1))

                        cw = max(call_gex.items(), key=lambda x: x[1])[0] if call_gex else None
                        pw = max(put_gex.items(), key=lambda x: x[1])[0] if put_gex else None
                        tot_g = sum(r['net_gex'] for r in records) / 1e6
                        flip = gamma_flip(positions, spot, T_val, risk_free_rate, mult, band)
                        return {'label': label, 'put_w': f"{pw:,.2f}" if pw else '-',
                                'flip_lvl': f"{flip:,.2f}" if flip else '-', 'call_w': f"{cw:,.2f}" if cw else '-',
                                'gex_str': f"{tot_g:+,.1f}M (tahmini)" if records else 'Veri yok',
                                'gex_color': GREEN if tot_g > 0 else RED if records else GRAY}

                    expiry_label = datetime.fromtimestamp(exp_0dte, timezone.utc).strftime('%d.%m.%Y')
                    horizons.append(process_chain(opt_data['options'][0], exp_0dte, expiry_label))

                    if options_sym == "^SPX":
                        calls_0, puts_0 = opt_data['options'][0].get('calls', []), opt_data['options'][0].get('puts', [])
                        c_vol, p_vol = sum(c.get('volume', 0) or 0 for c in calls_0), sum(p.get('volume', 0) or 0 for p in puts_0)
                        if c_vol > 0:
                            pcr = p_vol / c_vol
                            pcr_text = f"{pcr:.2f}"
                            pcr_color = WHITE
                        mc = max(calls_0, key=lambda x: x.get('volume', 0) or 0, default={})
                        mp = max(puts_0, key=lambda x: x.get('volume', 0) or 0, default={})
                        if (mc.get('volume', 0) or 0) > (mp.get('volume', 0) or 0) and (mc.get('volume', 0) or 0) > 0:
                            whale_text, whale_color = f"{mc.get('strike', 0)} CALL (Hacim: {int(mc.get('volume', 0)):,})", GREEN
                        elif (mp.get('volume', 0) or 0) > 0:
                            whale_text, whale_color = f"{mp.get('strike', 0)} PUT (Hacim: {int(mp.get('volume', 0)):,})", RED

                    try:
                        dw_resp = self.session.get(opt_url, params={'date': exp_weekly, **({'crumb': self.crumb} if self.crumb else {})}, timeout=5)
                        dw_resp.raise_for_status()
                        dw = dw_resp.json()['optionChain']['result'][0]
                        horizons.append(process_chain(dw['options'][0], exp_weekly, datetime.fromtimestamp(exp_weekly, timezone.utc).strftime('%d.%m.%Y')))
                    except Exception:
                        pass

                    try:
                        dm_resp = self.session.get(opt_url, params={'date': exp_monthly, **({'crumb': self.crumb} if self.crumb else {})}, timeout=5)
                        dm_resp.raise_for_status()
                        dm = dm_resp.json()['optionChain']['result'][0]
                        horizons.append(process_chain(dm['options'][0], exp_monthly, datetime.fromtimestamp(exp_monthly, timezone.utc).strftime('%d.%m.%Y')))
                    except Exception:
                        pass
            except Exception:
                horizons = []

            multi_gex_cards.append({'name': name, 'spot_str': f"{spot:,.2f}" if spot else 'Veri yok', 'horizons': horizons})

        result['spx_pcr'] = (pcr_text, pcr_color)
        result['spx_whale'] = (whale_text, whale_color)
        result['multi_gex_cards'] = multi_gex_cards

        try:
            fred = FredStore()
            sync = fred.sync_many()
            result['fred_metrics'] = mark_sync_errors(fred.metrics(), sync['errors'])
            result['fred_sync_errors'] = sync['errors']
        except Exception as exc:
            result['fred_metrics'] = []
            result['fred_sync_errors'] = {'FRED': str(exc)[:160]}
        cnh = fetch_cnh_quote()
        cnh_stale = bool(cnh and (datetime.now(timezone.utc).date() -
                                  datetime.fromisoformat(cnh['date']).date()).days > 10)
        result['fred_metrics'].append({
            'id': 'CNH=X', 'name': 'USD/CNH (Offshore)',
            'value': cnh['value'] if cnh else None,
            'date': cnh['date'] if cnh else None,
            'unit': 'CNH / USD', 'frequency': 'günlük',
            'source': cnh['source'] if cnh else 'Yahoo Finance',
            'stale': cnh_stale
        })

        try:
            cache_dir = os.path.join(os.path.dirname(fred_database_path()), 'external_macro_cache')
            result['external_metrics'] = ExternalMacroFeed(cache_path=cache_dir).fetch_metrics()
        except Exception:
            result['external_metrics'] = []
        try:
            result['external_metrics'] += cross_metrics(result['fred_metrics'], result['external_metrics'])
        except Exception as exc:
            print(f"[Cross metrics Error] {exc}")

        AppState.save_market_data(result)
        return result


# ---------------------------------------------------------
# GÖRÜNÜM AYARI VE EKRANLAR
# ---------------------------------------------------------
class AppearanceSheet(Sheet):
    """System / Light / Dark appearance and interface language."""
    def __init__(self, **kwargs):
        super(AppearanceSheet, self).__init__(tr("Görünüm"), height=dp(340), **kwargs)
        self.body.add_widget(SectionLabel(tr("Tema")))
        self.body.add_widget(SegmentedControl((("system", tr("Sistem")), ("light", tr("Açık")),
                                               ("dark", tr("Koyu"))),
                                              theme.mode, on_change=self._change))
        self.body.add_widget(ResponsiveLabel(
            text=tr("Sistem seçeneği telefonun açık/koyu ayarını izler."), font_size='13sp',
            color=hex_color(GRAY_LIGHT), min_height=22, padding=(dp(16), 0)))
        self.body.add_widget(SectionLabel(tr("Dil")))
        group = GroupedList()
        language_row = group.add_row(ListRow(tr("Uygulama dili"), trailing=i18n.language_name()))
        language_row.bind(on_press=self._pick_language)
        self.body.add_widget(group)
        self.body.add_widget(Widget())

    def _change(self, mode):
        self.dismiss()
        app = App.get_running_app()
        if app:
            Clock.schedule_once(lambda dt: app.apply_theme(mode), 0.25)

    def _pick_language(self, *args):
        ChoiceSheet(tr("Uygulama dili"), i18n.LANGUAGES, i18n.current, self._set_language).open()

    def _set_language(self, code):
        self.dismiss()
        app = App.get_running_app()
        if app:
            Clock.schedule_once(lambda dt: app.apply_language(code), 0.25)


# ---------------------------------------------------------
# 1. EKRAN: PİYASA
# ---------------------------------------------------------
class TerminalScreen(Screen):
    def __init__(self, **kwargs):
        super(TerminalScreen, self).__init__(**kwargs)
        self.root_layout = Background(orientation='vertical')

        self.header = LargeTitleHeader(tr("Piyasa"), tr("Veriler hazırlanıyor…"))
        self.refresh_btn = self.header.add_action(IconButton(themed_icon('refresh'), icon_size=20))
        self.refresh_btn.bind(on_press=lambda *a: self._start_auto_scan())
        appearance = self.header.add_action(IconButton(themed_icon('appearance'), icon_size=20))
        appearance.bind(on_press=lambda *a: AppearanceSheet().open())
        bell_btn = self.header.add_action(IconButton(bell_icon_source(), icon_size=20))
        bell_btn.bind(on_press=self._open_alarms)
        self.root_layout.add_widget(self.header)
        self.freshness_label = self.header.subtitle_label

        self.scroll = ScrollView(do_scroll_x=False, do_scroll_y=True, bar_width=dp(3))
        self.content = GridLayout(cols=1, spacing=dp(10), size_hint_y=None,
                                  padding=(dp(16), dp(8), dp(16), dp(20)))
        self.content.bind(minimum_height=self.content.setter('height'))
        self.scroll.add_widget(self.content)
        self.root_layout.add_widget(self.scroll)

        self._show_status(tr("Yükleniyor"), tr("Piyasa verileri alınıyor…"), GRAY_LIGHT)
        self.add_widget(self.root_layout)
        if market_data_is_fresh(AppState.last_market_data):
            Clock.schedule_once(lambda dt: self._render_full_report(AppState.last_market_data), 0)
        else:
            Clock.schedule_once(lambda dt: self._start_auto_scan(), 0.3)

    def _open_alarms(self, *args):
        try:
            AlarmListModal().open()
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"[OpenAlarms Error] {e}")

    def on_enter(self, *args):
        if not market_data_is_fresh(AppState.last_market_data):
            self._start_auto_scan()

    def _start_auto_scan(self):
        if getattr(self, '_scanning', False):
            return
        self._scanning = True
        self.refresh_btn.opacity = 0.4
        self.freshness_label.text = tr("Güncelleniyor…")
        if not AppState.last_market_data:
            self._show_status(tr("Yükleniyor"), tr("Yahoo, FRED ve opsiyon verileri alınıyor. Bu birkaç saniye sürebilir."), GRAY_LIGHT)
        threading.Thread(target=self._fetch_and_dispatch, daemon=True).start()

    def _go_to_ai(self, *args):
        app = App.get_running_app()
        if app:
            app.select_tab('ai_screen')

    def _show_status(self, title, msg, color):
        self.content.clear_widgets()
        card = SectionCard(title)
        card.add_widget(ResponsiveLabel(text=str(msg), min_height=24, font_size='15sp', color=hex_color(color)))
        self.content.add_widget(card)
        if color == RED:
            retry = ModernButton(text=tr("Tekrar dene"), size_hint_y=None, height=dp(50), bg_hex=BLUE)
            retry.bind(on_press=lambda *_: self._start_auto_scan())
            self.content.add_widget(retry)

    def _fetch_and_dispatch(self):
        try:
            fetcher = MarketDataFetcher()
            payload = fetcher.fetch_all()
            Clock.schedule_once(lambda dt: self._render_full_report(payload))
        except Exception as e:
            print(f"[Dashboard fetch] {type(e).__name__}: {e}")
            Clock.schedule_once(lambda dt: self._fetch_failed())

    def _fetch_failed(self):
        self._scanning = False
        self.refresh_btn.opacity = 1
        self.freshness_label.text = tr("Güncelleme başarısız")
        if not AppState.last_market_data:
            self._show_status(tr("Veriler alınamadı"), tr("Bağlantıyı kontrol edip tekrar deneyin."), RED)

    def _render_full_report(self, data):
        self._scanning = False
        self.refresh_btn.opacity = 1
        self.content.clear_widgets()
        try:
            scan_time = datetime.fromisoformat(data['fetched_at']).astimezone().strftime('%d.%m %H:%M')
        except (KeyError, TypeError, ValueError):
            scan_time = tr("bilinmiyor")
        stale_count = sum(1 for item in data.get('fred_metrics', []) + data.get('external_metrics', [])
                          if item.get('stale') or item.get('sync_error'))
        self.freshness_label.text = (tr("Güncellendi {time} · {count} gösterge eski", time=scan_time, count=stale_count)
                                     if stale_count else tr("Güncellendi {time}", time=scan_time))

        try:
            AlarmManager.check_market_data(data)
        except Exception as ex:
            print(f"[AlarmCheck Error] {ex}")

        if data.get('macros'):
            overview = GridLayout(cols=2, spacing=dp(10), size_hint_y=None)
            overview.bind(minimum_height=overview.setter('height'))
            key_metrics = (
                ("Altın Vadeli (USD/ons)", tr("Altın")),
                ("Dolar Endeksi (DXY)", tr("Dolar endeksi")),
                ("ABD 10 Yıllık Tahvil Faizi (%)", tr("ABD 10Y faiz")),
                ("VIX Endeksi", "VIX"),
            )
            by_name = {row[0]: row for row in data['macros']}
            for source_name, short_name in key_metrics:
                row = by_name.get(source_name)
                if row and row[1] != "Veri yok":
                    overview.add_widget(MetricTile(short_name, row[1], row[2], row[3]))
            if overview.children:
                self.content.add_widget(overview)

            self.content.add_widget(SectionLabel(tr("Göstergeler")))
            card_macro = CollapsibleSectionCard(tr("Piyasa fiyatları"), collapsed=True)
            for name, val_str, chg_str, color in data['macros']:
                display_val = f"{val_str}   {chg_str}" if chg_str != "N/A" else val_str
                card_macro.add_clickable_row(name, display_val, color)
            self.content.add_widget(card_macro)

        if data.get('fred_metrics'):
            by_id = {item['id']: item for item in data['fred_metrics']}
            for group_name, ids in FRED_GROUPS:
                card_fred = CollapsibleSectionCard(trd(group_name), collapsed=True)
                for series_id in ids:
                    item = by_id.get(series_id)
                    if not item:
                        continue
                    value = item.get('value')
                    display = (f"{value:,.2f} {trd(item['unit'])}  ·  {item.get('date') or tr('tarih yok')}"
                               if value is not None else tr("Veri yok"))
                    if item.get('stale') and value is not None:
                        display += "  ·  " + tr("eski gözlem")
                    if item.get('sync_error') and value is not None:
                        display += "  ·  " + tr("önbellek")
                    notes = item.get('notes') or tr("Kaynak: {source}; gözlem sıklığı: {frequency}",
                                                    source=item.get('source', 'FRED'),
                                                    frequency=trd(item.get('frequency', '?')))
                    card_fred.add_clickable_row(item['name'], display,
                                                YELLOW if item.get('stale') or item.get('sync_error') else WHITE if value is not None else GRAY,
                                                explanation=notes)
                if card_fred.body.children:
                    self.content.add_widget(card_fred)

        if data.get('external_metrics'):
            groups = {}
            for item in data['external_metrics']:
                groups.setdefault(item.get('group') or "Diğer resmi veriler", []).append(item)
            ordered = [name for name in EXTERNAL_GROUP_ORDER if name in groups] + \
                      [name for name in groups if name not in EXTERNAL_GROUP_ORDER]
            for group_name in ordered:
                card_external = CollapsibleSectionCard(trd(group_name), collapsed=True)
                for item in groups[group_name]:
                    value = item.get('value')
                    display = (f"{value:,.2f} {trd(item['unit'])}  ·  {item.get('date') or tr('tarih yok')}"
                               if value is not None else tr("Veri yok"))
                    if item.get('stale') and value is not None:
                        display += "  ·  " + tr("eski/önbellek")
                    notes = trd(item.get('notes') or '') + " " + tr("Kaynak: {source}", source=item.get('source') or tr('bilinmiyor'))
                    card_external.add_clickable_row(item['name'], display,
                                                    YELLOW if item.get('stale') or item.get('sync_error') else WHITE if value is not None else GRAY,
                                                    explanation=notes)
                self.content.add_widget(card_external)

        if data.get('headlines'):
            card_news = CollapsibleSectionCard(tr("Son başlıklar (48 saat)"), collapsed=True)
            for item in data['headlines'][:10]:
                card_news.add_multi_row(f"{item['source']} · {item['time']}", item['title'])
            self.content.add_widget(card_news)

        card_dyn = SectionCard(tr("Piyasa dinamikleri"))
        for key, label in (
            ('vix_curve', "VIX Eğrisi (Korku Yapısı)"),
            ('spx_pcr', "S&P 500 İlk Vade Put/Call Oranı"),
            ('spx_whale', "En Yüksek Opsiyon Hacmi"),
            ('junk_stress', "HYG/TLT ETF Oranı Günlük Değişimi"),
            ('btc_momentum', "BTC Günlük Değişimi"),
            ('cu_au', "Bakır/Altın Vadeli Oranı Günlük Değişimi"),
        ) + tuple((key, label) for key, label, *_ in MARKET_DYNAMICS):
            value, tone = data.get(key, ("Veri yok", GRAY))
            if value != "Veri yok":
                card_dyn.add_clickable_row(label, value, tone)

        sec = data.get('sectors', {})
        if sec:
            card_dyn.add_multi_row(tr("Sektör liderleri (günlük)"), sec.get('top_1d', '-'), GREEN)
            card_dyn.add_multi_row(tr("Sektör zayıfları (günlük)"), sec.get('bot_1d', '-'), RED)
            card_dyn.add_multi_row(tr("Sektör liderleri (haftalık)"), sec.get('top_1w', '-'), GREEN)
            card_dyn.add_multi_row(tr("Sektör zayıfları (haftalık)"), sec.get('bot_1w', '-'), RED)

        cal_txt = data.get('calendar', "Ekonomik takvim alınamadı.")
        if cal_txt != "Ekonomik takvim alınamadı.":
            card_dyn.add_multi_row(tr("Bugünkü kritik ABD verileri"), trd(cal_txt))
        if data.get('calendar_week'):
            card_dyn.add_multi_row(tr("Bu haftanın kalan kritik ABD verileri (UTC)"), trd(" | ".join(data['calendar_week'])))
        if card_dyn.row_count == 0:
            card_dyn.add_multi_row(tr("Durum"), tr("Şu anda ek piyasa göstergesi alınamadı."), GRAY_LIGHT)
        self.content.add_widget(card_dyn)

        if data.get('multi_gex_cards'):
            for g in data['multi_gex_cards']:
                m_card = CompactExpiryCard(tr("Opsiyonlar · {name}", name=g['name']), g['spot_str'])
                for h in g['horizons']:
                    m_card.add_expiry_row(h['label'], h['put_w'], h['flip_lvl'], h['call_w'], h['gex_str'], h['gex_color'])
                self.content.add_widget(m_card)
            self.content.add_widget(ResponsiveLabel(
                text=tr("GEX ve flip, erişilen opsiyon açık pozisyonundan Black-Scholes ile tahmin edilir."),
                font_size='12.5sp', color=hex_color(GRAY), min_height=30, padding=(dp(16), 0)))


# ---------------------------------------------------------
# 2. EKRAN: ASİSTAN (SOHBET)
# ---------------------------------------------------------
class ChatBubble(BoxLayout):
    """iMessage-like bubble that hugs its text up to 80% of the row width."""
    def __init__(self, text, mine, caption="", text_color=None, **kwargs):
        super(ChatBubble, self).__init__(orientation='vertical', size_hint_y=None, spacing=dp(3), **kwargs)
        self.mine = mine
        if caption:
            cap = Label(text=caption, font_size='12sp', color=hex_color(GRAY), size_hint_y=None, height=dp(16),
                        halign='right' if mine else 'left', valign='middle', padding=(dp(6), 0))
            cap.bind(size=cap.setter('text_size'))
            self.add_widget(cap)
        self.row = BoxLayout(orientation='horizontal', size_hint_y=None)
        self.bubble = BoxLayout(size_hint=(None, None), padding=(dp(14), dp(10)))
        with self.bubble.canvas.before:
            Color(*hex_color(USER_MSG_BG if mine else AI_MSG_BG))
            self._shape = RoundedRectangle(radius=[dp(18)])
        self.bubble.bind(pos=self._sync, size=self._sync)
        self.label = Label(text=text, font_size='16sp', markup=False, halign='left', valign='top',
                           color=hex_color(ON_ACCENT if mine else (text_color or WHITE)),
                           size_hint=(None, None))
        self.bubble.add_widget(self.label)
        if mine:
            self.row.add_widget(Widget())
        self.row.add_widget(self.bubble)
        if not mine:
            self.row.add_widget(Widget())
        self.add_widget(self.row)
        self.bind(width=self._layout)
        self.label.bind(texture_size=self._fit)

    def _sync(self, *args):
        self._shape.pos = self.bubble.pos
        self._shape.size = self.bubble.size

    def _layout(self, *args):
        self.label.text_size = (max(dp(60), self.width * 0.8 - dp(28)), None)

    def _fit(self, *args):
        w, h = self.label.texture_size
        self.label.size = (w, h)
        self.bubble.size = (w + dp(28), h + dp(20))
        self.row.height = self.bubble.height
        self.height = sum(child.height for child in self.children) + self.spacing * (len(self.children) - 1)


class AIScreen(Screen):
    def __init__(self, **kwargs):
        super(AIScreen, self).__init__(**kwargs)
        self.chat_history = []
        self.transcript = []  # everything shown, so a theme switch can redraw it
        self.request_pending = False
        self.root_layout = Background(orientation='vertical', padding=(dp(12), dp(4), dp(12), dp(8)), spacing=dp(4))

        top_bar = BoxLayout(orientation='horizontal', size_hint_y=None, height=dp(44))
        self.model_btn = IconButton(themed_icon('sparkles'), icon_size=20)
        self.model_btn.bind(on_press=self._open_model_selector)
        top_bar.add_widget(centered(self.model_btn))
        chat_title = Label(text=tr("Asistan"), font_size='17sp', bold=True, color=hex_color(WHITE),
                           halign='center', valign='middle')
        chat_title.bind(size=chat_title.setter('text_size'))
        top_bar.add_widget(chat_title)
        settings_btn = IconButton(themed_icon('gear'), icon_size=20)
        settings_btn.bind(on_press=self._open_settings)
        top_bar.add_widget(centered(settings_btn))
        self.root_layout.add_widget(top_bar)
        self.ai_status = ResponsiveLabel(text=self._model_status_text(),
                                         min_height=16, font_size='12sp', color=hex_color(GRAY),
                                         halign='center')
        self.root_layout.add_widget(self.ai_status)

        self.chat_scroll = ScrollView(do_scroll_x=False, do_scroll_y=True, bar_width=dp(3))
        self.chat_content = GridLayout(cols=1, spacing=dp(10), size_hint_y=None, padding=(0, dp(8), 0, dp(8)))

        def fit_chat_height(*_):
            self.chat_content.height = max(self.chat_content.minimum_height, self.chat_scroll.height)
        self.chat_content.bind(minimum_height=fit_chat_height)
        self.chat_scroll.bind(height=fit_chat_height)
        self.chat_scroll.add_widget(self.chat_content)
        self.root_layout.add_widget(self.chat_scroll)
        Clock.schedule_once(fit_chat_height, 0)

        self._add_ai_bubble(
            tr("Merhaba. Bir varlık ya da piyasa hakkında soru sorun; güncel gözlemleri ve geçmiş hareketleri "
               "birlikte değerlendireyim. Takip sorularında önceki konuyu hatırlarım."),
            "Modus")

        input_bar = BoxLayout(orientation='horizontal', size_hint_y=None, height=dp(48), spacing=dp(8))
        self.msg_input = ModernTextInput(hint_text=tr("Mesaj"), multiline=False, radius_val=22,
                                         padding=(dp(18), dp(13), dp(18), dp(11)))
        self.msg_input.bind(on_text_validate=self._on_send)
        input_bar.add_widget(self.msg_input)
        holder = AnchorLayout(size_hint_x=None, width=dp(42))
        self.send_btn = SendButton()
        self.send_btn.bind(on_press=self._on_send)
        holder.add_widget(self.send_btn)
        input_bar.add_widget(holder)
        self.root_layout.add_widget(input_bar)

        self.add_widget(self.root_layout)

    def restore_history(self, history, transcript=()):
        """Re-draw a conversation after a theme switch."""
        self.chat_history = list(history)
        if transcript:
            self.chat_content.clear_widgets()
            self.transcript = []
            for entry in transcript:
                if entry['mine']:
                    self._add_user_bubble(entry['text'])
                else:
                    self._add_ai_bubble(entry['text'], entry.get('model'), entry.get('color'), raw=True)

    def _model_status_text(self):
        """Selected model's readable name; the header button itself is only a symbol."""
        model_id = AppState.selected_model
        if not model_id:
            return tr("Model seçilmedi · soldaki simgeye dokunun")
        name = next((m.get('name') for m in AppState.available_models
                     if isinstance(m, dict) and m.get('id') == model_id and m.get('name')), None)
        name = name or model_id.split('/')[-1].replace('models/', '')
        return name[:34] + '…' if len(name) > 35 else name

    def _refresh_model_status(self, *args):
        if not self.request_pending:
            self.ai_status.text = self._model_status_text()

    def _open_model_selector(self, *args):
        ModelSelectorModal(on_selected_callback=self._on_model_changed).open()

    def _on_model_changed(self, new_model):
        self._refresh_model_status()

    def on_enter(self, *args):
        self._refresh_model_status()
        if not AppState.api_key or not AppState.api_key.strip():
            Clock.schedule_once(lambda dt: self._open_settings(), 0.1)

    def _open_settings(self, *args):
        ModernAISettingsModal(on_success_callback=self._on_settings_dismiss).open()

    def _on_settings_dismiss(self, *args):
        self._refresh_model_status()

    def _go_to_terminal(self, *args):
        app = App.get_running_app()
        if app:
            app.select_tab('terminal_screen')

    def _add_user_bubble(self, text):
        self.transcript.append({'mine': True, 'text': str(text)})
        self.chat_content.add_widget(ChatBubble(str(text), mine=True))
        Clock.schedule_once(lambda dt: setattr(self.chat_scroll, 'scroll_y', 0), 0.1)

    def _add_ai_bubble(self, text, model_name=None, text_color=None, raw=False):
        m_tag = model_name or (AppState.api_provider.capitalize() if AppState.api_key else "Modus")
        shown = str(text) if raw else display_ai_text(text)
        bubble = ChatBubble(shown, mine=False, caption=m_tag, text_color=text_color)
        bubble.entry = {'mine': False, 'text': shown, 'model': m_tag, 'color': text_color}
        self.transcript.append(bubble.entry)
        self.chat_content.add_widget(bubble)
        Clock.schedule_once(lambda dt: setattr(self.chat_scroll, 'scroll_y', 0), 0.1)
        return bubble

    def _ensure_market_data(self, on_ready):
        if market_data_is_fresh(AppState.last_market_data):
            on_ready()
            return

        def _fetch_bg():
            try:
                fetcher = MarketDataFetcher()
                payload = fetcher.fetch_all()
                AppState.save_market_data(payload)
            except Exception as exc:
                AppState.last_market_data = {'fetch_error': str(exc)[:120]}
            Clock.schedule_once(lambda dt: on_ready())

        threading.Thread(target=_fetch_bg, daemon=True).start()

    def _build_context_summary(self, topic="", focus=None, trend_data=None, factor_trends=None,
                               cross_lines=None, external_metrics=None):
        d = AppState.last_market_data or {}
        focus = focus or resolve_focus(topic, self.chat_history)
        selected_fred_ids = (set(fred_for_focus(focus)) |
                             {"Net Likidite (yaklaşık)", "Çekirdek PCE Yıllık Değişim", "UNRATE", "GDPC1", "CNH=X",
                              "T10Y3M", "DGS10", "GDP", "Nominal GSYH Yıllık Büyüme",
                              "A091RC1Q027SBEA", "W006RC1Q027SBEA", "Faiz Ödemesi / Vergi Geliri",
                              "ABD 10Y Faiz - Nominal Büyüme (r-g vekili)",
                              "IRLTLT01USM156N", "IRLTLT01JPM156N", "ABD-Japonya 10Y Faiz Farkı (aylık)"}) if focus else None
        selected_yahoo = {
            'gold': {"GC=F", "DX-Y.NYB", "^TNX", "^VIX", "^GVZ", "EURUSD=X", "CNY=X"},
            'spx': {"^TNX", "^VIX", "DX-Y.NYB", "^VIX9D", "^VIX3M", "^VVIX", "^SKEW", "^MOVE"},
            'silver': {"GC=F", "DX-Y.NYB", "^TNX", "^VIX", "^GVZ", "HG=F"},
            'oil': {"CL=F", "BZ=F", "RB=F", "HO=F", "DX-Y.NYB", "^VIX", "^OVX"},
            'brent': {"BZ=F", "CL=F", "RB=F", "HO=F", "DX-Y.NYB", "^VIX", "^OVX"},
            'btc': {"DX-Y.NYB", "^TNX", "^VIX", "^VVIX", "^MOVE"},
            'dollar': {"DX-Y.NYB", "JPY=X", "^TNX", "EURUSD=X", "CNY=X", "^MOVE"},
        }.get(focus, {"DX-Y.NYB", "^TNX", "^VIX"} if focus else None)
        lines = []
        if not d:
            lines.append("Yahoo/FRED piyasa özeti alınamadı; mevcut olmayan sayı veya işlem seviyesi verme.")
        lines.append("Yahoo Finance gözlemleri; borsa kapalıyken son işlem gününe ait olabilir.")
        lines.append("Tarama zamanı (UTC): " + str(d.get('fetched_at', 'bilinmiyor')))
        lines.append("Erişilemeyen kurumsal seriler: ABD 5Y CDS, gerçek SOFR-OIS, çapraz döviz baz swapı, ISM hizmetler PMI, Dünya Altın Konseyi merkez bankası alımları, resmi Çin 10Y tahvil verisi ve gerçek tahvil ihale tail ölçüsü. Bunlara sayı veya trend atfetme.")
        if focus and focus not in {'gold', 'spx', 'silver', 'oil', 'brent', 'btc', 'dollar'}:
            lines.append("Bu varlık için şirket bilançosu, kâr beklentisi, haber ve hacim verisi sağlanmadı; fiyat hareketine temel neden atfetme.")
        if d.get('fetch_error'):
            lines.append("Veri alma hatası: " + d['fetch_error'])
        if d.get('macros'):
            by_name = {name: symbol for name, symbol in YAHOO_MACROS}
            m_strs = []
            for m in d['macros']:
                if selected_yahoo is not None and by_name.get(m[0]) not in selected_yahoo:
                    continue
                if m[1] == 'Veri yok':
                    continue
                observation = d.get('macro_observations', {}).get(by_name.get(m[0]), {})
                stamp = observation.get('timestamp')
                date = datetime.fromtimestamp(stamp, timezone.utc).strftime('%Y-%m-%d') if stamp else 'tarih bilinmiyor'
                m_strs.append(f"{m[0]}: {m[1]} ({m[2]}; gözlem {date})")
            if m_strs:
                lines.append("Yahoo piyasa göstergeleri: " + ", ".join(m_strs))
        if d.get('fred_metrics'):
            fred_lines = [f"{item['name']}: {item['value']:.3f} {item['unit']} "
                          f"(gözlem {item['date']}; {item.get('source', 'FRED')}; "
                          f"{item.get('notes', item.get('frequency', ''))}; "
                          f"{'ESKİ GÖZLEM' if item.get('stale') else 'GÜNCELLEME HATASI; ÖNBELLEK' if item.get('sync_error') else 'son gözlem'})"
                          for item in d['fred_metrics']
                          if item.get('value') is not None and (selected_fred_ids is None or item.get('id') in selected_fred_ids)]
            if fred_lines:
                lines.append("FRED ve USD/CNH verileri: " + "; ".join(fred_lines))
        if d.get('fred_sync_errors'):
            lines.append(f"FRED senkronizasyonunda {len(d['fred_sync_errors'])} seri başarısız; varsa önceki kayıt kullanıldı.")
        external_metrics = external_metrics if external_metrics is not None else d.get('external_metrics', [])
        if external_metrics:
            for item in external_metrics:
                if focus and item.get('focus') and focus not in item['focus']:
                    continue
                if item.get('value') is None:
                    lines.append(f"{item.get('name', item.get('id', 'Harici gösterge'))}: veri alınamadı; sayı veya eğilim üretme.")
                    continue
                lines.append(f"{item['name']}: {item['value']:.3f} {item['unit']} (gözlem {item['date']}; kaynak {item['source']}; {item.get('notes', '')}; {'ESKİ GÖZLEM/ÖNBELLEK' if item.get('stale') or item.get('sync_error') else 'son gözlem'})")
        if focus in (None, 'spx', 'btc') and d.get('vix_curve') and d['vix_curve'][0] != 'Veri yok': lines.append(f"VIX Egrisi: {d['vix_curve'][0]}")
        if focus in (None, 'spx') and d.get('spx_pcr') and d['spx_pcr'][0] != 'Veri yok': lines.append(f"S&P 500 PCR (erişilen vade): {d['spx_pcr'][0]}")
        if focus in (None, 'spx') and d.get('spx_whale') and d['spx_whale'][0] != 'Veri yok': lines.append(f"En yüksek opsiyon hacmi: {d['spx_whale'][0]}")
        if d.get('multi_gex_cards'):
            gex_filter = {'gold': 'GLD', 'spx': 'S&P 500', 'silver': 'SLV', 'oil': 'USO'}
            for g in d['multi_gex_cards']:
                if focus and (focus not in gex_filter or gex_filter[focus] not in g['name']):
                    continue
                spot = parse_level(g['spot_str'])
                h_strs = []
                for h in g['horizons']:
                    h_text = f"{h['label']}: Put={h['put_w']}, Call={h['call_w']}, Flip={h.get('flip_lvl', '-')}, GEX={h['gex_str']}"
                    relative = format_gex_position(gex_position(spot, parse_level(h['put_w']), parse_level(h['call_w']),
                                                                parse_level(h.get('flip_lvl')))) if spot else None
                    h_strs.append(h_text + (f" [{relative}]" if relative else ""))
                if g['spot_str'] != 'Veri yok':
                    lines.append(f"{g['name']} (Spot: {g['spot_str']}) -> " + (" | ".join(h_strs) if h_strs else "Opsiyon zinciri yok"))
            if not focus or focus in gex_filter:
                lines.append("GEX yalnızca erişilen vade ve strike bandında mevcut opsiyon açık pozisyonundan tahmin edilir; tarihsel GEX serisi yok. "
                             "Flip, bant içindeki strike'larla net GEX'in işaret değiştirdiği tahmini spot seviyesidir ('-' ise bantta yok). "
                             "GLD, altın vadelisinin değil ETF opsiyonlarının vekilidir.")
        daily_dynamics = (
            ('junk_stress', "HYG/TLT ETF oranı günlük değişimi (kredi riski iştahı vekili)", (None, 'spx', 'btc')),
            ('btc_momentum', "BTC günlük değişimi (Yahoo son iki günlük bar)", (None, 'btc')),
            ('cu_au', "Bakır/altın vadeli oranı günlük değişimi", (None, 'gold', 'silver', 'oil', 'brent')),
        )
        dynamic_focuses = {
            'vix_short_term': (None, 'spx', 'btc', 'gold'),
            'breadth_rsp_spy': (None, 'spx'),
            'credit_hyg_lqd': (None, 'spx', 'btc'),
            'brent_wti': (None, 'oil', 'brent'),
            'crack_321': (None, 'oil', 'brent'),
        }
        dynamic_notes = {key: notes for key, *_, notes in MARKET_DYNAMICS}
        daily_dynamics += tuple((key, label, dynamic_focuses.get(key, (None,)))
                                for key, label, *_ in MARKET_DYNAMICS)
        for key, label, focuses in daily_dynamics:
            value = d.get(key)
            if focus in focuses and value and value[0] != 'Veri yok':
                note = f" Yorum: {dynamic_notes[key]}" if key in dynamic_notes else ""
                lines.append(f"{label}: {value[0]}; son bar tamamlanmamış olabilir.{note}")
        lines.extend(self._format_trend_context(trend_data or [], factor_trends or []))
        implied_for = {'^GSPC': ('^VIX', 'VIX'), 'SPY': ('^VIX', 'VIX'), 'GC=F': ('^GVZ', 'GVZ'),
                       'GLD': ('^GVZ', 'GVZ'), 'CL=F': ('^OVX', 'OVX'), 'USO': ('^OVX', 'OVX')}
        for item in trend_data or []:
            implied_symbol, implied_name = implied_for.get(item.get('symbol'), (None, None))
            realized = item.get('volatility_20d_pct')
            implied = d.get('macro_observations', {}).get(implied_symbol, {}).get('value') if implied_symbol else None
            if realized and implied:
                lines.append(f"{item['symbol']} ima/gerçekleşen oynaklık: {implied_name} {implied:.2f} − 20 günlük gerçekleşen "
                             f"%{realized:.2f} = {implied - realized:+.2f} puan. Pozitif fark: opsiyonlar sakinliğe göre pahalı "
                             "(risk primi/hedge talebi); negatif: piyasa hareketi ima edilenden büyük.")
        if d.get('calendar_week'):
            lines.append("Bu haftanın kalan yüksek etkili ABD verileri (ForexFactory, saatler UTC): "
                         + " | ".join(d['calendar_week']))
        if d.get('headlines'):
            lines.append("Son 48 saatin başlıkları (yalnızca başlık; içerik bilinmiyor, nedensellik kurma): "
                         + " | ".join(f"[{h['source']} {h['time']}] {h['title']}" for h in d['headlines'][:8]))
        lines.extend(cross_lines or [])
        if any(line.startswith("Göreli seviye") for line in cross_lines or []):
            lines.append("Göreli seviyeler göstergenin kendi geçmiş penceresindeki persentil ve z-skorudur (betimsel); "
                         "yüksek/düşük persentil tek başına dönüş veya yön sinyali değildir.")
        return "\n".join(lines) if len(lines) > 2 else "Piyasa verileri alınamadı. Güncel sayı veya işlem seviyesi verme."

    def _format_trend_context(self, trend_data, factor_trends):
        lines = []
        if not trend_data:
            lines.append("Tarihsel Yahoo fiyat verisi bu istekte alınamadı; 1 ay/1 yıl hareketi ve teknik trend hesaplama.")
        for item in trend_data:
            symbol = item.get('symbol', '?')
            if item.get('latest_close') is None:
                lines.append(f"{symbol}: tarihsel fiyat verisi yok; trend veya getiri hesaplama.")
                continue
            parts = [f"{symbol} ham Yahoo günlük kapanış {item['latest_close']:.3f} (gözlem {item['observation_date']}; {item.get('observation_count', 0)} bar)"]
            if not item.get('sync_ok', True):
                parts.append("son güncelleme başarısız; önbellek kullanıldı")
            if item.get('stale'):
                parts.append("ESKİ GÖZLEM")
            for horizon in ('1m', '3m', '1y'):
                comparison = item.get('returns', {}).get(horizon) or {}
                if comparison.get('value_pct') is not None:
                    parts.append(f"{horizon} değişim {comparison['value_pct']:+.2f}% ({comparison['baseline_date']} → {comparison['end_date']})")
                else:
                    parts.append(f"{horizon} değişim: yeterli tarihli veri yok")
            sma_text = format_sma_position(sma_position(item['latest_close'], item.get('sma')))
            if sma_text:
                parts.append(sma_text)
            if item.get('volatility_20d_pct') is not None:
                parts.append(f"20 bar gerçekleşmiş oynaklık {item['volatility_20d_pct']:.2f}% yıllıklandırılmış")
            year_range = item.get('range_52w')
            if year_range and year_range.get('full_window'):
                parts.append(f"52 hafta aralık {year_range['low']:.3f}–{year_range['high']:.3f}; zirveden {year_range['drawdown_from_high_pct']:+.2f}%; en büyük düşüş {year_range['max_drawdown_pct']:+.2f}%")
            lines.append('; '.join(parts))
        if trend_data:
            lines.append("Fiyat trendi ham kapanıştır: ETF temettüsü/bölünmesi ve vadeli kontrat devri getiriyi çarpıtabilir. Bugünkü günlük bar tamamlanmamış olabilir; trend ölçümü nedensellik kanıtı değildir.")
        for factor in factor_trends:
            parts = [f"{factor['name']} {factor['value']:.3f} {factor['unit']} (FRED gözlem {factor['date']})"]
            if factor.get('stale'):
                parts.append("ESKİ BİLEŞEN GÖZLEMİ")
            if factor.get('notes'):
                parts.append(factor['notes'])
            for horizon in ('1m', '1y'):
                comparison = factor.get('comparisons', {}).get(horizon)
                if comparison:
                    parts.append(f"{horizon} {comparison['value']:+.2f} {comparison['unit']} (baz {comparison['baseline_date']})")
            lines.append('; '.join(parts))
        if factor_trends:
            lines.append("FRED faktörleri farklı yayın sıklığı/gecikmesine sahiptir. Varlık-faktör eş hareketi tek başına neden-sonuç ilişkisi kurmaz.")
        return lines

    def _submit_ai(self, prompt, special_mode=None):
        if self.request_pending:
            return False
        self.request_pending = True
        self.send_btn.disabled = True
        self.ai_status.text = tr("Piyasa verileri ve geçmiş hareketler inceleniyor…")
        self._add_user_bubble(prompt)
        placeholder = self._add_ai_bubble(tr("Piyasa verileri inceleniyor..."), tr("Düşünüyor..."))
        history = list(self.chat_history[-12:])
        focus = resolve_focus(prompt, history)
        def ready():
            def load_trends():
                summaries, factors, cross_lines, external_metrics = [], [], [], None
                try:
                    store = MarketTrendStore()
                    for symbol in symbols_for_focus(focus):
                        sync = store.sync(symbol)
                        summary = store.summary(symbol)
                        summary['sync_ok'] = sync.get('ok', False)
                        summaries.append(summary)
                    level_names = {symbol: name for name, symbol in YAHOO_MACROS}
                    synced = set(symbols_for_focus(focus))
                    for symbol in levels_for_focus(focus):
                        try:
                            if symbol not in synced:
                                store.sync(symbol)
                            text = format_history_position(level_names.get(symbol, symbol),
                                                           history_position(store.history(symbol), years=1, min_count=150))
                            if text:
                                cross_lines.append("Göreli seviye — " + text)
                        except Exception:
                            continue
                    if focus == 'gold':
                        correlation = dated_correlation(store.history('GC=F'), store.history('DX-Y.NYB'))
                        if correlation:
                            cross_lines.append(f"Altın vadeli–DXY günlük getiri korelasyonu, son 90 gün: r={correlation['r']:+.2f}; {correlation['pairs']} eş tarih ({correlation['start_date']}–{correlation['end_date']}). Bu betimsel eş hareket, nedensellik değildir.")
                        ratio = matched_ratio(store.history('HG=F'), store.history('GC=F'))
                        if ratio:
                            ratio_parts = [f"Bakır/altın ham vadeli fiyat oranı {ratio['value']:.6f} (ortak tarih {ratio['date']}; USD/lb ÷ USD/ons, birimsiz değildir)"]
                            for horizon in ('1m', '3m', '1y'):
                                comparison = ratio['comparisons'].get(horizon)
                                if comparison:
                                    ratio_parts.append(f"{horizon} {comparison['value_pct']:+.2f}% (baz {comparison['baseline_date']})")
                            cross_lines.append('; '.join(ratio_parts))
                    if focus in ('spx', 'btc'):
                        symbol = '^GSPC' if focus == 'spx' else 'BTC-USD'
                        correlation = dated_correlation(store.history(symbol), store.history('DX-Y.NYB'))
                        if correlation:
                            cross_lines.append(f"{symbol}–DXY günlük getiri korelasyonu, son 90 gün: r={correlation['r']:+.2f}; {correlation['pairs']} eş tarih. Nedensellik değildir.")
                except Exception:
                    pass
                try:
                    fred = FredStore()
                    factors = fred.trend_changes(fred_for_focus(focus)) + fred.derived_trend_changes()
                    fred_names = {item.get('id'): (item.get('name'), item.get('unit', ''))
                                  for item in (AppState.last_market_data or {}).get('fred_metrics', [])}
                    for series_id in fred_for_focus(focus):
                        if series_id not in FRED_LEVEL_SERIES:
                            continue
                        name, unit = fred_names.get(series_id, (series_id, ''))
                        text = format_history_position(name or series_id,
                                                       history_position(fred.recent(series_id, 3000), years=5, min_count=24), unit)
                        if text:
                            cross_lines.append("Göreli seviye (FRED) — " + text)
                    if focus in ('oil', 'brent') and summaries:
                        symbol = 'CL=F' if focus == 'oil' else 'BZ=F'
                        correlation = dated_correlation(store.history(symbol), fred.recent('T10YIE', 180), second_relative=False)
                        if correlation:
                            cross_lines.append(f"{symbol} günlük getirisi–10Y enflasyon beklentisi günlük değişimi korelasyonu, son 90 gün: r={correlation['r']:+.2f}; {correlation['pairs']} eş tarih. Nedensellik veya arz şoku kanıtı değildir.")
                except Exception:
                    pass
                try:
                    cache_dir = os.path.join(os.path.dirname(fred_database_path()), 'external_macro_cache')
                    external_metrics = ExternalMacroFeed(cache_path=cache_dir).fetch_metrics()
                    fred_metrics = (AppState.last_market_data or {}).get('fred_metrics', [])
                    external_metrics += cross_metrics(fred_metrics, external_metrics)
                except Exception:
                    pass
                context =self._build_context_summary(prompt, focus, summaries, factors,
                                                      cross_lines, external_metrics)
                query_ai_service(prompt, context,
                                 lambda answer, color, tag, ok: self._handle_ai_response(
                                     answer, color, tag, ok, prompt, placeholder),
                                 special_mode=special_mode, chat_history=history)
            threading.Thread(target=load_trends, daemon=True).start()
        self._ensure_market_data(ready)
        return True

    def _on_quick_analysis(self, *args):
        self._submit_ai(tr("Erişilebilir piyasa göstergelerini ve GEX verilerini analiz et."), "summary")

    def _on_spx_plan(self, *args):
        self._submit_ai(tr("S&P 500 için erişilebilir piyasa ve opsiyon verilerini değerlendir."), "spx_plan")

    def _on_send(self, *args):
        txt = self.msg_input.text.strip()
        if txt and self._submit_ai(txt):
            self.msg_input.text = ''

    def _handle_ai_response(self, reply_text, color, model_name, ok, prompt, placeholder):
        if placeholder.parent is self.chat_content:
            self.chat_content.remove_widget(placeholder)
        if getattr(placeholder, 'entry', None) in self.transcript:
            self.transcript.remove(placeholder.entry)
        self._add_ai_bubble(reply_text, model_name, color)
        if ok:
            self.chat_history.extend(({"role": "user", "content": prompt},
                                      {"role": "assistant", "content": reply_text}))
            self.chat_history = self.chat_history[-12:]
        self.request_pending = False
        self.send_btn.disabled = False
        self.ai_status.text = self._model_status_text() if ok else tr("Yanıt alınamadı · Ayarları veya bağlantıyı kontrol edin")


def start_android_background_service():
    """Android Foreground Background Service'i başlatır (24/7 arkaplan takibi)."""
    try:
        from jnius import autoclass
        PythonActivity = autoclass('org.kivy.android.PythonActivity')
        mActivity = PythonActivity.mActivity
        if mActivity:
            service = autoclass('org.godmode.borsaradar.ServiceModusservice')
            service.start(mActivity, '')
            print("[Service] ModusService 24/7 arka plan servisi baslatildi.")
    except Exception as e:
        print(f"[Service Note] {e}")


# ---------------------------------------------------------
# ANA KIVY UYGULAMASI
# ---------------------------------------------------------
class WallStreetApp(App):
    TABS = (('terminal_screen', 'Piyasa', 'chart'), ('ai_screen', 'Asistan', 'chat'))

    def build(self):
        self.title = "Modus"
        ui_text.activate(i18n.load_language())
        AppState.load_all()
        AlarmManager.load_alarms()
        NotificationEngine.init_engine()
        theme.apply(theme.load_mode())
        self.container = BoxLayout(orientation='vertical')
        self._build_ui()
        return self.container

    def _build_ui(self, current='terminal_screen', conversation=None):
        """(Re)create screens with the active palette; widgets read colours when built."""
        Window.clearcolor = hex_color(BG_DARK)
        theme.style_system_bars()
        self.container.clear_widgets()
        self.sm = ScreenManager(transition=NoTransition())
        self.sm.add_widget(TerminalScreen(name='terminal_screen'))
        ai_screen = AIScreen(name='ai_screen')
        if conversation:
            ai_screen.restore_history(*conversation)
        self.sm.add_widget(ai_screen)
        self.sm.current = current
        self.tab_bar = TabBar(tuple((name, tr(label), icon) for name, label, icon in self.TABS), current, self.select_tab)
        self.container.add_widget(self.sm)
        self.container.add_widget(self.tab_bar)

    def select_tab(self, name):
        if self.sm.current != name:
            self.sm.current = name
        self.tab_bar.select(name)

    def apply_theme(self, mode=None):
        if mode:
            theme.save_mode(mode)
        previous = theme.name
        theme.apply(mode or theme.mode)
        if mode or theme.name != previous:
            ai_screen = self.sm.get_screen('ai_screen')
            self._build_ui(self.sm.current, (ai_screen.chat_history, ai_screen.transcript))

    def apply_language(self, code):
        """Switch the interface language and rebuild screens, keeping the conversation."""
        if code == i18n.current:
            return
        i18n.save_language(code)
        ui_text.activate(code)
        ai_screen = self.sm.get_screen('ai_screen')
        self._build_ui(self.sm.current, (ai_screen.chat_history, ai_screen.transcript))

    def on_start(self):
        Clock.schedule_once(lambda dt: start_android_background_service(), 2.0)

    def on_resume(self):
        # "Sistem" follows the phone's dark-mode setting, which may change while paused.
        if theme.mode == 'system':
            self.apply_theme()


if __name__ == '__main__':
    WallStreetApp().run()
