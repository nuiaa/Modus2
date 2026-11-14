import streamlit as st
import yfinance as yf
import pandas as pd

st.set_page_config(page_title="Wall Street Radar", page_icon="📈", layout="centered")

st.markdown("<h1 style='text-align: center; color: #00FF00;'>Wall Street Profesyonel Radar</h1>", unsafe_allow_html=True)
st.markdown("---")

if st.button("Piyasayı Tara (Verileri Güncelle)", use_container_width=True):
    with st.spinner("Wall Street sunucularına bağlanılıyor..."):
        try:
            # Makro Veriler
            data = yf.download("^TNX ^VIX", period="2d", group_by="ticker", progress=False)
            vix = data["^VIX"]["Close"].dropna().iloc[-1]
            tnx = data["^TNX"]["Close"].dropna().iloc[-1]
            
            st.subheader("📊 Makro Ekonomik Göstergeler")
            col1, col2 = st.columns(2)
            col1.metric("VIX (Korku Endeksi)", f"{vix:.2f}")
            col2.metric("10 Yıllık ABD Tahvili", f"{tnx:.2f}")
            
            st.markdown("---")
            
            # SPX Spot
            spx = yf.Ticker("^SPX")
            spot = spx.history(period="1d")["Close"].iloc[-1]
            
            st.subheader("📈 S&P 500 Durumu")
            st.metric("SPX Spot Fiyat", f"{spot:.2f}")
            
            st.success("✅ Sistem Stabil - Veriler Başarıyla Çekildi.")
            
        except Exception as e:
            st.error(f"Bağlantı Hatası: {e}")

st.markdown("<br><p style='text-align: center; color: gray;'>Bu uygulama arkadaşlarınızla tek bir link (URL) üzerinden paylaşılabilir.</p>", unsafe_allow_html=True)
