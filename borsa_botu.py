"""
BIST 15 dakikalık DİP-TEPE (Mean Reversion) AL/SAT sinyali botu
"""
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
import yfinance as yf

# ==================== AYARLAR ====================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

SEMBOLLER = ["SKTAS.IS", "THYAO.IS", "ASELS.IS", "MRGYO.IS"]

# YENİ STRATEJİ PARAMETRELERİ (DİP-TEPE)
RSI_LEN = 14
RSI_ALT = 35   # RSI bu seviyenin altına düşerse AL
RSI_UST = 65   # RSI bu seviyenin üzerine çıkarsa SAT

ATR_LEN = 14
ATR_MULT_SL = 1.5
RR_ORAN = 1.5

INTERVAL = "15m"
PERIOD = "1mo"

TZ = ZoneInfo("Europe/Istanbul")
MUM_SURESI = pd.Timedelta(minutes=15)
LOG_DOSYASI = "signals.csv"
LOG_KOLONLAR = ["bar_zamani", "sembol", "islem_yonu", "giris", "sl", "tp", "rsi", "sonuc"]

_veri_onbellek = {}

# ==================== YARDIMCI FONKSİYONLAR ====================
def simdi():
    return datetime.now(TZ)

def piyasa_acik_mi():
    s = simdi()
    if s.weekday() >= 5:
        return False
    dakika = s.hour * 60 + s.minute
    return 10 * 60 <= dakika <= 18 * 60 + 10

def telegram_mesaj_gonder(mesaj):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ TELEGRAM_TOKEN / TELEGRAM_CHAT_ID tanımlı değil, mesaj gönderilmedi.")
        print(mesaj)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mesaj, "parse_mode": "HTML"}
    try:
        r = requests.post(url, data=payload, timeout=15)
        if r.status_code == 200:
            print("✅ Telegram mesajı gönderildi.")
        else:
            print(f"❌ Telegram API hatası: {r.text}")
    except Exception as e:
        print(f"❌ Telegram bağlantı hatası: {e}")

# ==================== İNDİKATÖRLER ====================
def hesapla_rsi(series, length=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=length - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=length - 1, adjust=False).mean()
    rs = avg_gain / (avg_loss + 1e-10)
    return 100 - (100 / (1 + rs))

def hesapla_atr(df, length=14):
    high_low = df["High"] - df["Low"]
    high_close = np.abs(df["High"] - df["Close"].shift(1))
    low_close = np.abs(df["Low"] - df["Close"].shift(1))
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(window=length).mean()

# ==================== VERİ ====================
def veri_al(sembol):
    if sembol in _veri_onbellek:
        return _veri_onbellek[sembol]

    df = None
    try:
        df = yf.download(sembol, period=PERIOD, interval=INTERVAL,
                         progress=False, auto_adjust=True)
        if df is None or df.empty:
            df = None
        else:
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            if df.index.tz is None:
                df.index = df.index.tz_localize("UTC")
            df.index = df.index.tz_convert(TZ)
            df = df.dropna(subset=["Close"])
            if len(df) > 0 and df.index[-1] + MUM_SURESI > pd.Timestamp.now(tz=TZ):
                df = df.iloc[:-1]
            if len(df) == 0:
                df = None
    except Exception as e:
        print(f"❌ {sembol} veri çekme hatası: {e}")
        df = None

    _veri_onbellek[sembol] = df
    return df

# ==================== LOG ====================
def log_oku():
    if not os.path.exists(LOG_DOSYASI):
        return pd.DataFrame(columns=LOG_KOLONLAR)
    log = pd.read_csv(LOG_DOSYASI, dtype=str)
    for k in LOG_KOLONLAR:
        if k not in log.columns:
            log[k] = ""
    log["sonuc"] = log["sonuc"].fillna("")
    return log[LOG_KOLONLAR]

def zaten_gonderildi(sembol, bar_zamani, islem_yonu):
    log = log_oku()
    return ((log["sembol"] == sembol) & (log["bar_zamani"] == str(bar_zamani)) & (log["islem_yonu"] == islem_yonu)).any()

def log_ekle(bar_zamani, sembol, islem_yonu, giris, sl, tp, rsi):
    log = log_oku()
    yeni = pd.DataFrame([{
        "bar_zamani": str(bar_zamani), "sembol": sembol, "islem_yonu": islem_yonu,
        "giris": giris, "sl": sl, "tp": tp, "rsi": rsi, "sonuc": "",
    }])
    pd.concat([log, yeni], ignore_index=True).to_csv(LOG_DOSYASI, index=False)

# ==================== STRATEJİ ====================
def strateji_kontrol(sembol):
    print(f"🔍 {sembol} kontrol ediliyor...")
    df = veri_al(sembol)
    if df is None or len(df) < 30: # RSI için en az 30 mum gerekli
        print(f"⚠️ {sembol} için yeterli veri yok.")
        return

    df = df.copy()
    df["RSI"] = hesapla_rsi(df["Close"], RSI_LEN)
    df["ATR"] = hesapla_atr(df, ATR_LEN)

    son = df.iloc[-1]
    onceki = df.iloc[-2]
    bar_zamani = df.index[-1]

    if pd.isna(son["ATR"]):
        print(f"⚠️ {sembol} ATR hesaplanamadı.")
        return

    fiyat = round(float(son["Close"]), 2)
    atr = float(son["ATR"])
    rsi = round(float(son["RSI"]), 2)

    # DİP ALIŞ SİNYALİ (RSI 35'in altına düştüğünde)
    if rsi < RSI_ALT and onceki["RSI"] >= RSI_ALT: # RSI yeni aşağı kesti
        if not zaten_gonderildi(sembol, bar_zamani, "AL"):
            sl = round(fiyat - atr * ATR_MULT_SL, 2)
            tp = round(fiyat + (fiyat - sl) * RR_ORAN, 2)
            mesaj = (
                f"🟢 <b>{sembol} DİP ALIŞ SİNYALİ</b>\n"
                f"💰 Giriş: {fiyat}\n"
                f"🛑 Stop-Loss: {sl}\n"
                f"🎯 Kâr Al (TP): {tp}\n"
                f"📊 RSI: {rsi} (Aşırı Satım)\n"
                f"🕒 Mum: {bar_zamani.strftime('%d.%m %H:%M')} (TR)"
            )
            telegram_mesaj_gonder(mesaj)
            log_ekle(bar_zamani, sembol, "AL", fiyat, sl, tp, rsi)
            print(f"✅ {sembol} için AL sinyali üretildi.")
            return

    # TEPE SATIŞ SİNYALİ (RSI 65'in üzerine çıktığında)
    if rsi > RSI_UST and onceki["RSI"] <= RSI_UST: # RSI yeni yukarı kesti
        if not zaten_gonderildi(sembol, bar_zamani, "SAT"):
            sl = round(fiyat + atr * ATR_MULT_SL, 2)
            tp = round(fiyat - (sl - fiyat) * RR_ORAN, 2)
            mesaj = (
                f"🔴 <b>{sembol} TEPE SATIŞ SİNYALİ</b>\n"
                f"💰 Giriş: {fiyat}\n"
                f"🛑 Stop-Loss: {sl}\n"
                f"🎯 Kâr Al (TP): {tp}\n"
                f"📊 RSI: {rsi} (Aşırı Alım)\n"
                f"🕒 Mum: {bar_zamani.strftime('%d.%m %H:%M')} (TR)"
            )
            telegram_mesaj_gonder(mesaj)
            log_ekle(bar_zamani, sembol, "SAT", fiyat, sl, tp, rsi)
            print(f"✅ {sembol} için SAT sinyali üretildi.")
            return

    print(f"ℹ️ {sembol} sinyal yok. (RSI: {rsi})")

# ==================== SONUÇ TAKİBİ ====================
def sonuclari_guncelle():
    log = log_oku()
    if log.empty:
        return

    degisti = False
    for i, satir in log.iterrows():
        if satir["sonuc"] != "":
            continue
        df = veri_al(satir["sembol"])
        if df is None:
            continue
        giris_zamani = pd.Timestamp(satir["bar_zamani"])
        sl, tp = float(satir["sl"]), float(satir["tp"])
        islem_yonu = satir["islem_yonu"]

        for zaman, mum in df[df.index > giris_zamani].iterrows():
            if islem_yonu == "AL":
                sl_oldu = mum["Low"] <= sl
                tp_oldu = mum["High"] >= tp
            else: # SAT
                sl_oldu = mum["High"] >= sl
                tp_oldu = mum["Low"] <= tp

            if sl_oldu or tp_oldu:
                sonuc = "SL" if sl_oldu else "TP"
                log.at[i, "sonuc"] = sonuc
                degisti = True
                emoji = "🛑" if sonuc == "SL" else "🎯"
                telegram_mesaj_gonder(
                    f"{emoji} <b>{satir['sembol']}</b> {islem_yonu} sinyali {sonuc} oldu\n"
                    f"Giriş: {satir['giris']} | SL: {satir['sl']} | TP: {satir['tp']}\n"
                    f"Mum: {zaman.strftime('%d.%m %H:%M')} (TR)"
                )
                break

    if degisti:
        log.to_csv(LOG_DOSYASI, index=False)

def ozet_yazdir():
    log = log_oku()
    if log.empty:
        return
    tp = (log["sonuc"] == "TP").sum()
    sl = (log["sonuc"] == "SL").sum()
    acik = (log["sonuc"] == "").sum()
    print(f"📈 Toplam sinyal: {len(log)} | TP: {tp} | SL: {sl} | Açık: {acik}")

# ==================== ÇALIŞTIR ====================
if __name__ == "__main__":
    zorla = "--zorla" in sys.argv
    print(f"📅 Tarama: {simdi().strftime('%d-%m-%Y %H:%M')} (TR)")

    if not piyasa_acik_mi() and not zorla:
        print("🌙 Piyasa kapalı, tarama atlandı.")
        sys.exit(0)

    sonuclari_guncelle()
    for s in SEMBOLLER:
        strateji_kontrol(s)
        print("-" * 40)
    ozet_yazdir()
    print("✅ Tarama tamamlandı.")
