import os
import math
import json
import urllib.request
import threading
from datetime import datetime

from kivy.app import App
from kivy.lang import Builder
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.core.window import Window
from kivy.clock import Clock
from kivy.utils import get_color_from_hex

# ---------------------------------------------------------
# UI TASARIMI (KV LANGUAGE) - MINIMALIST & PROFESYONEL
# ---------------------------------------------------------
KV = '''
#:import hex kivy.utils.get_color_from_hex

<DataCard@BoxLayout>:
    orientation: 'vertical'
    padding: dp(15)
    spacing: dp(10)
    size_hint_y: None
    height: self.minimum_height
    canvas.before:
        Color:
            rgba: hex('#1E1E1E')
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(12)]

<MetricRow@BoxLayout>:
    title: ''
    value: ''
    val_color: '#FFFFFF'
    size_hint_y: None
    height: dp(25)
    Label:
        text: root.title
        color: hex('#9E9E9E') # Gri
        font_size: '15sp'
        halign: 'left'
        valign: 'middle'
        text_size: self.size
    Label:
        text: root.value
        color: hex(root.val_color)
        font_size: '16sp'
        bold: True
        halign: 'right'
        valign: 'middle'
        text_size: self.size
        markup: True

<MainLayout>:
    orientation: 'vertical'
    padding: dp(15)
    spacing: dp(15)
    canvas.before:
        Color:
            rgba: hex('#121212') # Derin Siyah Arka Plan
        Rectangle:
            pos: self.pos
            size: self.size

    # Ust Baslik
    Label:
        text: 'WALL STREET RADAR'
        font_size: '22sp'
        bold: True
        color: hex('#FFFFFF')
        size_hint_y: None
        height: dp(40)
        halign: 'center'
        valign: 'middle'
        text_size: self.size

    # Kaydirilabilir Icerik Alani
    ScrollView:
        do_scroll_x: False
        do_scroll_y: True
        GridLayout:
            id: content_grid
            cols: 1
            spacing: dp(15)
            size_hint_y: None
            height: self.minimum_height

    # Alt Buton
    Button:
        id: scan_btn
        text: 'PİYASAYI TARA'
        font_size: '16sp'
        bold: True
        size_hint_y: None
        height: dp(55)
        background_normal: ''
        background_color: hex('#2962FF') # Profesyonel Mavi
        color: hex('#FFFFFF')
        on_press: app.start_fetch()
        canvas.before:
            Color:
                rgba: hex('#2962FF') if self.state == 'normal' else hex('#1565C0')
            RoundedRectangle:
                pos: self.pos
                size: self.size
                radius: [dp(8)]
'''

# ---------------------------------------------------------
# SAF PYTHON MATEMATIK MOTORU
# ---------------------------------------------------------
def norm_pdf(x):
    return math.exp(-x**2 / 2.0) / math.sqrt(2.0 * math.pi)

def compute_gamma(S, K, T, r, sigma):
    if T <= 0 or sigma <= 0: return 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    return norm_pdf(d1) / (S * sigma * math.sqrt(T))

def get_json(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.loads(response.read())

def get_history(ticker):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=2d&interval=1d"
    data = get_json(url)
    closes = data['chart']['result'][0]['indicators']['quote'][0]['close']
    v = [c for c in closes if c is not None]
    if len(v) >= 2: return v[-2], v[-1]
    elif len(v) == 1: return v[-1], v[-1]
    return 0, 0

# ---------------------------------------------------------
# KIVY WIDGET SINIFLARI
# ---------------------------------------------------------
class MetricRow(BoxLayout):
    pass

class DataCard(BoxLayout):
    def add_title(self, title_text):
        lbl = Label(text=title_text, bold=True, color=get_color_from_hex('#FFFFFF'), font_size='18sp', size_hint_y=None, height=40, halign='left', valign='middle')
        lbl.bind(size=lbl.setter('text_size'))
        self.add_widget(lbl)

    def add_metric(self, title, value, val_color='#FFFFFF'):
        row = MetricRow()
        row.title = title
        row.value = value
        row.val_color = val_color
        self.add_widget(row)

class MainLayout(BoxLayout):
    pass

# ---------------------------------------------------------
# ANA UYGULAMA SINIFI
# ---------------------------------------------------------
class WallStreetApp(App):
    def build(self):
        Window.clearcolor = get_color_from_hex('#121212')
        Builder.load_string(KV)
        self.main_ui = MainLayout()
        
        # Baslangic Mesaji
        self.add_status_card("Sistem Hazır", "Güncel verileri almak için taramayı başlatın.", "#9E9E9E")
        return self.main_ui

    def add_status_card(self, title, message, color_hex):
        self.main_ui.ids.content_grid.clear_widgets()
        card = DataCard()
        card.add_title(title)
        
        lbl = Label(text=message, color=get_color_from_hex(color_hex), font_size='15sp', size_hint_y=None, halign='left', valign='middle')
        lbl.bind(texture_size=lbl.setter('size'))
        lbl.bind(size=lbl.setter('text_size'))
        card.add_widget(lbl)
        
        self.main_ui.ids.content_grid.add_widget(card)

    def start_fetch(self):
        self.main_ui.ids.scan_btn.text = 'VERİLER ÇEKİLİYOR...'
        self.main_ui.ids.scan_btn.disabled = True
        self.add_status_card("Taranıyor", "Wall Street sunucularına bağlanılıyor...\nLütfen bekleyin.", "#2962FF")
        threading.Thread(target=self.run_logic).start()

    def run_logic(self):
        # Arayuz guncellemeleri listesi
        cards_data = []
        
        try:
            # 1. MAKRO VERILER
            macro_card = DataCard()
            macro_card.add_title("Makro Ekonomi")
            
            macros = [("^VIX", "VIX (Korku)"), ("^TNX", "10Y Tahvil"), ("HYG", "Çöp Tahvil"), ("BTC-USD", "Bitcoin")]
            for sym, name in macros:
                try:
                    prev, curr = get_history(sym)
                    if prev > 0:
                        pct = ((curr - prev) / prev) * 100
                        color = "#00E676" if pct > 0 else "#FF1744"
                        # Formatlama: 10Y tahvil icin ekstra
                        val_str = f"{curr:.2f} ({pct:+.2f}%)"
                        macro_card.add_metric(name, val_str, color)
                except:
                    pass
            cards_data.append(macro_card)
            
            # 2. SPX GEX ANALIZI
            spx_card = DataCard()
            spx_card.add_title("S&P 500 Analizi")
            
            spot = get_json("https://query1.finance.yahoo.com/v8/finance/chart/^SPX?range=1d&interval=1d")['chart']['result'][0]['meta']['regularMarketPrice']
            spx_card.add_metric("Spot Fiyat", f"{spot:,.2f}", "#FFFFFF")
            
            url = "https://query1.finance.yahoo.com/v7/finance/options/^SPX"
            opt_data = get_json(url)['optionChain']['result'][0]
            dt = datetime.fromtimestamp(opt_data['expirationDates'][0])
            spx_card.add_metric("Yaklaşan Vade", dt.strftime('%Y-%m-%d'), "#9E9E9E")
            
            options = opt_data['options'][0]
            T_val = max((dt - datetime.now()).days, 1) / 365.0
            r_val = 0.045
            min_k = spot * 0.96
            max_k = spot * 1.04
            
            total_call_gex = 0
            total_put_gex = 0
            max_c_vol = 0
            max_c_strike = 0
            max_p_vol = 0
            max_p_strike = 0
            
            for c in options.get('calls', []):
                v = c.get('volume', 0)
                if v > max_c_vol: max_c_vol, max_c_strike = v, c.get('strike', 0)
                k = c.get('strike', 0)
                if min_k <= k <= max_k:
                    iv, oi = c.get('impliedVolatility', 0), max(c.get('openInterest', 0), v)
                    if oi > 0 and iv > 0:
                        total_call_gex += compute_gamma(spot, k, T_val, r_val, iv) * oi * 100 * (spot ** 2) * 0.01
                        
            for p in options.get('puts', []):
                v = p.get('volume', 0)
                if v > max_p_vol: max_p_vol, max_p_strike = v, p.get('strike', 0)
                k = p.get('strike', 0)
                if min_k <= k <= max_k:
                    iv, oi = p.get('impliedVolatility', 0), max(p.get('openInterest', 0), v)
                    if oi > 0 and iv > 0:
                        total_put_gex += compute_gamma(spot, k, T_val, r_val, iv) * oi * 100 * (spot ** 2) * 0.01

            # Balina Islemi
            if max_c_vol > max_p_vol and max_c_vol > 0:
                spx_card.add_metric("Balina İşlemi", f"{max_c_strike} CALL", "#00E676")
            elif max_p_vol > 0:
                spx_card.add_metric("Balina İşlemi", f"{max_p_strike} PUT", "#FF1744")

            # GEX Yorumlama
            net_gex = (total_call_gex - total_put_gex) / 1e9
            color = "#00E676" if net_gex > 0 else "#FF1744"
            spx_card.add_metric("Net GEX Sinyali", f"{net_gex:+.2f} Milyar $", color)
            
            cards_data.append(spx_card)
            Clock.schedule_once(lambda dt: self.render_cards(cards_data))
            
        except Exception as e:
            Clock.schedule_once(lambda dt: self.add_status_card("Hata Oluştu", f"Sunucu hatası: {str(e)}", "#FF1744"))
        finally:
            Clock.schedule_once(lambda dt: self.reset_btn())
            
    def render_cards(self, cards):
        self.main_ui.ids.content_grid.clear_widgets()
        for card in cards:
            self.main_ui.ids.content_grid.add_widget(card)

    def reset_btn(self):
        self.main_ui.ids.scan_btn.text = 'PİYASAYI TARA'
        self.main_ui.ids.scan_btn.disabled = False

if __name__ == '__main__':
    WallStreetApp().run()
