import numpy as np
import pandas as pd
import os
import yfinance as yf
from scipy.stats import norm
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.columns import Columns
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
import warnings

warnings.filterwarnings("ignore", category=FutureWarning)

console = Console()
SPX_PCR_TEXT = "N/A"
SPX_WHALE_TEXT = "N/A"
SPX_SKEW_TEXT = "N/A"


# ---------------------------------------------------------
# 1. TAM BLACK-SCHOLES GREEKS HESAPLAMA MOTORU
# ---------------------------------------------------------
class BSGreeksEngine:
    @staticmethod
    def _d1_d2(S, K, T, r, sigma):
        if T <= 0 or sigma <= 0:
            return 0.0, 0.0
        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)
        return d1, d2

    @classmethod
    def compute_gamma(cls, S, K, T, r, sigma):
        if T <= 0 or sigma <= 0:
            return 0.0
        d1, _ = cls._d1_d2(S, K, T, r, sigma)
        pdf_d1 = norm.pdf(d1)
        sqrt_T = np.sqrt(T)
        gamma = pdf_d1 / (S * sigma * sqrt_T)
        return gamma

# ---------------------------------------------------------
# 2. VARLIK KONFIGURASYONLARI
# ---------------------------------------------------------
CONFIG = [
    {"name": "S&P 500 (SPX)", "symbol": "^SPX", "multiplier": 100, "strike_band": 0.04},
    {"name": "Gold ETF (GLD)", "symbol": "GLD", "multiplier": 100, "strike_band": 0.05},
    {"name": "Silver ETF (SLV)", "symbol": "SLV", "multiplier": 100, "strike_band": 0.06},
    {"name": "Crude Oil ETF (USO)", "symbol": "USO", "multiplier": 100, "strike_band": 0.06}
]

MACRO_CONFIG = [
    {"name": "5-Year Yield (2Y Muadili)", "symbol": "^FVX"}, 
    {"name": "10-Year Yield", "symbol": "^TNX"},
    {"name": "30-Year Yield", "symbol": "^TYX"},
    {"name": "VIX Endeksi", "symbol": "^VIX"},
    {"name": "MOVE Endeksi (Tahvil Korkusu)", "symbol": "^MOVE"},
    {"name": "TIP (Reel Faiz Stresi)", "symbol": "TIP"},
    {"name": "EEM (Gelisen Piyasalar Likiditesi)", "symbol": "EEM"},
    {"name": "Dolar Endeksi (DXY)", "symbol": "DX-Y.NYB"}
]

# ---------------------------------------------------------
# 3. PROFESYONEL VERI MODULLERI
# ---------------------------------------------------------

def fetch_junk_bond_stress():
    try:
        data = yf.download("HYG TLT", period='2d', group_by='ticker', auto_adjust=True, progress=False)
        hyg_prev, hyg_curr = data['HYG']['Close'].dropna().iloc[-2:]
        tlt_prev, tlt_curr = data['TLT']['Close'].dropna().iloc[-2:]
        
        ratio_prev = hyg_prev / tlt_prev
        ratio_curr = hyg_curr / tlt_curr
        
        pct_change = ((ratio_curr - ratio_prev) / ratio_prev) * 100
        status = "Risk-Off (Kriz Beklentisi)" if pct_change < 0 else "Risk-On (Cosku)"
        color = "red" if pct_change < 0 else "green"
        
        return f"[{color}]{pct_change:+.2f}% ({status})[/]"
    except Exception:
        return "N/A"



def fetch_comex_data():
    comex_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Comex_Verileri")
    if not os.path.exists(comex_dir):
        os.makedirs(comex_dir)
        return "[dim]Comex_Verileri klasoru bos. Dosya bekliyor...[/]"
    
    try:
        files = [os.path.join(comex_dir, f) for f in os.listdir(comex_dir) if f.endswith('.xlsx') or f.endswith('.xls') or f.endswith('.csv')]
        if not files:
            return "[dim]Comex_Verileri klasoru bos. Dosya bekliyor...[/]"
        
        latest_file = max(files, key=os.path.getmtime)
        filename = os.path.basename(latest_file)
        
        if filename.endswith('.csv'):
            df = pd.read_csv(latest_file, header=None)
        else:
            df = pd.read_excel(latest_file, header=None)
            
        tot_reg = df[df[0].astype(str).str.contains('TOTAL REGISTERED', na=False, case=False)]
        tot_elig = df[df[0].astype(str).str.contains('TOTAL ELIGIBLE', na=False, case=False)]
        comb_tot = df[df[0].astype(str).str.contains('COMBINED TOTAL', na=False, case=False)]
        
        if not tot_reg.empty and not comb_tot.empty and not tot_elig.empty:
            reg_today = float(tot_reg.iloc[0, 7]) / 1e6
            reg_prev = float(tot_reg.iloc[0, 2]) / 1e6
            reg_pct = ((reg_today - reg_prev) / reg_prev) * 100 if reg_prev else 0
            
            elig_today = float(tot_elig.iloc[0, 7]) / 1e6
            elig_prev = float(tot_elig.iloc[0, 2]) / 1e6
            elig_pct = ((elig_today - elig_prev) / elig_prev) * 100 if elig_prev else 0
            
            tot_today = float(comb_tot.iloc[0, 7]) / 1e6
            tot_prev = float(comb_tot.iloc[0, 2]) / 1e6
            tot_pct = ((tot_today - tot_prev) / tot_prev) * 100 if tot_prev else 0
            
            c_reg = 'green' if reg_pct > 0 else 'red'
            c_reg = 'green' if reg_pct > 0 else 'red'
            c_elig = 'green' if elig_pct > 0 else 'red'
            c_tot = 'green' if tot_pct > 0 else 'red'
            
            if reg_pct < -0.5:
                sonuc = "[bold red]Kritik Squeeze Riski (Reg Azaliyor!)[/]"
            elif reg_pct < 0:
                sonuc = "[red]Fiziksel Azalis (Kitlik Sinyali)[/]"
            else:
                sonuc = "[green]Stoklar Stabil[/]"
                
            return f"Reg: {reg_today:.1f}M oz ([{c_reg}]{reg_pct:+.2f}%[/]) | Elig: {elig_today:.1f}M oz ([{c_elig}]{elig_pct:+.2f}%[/]) | Top: {tot_today:.1f}M oz ([{c_tot}]{tot_pct:+.2f}%[/]) -> Sonuc: {sonuc}"
        else:
            return f"[cyan]Baglanti Basarili ({filename}) - Format Tanimlanamadi.[/]"
    except Exception as e:
        return f"[red]Dosya Okuma Hatasi (Bozuk dosya veya yanlis format)[/]"

def fetch_copper_gold_ratio():
    try:
        data = yf.download("HG=F GC=F", period='2d', group_by='ticker', auto_adjust=True, progress=False)
        cu_prev, cu_curr = data['HG=F']['Close'].dropna().iloc[-2:]
        au_prev, au_curr = data['GC=F']['Close'].dropna().iloc[-2:]
        
        ratio_prev = cu_prev / au_prev
        ratio_curr = cu_curr / au_curr
        
        pct_change = ((ratio_curr - ratio_prev) / ratio_prev) * 100
        status = "Buyume (Risk-On)" if pct_change > 0 else "Resesyon Korkusu"
        color = "green" if pct_change > 0 else "red"
        
        return f"[{color}]{pct_change:+.2f}% ({status})[/]"
    except Exception:
        return "N/A"

def fetch_bitcoin_momentum():
    try:
        data = yf.download("BTC-USD", period='2d', auto_adjust=True, progress=False)
        hist = data['Close'].dropna()
        if len(hist) >= 2:
            pct = ((hist.iloc[-1] - hist.iloc[-2]) / hist.iloc[-2]) * 100
            status = "Pozitif" if pct > 0 else "Negatif"
            color = "green" if pct > 0 else "red"
            return f"[{color}]{pct:+.2f}% ({status})[/]"
        return "N/A"
    except Exception:
        return "N/A"

def fetch_vix_curve():

    try:
        vix = yf.Ticker('^VIX').history(period='1d')['Close'].iloc[-1]
        vix3m = yf.Ticker('^VIX3M').history(period='1d')['Close'].iloc[-1]
        status = "CONTANGO (Sakin)" if vix3m > vix else "BACKWARDATION (Panik)"
        color = "green" if vix3m > vix else "bold red"
        return f"[{color}]{status}[/] (VIX: {vix:.2f}, VIX3M: {vix3m:.2f})"
    except Exception:
        return "N/A"

def fetch_sector_rotation():
    sectors = {
        'XLK': 'Teknoloji', 'XLY': 'Luks Tuketim', 'XLF': 'Finans',
        'XLV': 'Saglik', 'XLE': 'Enerji', 'XLI': 'Endustri',
        'XLP': 'Temel Tuketim', 'XLU': 'Altyapi', 'XLC': 'Iletisim'
    }
    try:
        tickers = " ".join(sectors.keys())
        data = yf.download(tickers, period='1mo', group_by='ticker', auto_adjust=True, progress=False)
        
        def get_top_bot(period_days):
            changes = {}
            for t in sectors.keys():
                if t in data and not data[t].empty:
                    hist = data[t]['Close'].dropna()
                    if len(hist) > period_days:
                        pct = ((hist.iloc[-1] - hist.iloc[-(period_days+1)]) / hist.iloc[-(period_days+1)]) * 100
                        changes[sectors[t]] = pct
            sorted_sectors = sorted(changes.items(), key=lambda x: x[1], reverse=True)
            if not sorted_sectors: return "N/A", "N/A"
            top_str = ", ".join([f"[green]{s} (+{p:.1f}%)[/]" for s, p in sorted_sectors[:2]])
            bot_str = ", ".join([f"[red]{s} ({p:.1f}%)[/]" for s, p in sorted_sectors[-2:]])
            return top_str, bot_str
            
        top_1d, bot_1d = get_top_bot(1)
        top_1w, bot_1w = get_top_bot(5) # 5 is 1 week
        top_1m, bot_1m = get_top_bot(20) # 20 is 1 month
        
        return (top_1d, bot_1d), (top_1w, bot_1w), (top_1m, bot_1m)
    except Exception:
        return ("N/A", "N/A"), ("N/A", "N/A"), ("N/A", "N/A")

def fetch_market_breadth():
    dow30 = ['AAPL','MSFT','JPM','V','UNH','JNJ','WMT','PG','HD','CVX',
             'MRK','KO','CSCO','PEP','MCD','TRV','AXP','IBM','GS','BA',
             'CAT','HON','DIS','VZ','NKE','AMGN','CRM','INTC','DOW','AMZN']
    try:
        data = yf.download(" ".join(dow30), period='3mo', group_by='ticker', auto_adjust=True, progress=False)
        above_50 = 0
        total = 0
        for t in dow30:
            if t in data and not data[t].empty:
                hist = data[t]['Close'].dropna()
                if len(hist) >= 50:
                    ma50 = hist.tail(50).mean()
                    last = hist.iloc[-1]
                    if last > ma50:
                        above_50 += 1
                    total += 1
        if total > 0:
            pct = (above_50 / total) * 100
            status = "Guclu" if pct > 50 else "Zayif"
            color = "green" if pct > 50 else "red"
            return f"[{color}]%{pct:.0f} Katilim ({status})[/]"
        return "N/A"
    except Exception:
        return "N/A"

def fetch_economic_calendar():
    try:
        req = urllib.request.Request('https://nfs.faireconomy.media/ff_calendar_thisweek.xml', headers={'User-Agent': 'Mozilla/5.0'})
        xml_data = urllib.request.urlopen(req, timeout=5).read()
        root = ET.fromstring(xml_data)
        
        today_str = datetime.now().strftime("%m-%d-%Y")
        events = []
        for event in root.findall('event'):
            country = event.find('country').text
            impact = event.find('impact').text
            date_str = event.find('date').text
            
            if country == 'USD' and impact == 'High' and date_str == today_str:
                time_str = event.find('time').text
                title = event.find('title').text
                events.append(f"{time_str} - {title}")
                
        if events:
            return "[bold red]" + " | ".join(events) + "[/]"
        else:
            return "[dim]Bugun kritik bir veri beklenmiyor.[/]"
    except Exception:
        return "[dim]Takvim alinamadi.[/]"

def fetch_macros():
    records = []
    for m in MACRO_CONFIG:
        try:
            tk = yf.Ticker(m['symbol'])
            hist = tk.history(period="2d")
            if len(hist) >= 2:
                prev = hist['Close'].iloc[-2]
                curr = hist['Close'].iloc[-1]
                pct = ((curr - prev) / prev) * 100
                records.append({"Gosterge": m['name'], "Deger": f"{curr:.2f}", "Degisim": f"{pct:+.2f}%"})
            elif len(hist) == 1:
                curr = hist['Close'].iloc[-1]
                records.append({"Gosterge": m['name'], "Deger": f"{curr:.2f}", "Degisim": "N/A"})
        except Exception:
            pass
    return records

def find_zero_gamma(df):
    if df.empty or 'net_gex' not in df.columns:
        return None
    grouped = df.groupby('strike')['net_gex'].sum().sort_index()
    cum_gex = grouped.cumsum()
    sign_changes = np.where(np.diff(np.sign(cum_gex)))[0]
    if len(sign_changes) > 0:
        idx = sign_changes[0]
        s1, s2 = cum_gex.index[idx], cum_gex.index[idx + 1]
        g1, g2 = cum_gex.iloc[idx], cum_gex.iloc[idx + 1]
        if g2 != g1:
            flip_level = s1 - g1 * ((s2 - s1) / (g2 - g1))
            return round(flip_level, 2)
    return round(grouped.abs().idxmin(), 2)

def process_asset(asset):
    global SPX_PCR_TEXT
    name = asset["name"]
    symbol = asset["symbol"]
    mult = asset["multiplier"]
    band = asset["strike_band"]

    tk = yf.Ticker(symbol)
    
    try:
        hist = tk.history(period="1d")
        if hist.empty:
            return None
        spot_price = hist['Close'].iloc[-1]
    except Exception:
        return None

    options_dates = tk.options
    if not options_dates:
        return None
    
    exp = options_dates[0]
    opt = tk.option_chain(exp)
    
    if symbol == "^SPX":
        try:
            global SPX_WHALE_TEXT, SPX_SKEW_TEXT
            # 1. PCR
            total_call_vol = opt.calls['volume'].sum() if 'volume' in opt.calls.columns else 0
            total_put_vol = opt.puts['volume'].sum() if 'volume' in opt.puts.columns else 0
            if total_call_vol > 0:
                pcr = total_put_vol / total_call_vol
                color = "red" if pcr > 1.0 else ("green" if pcr < 0.7 else "yellow")
                status = "Asiri Korku" if pcr > 1.0 else ("Asiri Cosku" if pcr < 0.7 else "Normal")
                SPX_PCR_TEXT = f"[{color}]{pcr:.2f} ({status})[/]"
                
            # 2. Whale Trade
            c_max_idx = opt.calls['volume'].idxmax()
            p_max_idx = opt.puts['volume'].idxmax()
            c_max_vol = opt.calls.loc[c_max_idx]['volume'] if pd.notna(c_max_idx) else 0
            p_max_vol = opt.puts.loc[p_max_idx]['volume'] if pd.notna(p_max_idx) else 0
            
            if c_max_vol > p_max_vol and c_max_vol > 0:
                strike = opt.calls.loc[c_max_idx]['strike']
                SPX_WHALE_TEXT = f"[bold green]{strike} CALL (Hacim: {int(c_max_vol):,})[/]"
            elif p_max_vol > 0:
                strike = opt.puts.loc[p_max_idx]['strike']
                SPX_WHALE_TEXT = f"[bold red]{strike} PUT (Hacim: {int(p_max_vol):,})[/]"

            # 3. Volatility Skew
            put_target = spot_price * 0.95
            call_target = spot_price * 1.05
            
            put_closest = opt.puts.iloc[(opt.puts['strike'] - put_target).abs().argsort()[:1]]
            call_closest = opt.calls.iloc[(opt.calls['strike'] - call_target).abs().argsort()[:1]]
            
            put_iv = put_closest['impliedVolatility'].values[0] if not put_closest.empty else 0
            call_iv = call_closest['impliedVolatility'].values[0] if not call_closest.empty else 0
            
            if call_iv > 0:
                skew = put_iv / call_iv
                s_color = "red" if skew > 1.5 else ("green" if skew < 0.8 else "yellow")
                s_status = "Asiri Korku (Sigorta Pahali)" if skew > 1.5 else ("Asiri Cosku" if skew < 0.8 else "Dengeli")
                SPX_SKEW_TEXT = f"[{s_color}]{skew:.2f} ({s_status})[/]"
        except Exception:
            pass
    
    today = pd.Timestamp.now().normalize()
    days_to_exp = max((pd.to_datetime(exp) - today).days, 1)
    T_val = days_to_exp / 365.0
    r_val = 0.045
    
    min_strike = spot_price * (1 - band)
    max_strike = spot_price * (1 + band)

    records = []
    
    calls = opt.calls
    calls = calls[(calls['strike'] >= min_strike) & (calls['strike'] <= max_strike)]
    for _, row in calls.iterrows():
        k = row['strike']
        iv = row['impliedVolatility']
        raw_oi = row['openInterest'] if not pd.isna(row['openInterest']) else 0
        raw_vol = row['volume'] if not pd.isna(row['volume']) else 0
        oi = max(raw_oi, raw_vol)
        
        if oi == 0 or iv == 0: continue
        gamma = BSGreeksEngine.compute_gamma(spot_price, k, T_val, r_val, iv)
        dollar_gex = gamma * oi * mult * (spot_price ** 2) * 0.01
        records.append({'strike': k, 'right': 'C', 'oi': oi, 'gamma': gamma, 'net_gex': dollar_gex, 'call_gex': dollar_gex, 'put_gex': 0})
        
    puts = opt.puts
    puts = puts[(puts['strike'] >= min_strike) & (puts['strike'] <= max_strike)]
    for _, row in puts.iterrows():
        k = row['strike']
        iv = row['impliedVolatility']
        raw_oi = row['openInterest'] if not pd.isna(row['openInterest']) else 0
        raw_vol = row['volume'] if not pd.isna(row['volume']) else 0
        oi = max(raw_oi, raw_vol)
        
        if oi == 0 or iv == 0: continue
        gamma = BSGreeksEngine.compute_gamma(spot_price, k, T_val, r_val, iv)
        dollar_gex = gamma * oi * mult * (spot_price ** 2) * 0.01
        records.append({'strike': k, 'right': 'P', 'oi': oi, 'gamma': gamma, 'net_gex': -dollar_gex, 'call_gex': 0, 'put_gex': dollar_gex})

    df = pd.DataFrame(records)
    if df.empty: return None

    call_wall = df.groupby('strike')['call_gex'].sum().idxmax()
    put_wall = df.groupby('strike')['put_gex'].sum().idxmax()
    gamma_flip = find_zero_gamma(df)
    total_net_gex_m = df['net_gex'].sum() / 1e6

    return {
        "Varlik": name, "Spot": f"{spot_price:,.2f}", "Vade": exp,
        "Put Wall (Destek)": f"{put_wall:,.2f}", "Call Wall (Direnc)": f"{call_wall:,.2f}",
        "Gamma Flip": f"{gamma_flip:,.2f}" if gamma_flip else "N/A",
        "Net GEX ($M/1%)": f"{total_net_gex_m:+.2f}M"
    }

def main():
    console.print(f"[bold cyan]Yahoo Finance Profesyonel Trader Terminali Yukleniyor...[/]")
    
    # Verileri Çek
    macro_records = fetch_macros()
    vix_curve_text = fetch_vix_curve()
    res_sectors = fetch_sector_rotation()
    top_1d, bot_1d = res_sectors[0]
    top_1w, bot_1w = res_sectors[1]
    top_1m, bot_1m = res_sectors[2]
    breadth_text = fetch_market_breadth()
    calendar_text = fetch_economic_calendar()
    junk_stress_text = fetch_junk_bond_stress()
    btc_text = fetch_bitcoin_momentum()
    cu_au_text = fetch_copper_gold_ratio()
    comex_text = fetch_comex_data()
    
    results = []
    for asset in CONFIG:
        try:
            res = process_asset(asset)
            if res: results.append(res)
        except Exception:
            pass

    console.print("")

    # Makro Tablosu
    if macro_records:
        t_macro = Table(title="Sabah Makro Ekonomik Gostergeler", show_header=True, header_style="bold yellow")
        t_macro.add_column("Gosterge", style="bold white")
        t_macro.add_column("Deger", justify="right", style="cyan")
        t_macro.add_column("Gunluk Degisim", justify="right", style="bold")
        for r in macro_records:
            pct_val = r["Degisim"]
            color = "green" if "+" in pct_val else ("red" if "-" in pct_val else "white")
            t_macro.add_row(r["Gosterge"], r["Deger"], f"[{color}]{pct_val}[/]")
        console.print(t_macro)

    # Profesyonel Dinamikler Tablosu
    t_prof = Table(title="Wall Street Profesyonel Dinamikleri", show_header=True, header_style="bold magenta", padding=(0, 2))
    t_prof.add_column("Metrik", style="bold white")
    t_prof.add_column("Analiz / Durum", style="white")
    
    t_prof.add_row("VIX Egrisi (Korku Yapisi)", vix_curve_text)
    t_prof.add_row("Volatilite Skew (Cokus Sigortasi)", SPX_SKEW_TEXT)
    t_prof.add_row("S&P 500 Put/Call Hacim Orani (PCR)", SPX_PCR_TEXT)
    t_prof.add_row("Filin Ayak Izi (Gunun Balina Islemi)", SPX_WHALE_TEXT)
    t_prof.add_row("Cop Tahvil Stresi (HYG/TLT Orani)", junk_stress_text)
    t_prof.add_row("Kripto Oncu Sinyali (BTC Momentum)", btc_text)
    t_prof.add_row("Doktor Bakir / Altin Orani (Resesyon Radari)", cu_au_text)
    t_prof.add_row("COMEX Fiziksel Kasa Durumu (Manuel Baglanti)", comex_text)
    t_prof.add_row("Piyasa Genisligi (Dow 30 > 50MA)", breadth_text)
    t_prof.add_row("Sektor Liderleri (Gunluk)", top_1d)
    t_prof.add_row("Sektor Zayiflari (Gunluk)", bot_1d)
    t_prof.add_row("Sektor Liderleri (Haftalik)", top_1w)
    t_prof.add_row("Sektor Zayiflari (Haftalik)", bot_1w)
    t_prof.add_row("Sektor Liderleri (Aylik)", top_1m)
    t_prof.add_row("Sektor Zayiflari (Aylik)", bot_1m)
    t_prof.add_row("Bugunku Kritik ABD Haberleri", calendar_text)
    
    console.print(t_prof)
    console.print("")

    # GEX Tablosu
    if results:
        table = Table(title="Sabah Piyasa Yapici Duvarlari & GEX Raporu", show_header=True, header_style="bold blue")
        table.add_column("Varlik", style="bold white")
        table.add_column("Spot", justify="right", style="cyan")
        table.add_column("Vade", justify="center", style="dim")
        table.add_column("Put Wall", justify="right", style="green")
        table.add_column("Gamma Flip", justify="right", style="yellow")
        table.add_column("Call Wall", justify="right", style="red")
        table.add_column("Net GEX", justify="right", style="bold")

        for r in results:
            table.add_row(r["Varlik"], r["Spot"], r["Vade"], r["Put Wall (Destek)"], r["Gamma Flip"], r["Call Wall (Direnc)"], r["Net GEX ($M/1%)"])
        console.print(table)
    else:
        console.print("[red]Hicbir varlik icin veri hesaplanamadi.[/]")

if __name__ == "__main__":
    main()
