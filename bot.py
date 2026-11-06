import yfinance as yf
import pandas as pd
import numpy as np
import requests
from datetime import datetime

# ==================== AYARLAR ====================
# Lütfen Token'ını BotFather'dan yenilediysen buraya onu yaz!
TELEGRAM_TOKEN = "8976321317:AAE22e1cwXaE67qkgYhaSWec8_RcodGLC6Q"
TELEGRAM_CHAT_ID = "9083515870"

SEMBOLLER = ["SKTAS.IS", "THYAO.IS", "ASELS.IS", "MRGYO.IS"] 

# GÜN İÇİ (30 DAKİKALIK) PARAMETRELERİ
FAST_LEN = 5   
SLOW_LEN = 13  
TREND_LEN = 50 
RSI_LEN = 14
RSI_ALT = 30   
RSI_UST = 75   # 75'e gevşetildi
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIG = 9
VOL_LEN = 20
VOL_MULT = 0.8 # 0.8'e gevşetildi (Hacim ortalamanın %80'i ise yeter)
ATR_LEN = 14
ATR_MULT_SL = 1.5
RR_ORAN = 1.5  

# VERİ ÇEKME AYARLARI (30 DAKİKA)
INTERVAL = "30m"
PERIOD = "1mo" # 30 dakikalık veriler için son 1 ay yeterli

# ==================== TELEGRAM BİLDİRİM FONKSİYONU ====================
def telegram_mesaj_gonder(mesaj):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mesaj, "parse_mode": "HTML"}
    try:
        response = requests.post(url, data=payload)
        if response.status_code == 200:
            print("✅ Telegram mesajı başarıyla gönderildi.")
        else:
            print(f"❌ Telegram API Hatası: {response.text}")
    except Exception as e:
        print(f"❌ Telegram bağlantı hatası: {e}")

# ==================== İNDİKATÖR FONKSİYONLARI (GEMINI İYİLEŞTİRMELERİ) ====================
def hesapla_ema(series, length):
    return series.ewm(span=length, adjust=False).mean()

def hesapla_rsi(series, length=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    # Wilder's Smoothing (Profesyonel RSI Hesaplaması)
    avg_gain = gain.ewm(com=length - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=length - 1, adjust=False).mean()
    rs = avg_gain / (avg_loss + 1e-10) # Sıfıra bölünme koruması
    return 100 - (100 / (1 + rs))

def hesapla_macd(series, fast=12, slow=26, signal=9):
    ema_fast = hesapla_ema(series, fast)
    ema_slow = hesapla_ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = hesapla_ema(macd_line, signal)
    return macd_line, signal_line

def hesapla_atr(df, length=14):
    # Gelişmiş ATR Hesaplaması (True Range)
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift(1))
    low_close = np.abs(df['Low'] - df['Close'].shift(1))
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(window=length).mean()

# ==================== ANA STRATEJİ FONKSİYONU ====================
def strateji_kontrol(sembol):
    print(f"🔍 {sembol} kontrol ediliyor...")
    
    try:
        df = yf.download(sembol, period=PERIOD, interval=INTERVAL, progress=False)
        if df.empty or len(df) < TREND_LEN:
            print(f"⚠️ {sembol} için yeterli veri bulunamadı.")
            return
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
    except Exception as e:
        print(f"❌ {sembol} veri çekme hatası: {e}")
        return

    # İndikatörleri Hesapla
    df['EMA_FAST'] = hesapla_ema(df['Close'], FAST_LEN)
    df['EMA_SLOW'] = hesapla_ema(df['Close'], SLOW_LEN)
    df['EMA_TREND'] = hesapla_ema(df['Close'], TREND_LEN)
    df['RSI'] = hesapla_rsi(df['Close'], RSI_LEN)
    df['MACD'], df['MACD_SIG'] = hesapla_macd(df['Close'], MACD_FAST, MACD_SLOW, MACD_SIG)
    df['VOL_SMA'] = df['Volume'].rolling(window=VOL_LEN).mean()
    df['ATR'] = hesapla_atr(df, ATR_LEN)

    # Son iki mumu al
    son_mum = df.iloc[-1]
    onceki_mum = df.iloc[-2]

    # Koşullar
    trend_yukari = son_mum['Close'] > son_mum['EMA_TREND']
    macd_onay = son_mum['MACD'] > son_mum['MACD_SIG']
    hacim_onay = son_mum['Volume'] > (son_mum['VOL_SMA'] * VOL_MULT)
    rsi_onay = (son_mum['RSI'] > RSI_ALT) and (son_mum['RSI'] < RSI_UST)
    ema_kesisim = (onceki_mum['EMA_FAST'] <= onceki_mum['EMA_SLOW']) and (son_mum['EMA_FAST'] > son_mum['EMA_SLOW'])

    # Nihai Sinyal
    al_sinyali = trend_yukari and macd_onay and hacim_onay and rsi_onay and ema_kesisim

    if al_sinyali:
        fiyat = round(son_mum['Close'], 2)
        atr = son_mum['ATR']
        sl = round(fiyat - (atr * ATR_MULT_SL), 2)
        tp = round(fiyat + ((fiyat - sl) * RR_ORAN), 2)
        
        mesaj = (
            f"⚡ <b>{sembol} 30 DK AL SİNYALİ!</b>\n"
            f"💰 Giriş Fiyatı: {fiyat}\n"
            f"🛑 Stop-Loss: {sl}\n"
            f"🎯 Kâr Al (TP): {tp}\n"
            f"📊 RSI: {round(son_mum['RSI'], 2)}\n"
            f"⏰ Saat: {datetime.now().strftime('%H:%M')}"
        )
        telegram_mesaj_gonder(mesaj)
    else:
        print(f"ℹ️ {sembol} için sinyal yok. (Trend: {trend_yukari}, MACD: {macd_onay}, Hacim: {hacim_onay}, RSI: {rsi_onay}, Kesişim: {ema_kesisim})")

# ==================== ÇALIŞTIR ====================
if __name__ == "__main__":
    print(f"📅 30 Dakikalık Tarama Başladı: {datetime.now().strftime('%d-%m-%Y %H:%M')}")
    for sembol in SEMBOLLER:
        strateji_kontrol(sembol)
        print("-" * 40)
    print("✅ Tarama Tamamlandı.")
