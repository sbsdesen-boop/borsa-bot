import yfinance as yf
import pandas as pd
import numpy as np
import requests
from datetime import datetime

# ==================== AYARLAR ====================
# SENİN VERDİĞİN BİLGİLER
TELEGRAM_TOKEN = "8976321317:AAE22e1cwXaE67qkgYhaSWec8_RcodGLC6Q"
TELEGRAM_CHAT_ID = "9083515870"

SEMBOLLER = ["SKTAS.IS", "THYAO.IS", "ASELS.IS", "MRGYO.IS"] 

# GÜN İÇİ (INTRADAY) PARAMETRELERİ
# Daha hızlı tepki verebilmesi için periyotları kısalttık
FAST_LEN = 5   # 9'dan 5'e düşürüldü
SLOW_LEN = 13  # 21'den 13'e düşürüldü
TREND_LEN = 50 # 100'den 50'ye düşürüldü
RSI_LEN = 14
RSI_ALT = 30   # Aşırı satım
RSI_UST = 70   # Aşırı alım
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIG = 9
VOL_LEN = 20
VOL_MULT = 1.2 # Hacim onayı biraz sıkılaştırıldı
ATR_LEN = 14
ATR_MULT_SL = 1.5
RR_ORAN = 1.5  # Gün içi hedef (Take Profit) biraz daha yakın tutuldu

# ==================== TELEGRAM BİLDİRİM FONKSİYONU ====================
def telegram_mesaj_gonder(mesaj):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mesaj, "parse_mode": "HTML"}
    try:
        requests.post(url, data=payload)
        print(f"✅ Telegram mesajı gönderildi.")
    except Exception as e:
        print(f"❌ Telegram hatası: {e}")

# ==================== İNDİKATÖR FONKSİYONLARI ====================
def hesapla_ema(series, length):
    return series.ewm(span=length, adjust=False).mean()

def hesapla_rsi(series, length=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=length).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=length).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def hesapla_macd(series, fast=12, slow=26, signal=9):
    ema_fast = hesapla_ema(series, fast)
    ema_slow = hesapla_ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = hesapla_ema(macd_line, signal)
    return macd_line, signal_line

def hesapla_atr(df, length=14):
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    return true_range.rolling(window=length).mean()

# ==================== ANA STRATEJİ FONKSİYONU ====================
def strateji_kontrol(sembol):
    print(f"🔍 {sembol} kontrol ediliyor...")
    
    # 1. Veriyi Çek (Son 1 aylık SAATLİK veri)
    try:
        # interval="1h" ile saatlik veri çekiyoruz
        df = yf.download(sembol, period="1mo", interval="1h", progress=False)
        if df.empty:
            print(f"⚠️ {sembol} için veri bulunamadı.")
            return
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
    except Exception as e:
        print(f"❌ {sembol} veri çekme hatası: {e}")
        return

    # 2. İndikatörleri Hesapla
    df['EMA_FAST'] = hesapla_ema(df['Close'], FAST_LEN)
    df['EMA_SLOW'] = hesapla_ema(df['Close'], SLOW_LEN)
    df['SMA_TREND'] = df['Close'].rolling(window=TREND_LEN).mean()
    df['RSI'] = hesapla_rsi(df['Close'], RSI_LEN)
    df['MACD'], df['MACD_SIG'] = hesapla_macd(df['Close'], MACD_FAST, MACD_SLOW, MACD_SIG)
    df['VOL_SMA'] = df['Volume'].rolling(window=VOL_LEN).mean()
    df['ATR'] = hesapla_atr(df, ATR_LEN)

    # 3. En Son Kapanan Mumun Verilerini Al
    son_mum = df.iloc[-1]
    onceki_mum = df.iloc[-2]

    # 4. Koşullar
    trend_yukari = son_mum['Close'] > son_mum['SMA_TREND']
    macd_onay = son_mum['MACD'] > son_mum['MACD_SIG']
    hacim_onay = son_mum['Volume'] > (son_mum['VOL_SMA'] * VOL_MULT)
    rsi_onay = son_mum['RSI'] < RSI_UST
    ema_kesisim = (onceki_mum['EMA_FAST'] <= onceki_mum['EMA_SLOW']) and (son_mum['EMA_FAST'] > son_mum['EMA_SLOW'])

    # 5. Nihai Sinyal
    al_sinyali = trend_yukari and macd_onay and hacim_onay and rsi_onay and ema_kesisim

    # 6. Sinyal Varsa Telegram'a Gönder
    if al_sinyali:
        fiyat = round(son_mum['Close'], 2)
        atr = son_mum['ATR']
        sl = round(fiyat - (atr * ATR_MULT_SL), 2)
        tp = round(fiyat + ((fiyat - sl) * RR_ORAN), 2)
        
        mesaj = (
            f"⚡ <b>{sembol} SAATLİK AL SİNYALİ!</b>\n"
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
    print(f"📅 Saatlik Tarama Başladı: {datetime.now().strftime('%d-%m-%Y %H:%M')}")
    for sembol in SEMBOLLER:
        strateji_kontrol(sembol)
        print("-" * 40)
    print("✅ Tarama Tamamlandı.")
