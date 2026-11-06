from flask import Flask
import subprocess

app = Flask(__name__)

@app.route('/')
def home():
    return "Borsa Alarm Botu Calisiyor!"

@app.route('/run')
def run_bot():
    try:
        # bot.py dosyasını arka planda çalıştır ve çıktısını al
        result = subprocess.run(["python", "bot.py"], capture_output=True, text=True, timeout=300)
        return f"<h3>Tarama Tamamlandi!</h3><pre>{result.stdout}</pre><p>Hatalar:</p><pre>{result.stderr}</pre>"
    except Exception as e:
        return f"Hata olustu: {str(e)}"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
