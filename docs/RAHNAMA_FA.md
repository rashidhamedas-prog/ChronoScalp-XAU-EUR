# راهنمای کامل فارسی — ChronoScalp

این سند **قدم‌به‌قدم** توضیح می‌دهد از صفر تا اجرای ربات روی **VPS هلند (Linux)** چه کارهایی باید انجام دهید.

> **وضعیت پروژه:** کد و ابزارها آماده‌اند (شامل **پنل لایسنس و اتصال آسان بروکر**).  
> **مرحله باقی‌مانده شما:** خرید VPS هلند و deploy.  
> **فروش به مشتری:** ببینید [docs/FOROOSH_FA.md](FOROOSH_FA.md)

---

## ۰. سریع‌ترین روش استفاده (پیشنهادی)

```powershell
cd مسیر-پروژه
.venv\Scripts\activate
copy .env.example .env
notepad .env   # LICENSE_ADMIN_SECRET را یک رمز قوی بگذارید
streamlit run scripts/app.py
```

یا دوبار کلیک روی `scripts\start.bat`

در مرورگر **http://localhost:8501**:

1. **مدیر لایسنس** → یک کلید Trial/Monthly برای خودتان صادر کنید  
2. **لایسنس** → همان کلید را فعال کنید  
3. **اتصال بروکر** → OANDA را وصل و «تست اتصال» بزنید → ذخیره  
4. **کنترل ربات** → استارت Paper  

جزئیات فروش و IB: **docs/FOROOSH_FA.md**

---

## فهرست

1. [این پروژه چیست؟](#۱-این-پروژه-چیست)
2. [چه چیزهایی لازم دارید](#۲-چه-چیزهایی-لازم-دارید)
3. [نصب روی ویندوز (تست محلی)](#۳-نصب-روی-ویندوز-تست-محلی)
4. [ساخت حساب OANDA](#۴-ساخت-حساب-oanda)
5. [تنظیم فایل `.env`](#۵-تنظیم-فایل-env)
6. [تنظیم `config/settings.yaml`](#۶-تنظیم-configsettingsyaml)
7. [بک‌تست (بدون بروکر)](#۷-بک‌تست-بدون-بروکر)
8. [اجرای Paper روی PC](#۸-اجرای-paper-روی-pc)
9. [داشبورد دو زبانه](#۹-داشبورد-دو-زبانه)
10. [استارت و استاپ با یک کلیک](#۱۰-استارت-و-استاپ-با-یک-کلیک) — الان پنل `app.py` را باز می‌کند
11. [توقف اضطراری (Kill Switch)](#۱۱-توقف-اضطراری-kill-switch)
12. [هشدار تلگرام](#۱۲-هشدار-تلگرام)
13. [**Deploy روی VPS هلند**](#۱۳-deploy-روی-vps-هلند) ← مرحله نهایی شما
14. [از Paper به Live](#۱۴-از-paper-به-live)
15. [عیب‌یابی](#۱۵-عیب‌یابی)
16. [چک‌لیست نهایی](#۱۶-چک‌لیست-نهایی)
17. فروش لایسنس: [FOROOSH_FA.md](FOROOSH_FA.md)

---

## ۱. این پروژه چیست؟

ChronoScalp یک ربات اسکالپ **XAUUSD** و **EURUSD** است که:

- روی تایم‌فریم‌های M1 / M3 / M5 / M10 تحلیل می‌کند
- فقط وقتی M10 و M5 هم‌جهت باشند معامله می‌کند
- فقط در سشن **لندن** و **نیویورک** کار می‌کند
- حداکثر **۱٪ ریسک** در هر معامله و حداقل **R:R 1:1.5** دارد (قابل تغییر نیست — عمدی است)
- روی **VPS لینوکس هلند** با **OANDA** اجرا می‌شود (بدون MT5)

---

## ۲. چه چیزهایی لازم دارید

| مورد | برای چه |
|------|---------|
| PC با ویندوز | تست محلی، بک‌تست، داشبورد |
| حساب OANDA Practice | داده و معامله آزمایشی (رایگان) |
| VPS هلند (Ubuntu) | اجرای ۲۴/۷ — **مرحله آخر** |
| (اختیاری) Bot تلگرام | هشدار باز/بسته شدن معامله |
| (اختیاری) کلید Finnhub | تقویم اخبار اقتصادی |

**مهم:** MetaTrader5 روی Linux کار **نمی‌کند**. برای VPS هلند فقط مسیر **OANDA** را بروید.

---

## ۳. نصب روی ویندوز (تست محلی)

### قدم ۳.۱ — Clone پروژه

```powershell
cd D:\soft\Claud\porje
git clone https://github.com/rashidhamedas-prog/ChronoScalp-XAU-EUR.git
cd ChronoScalp-XAU-EUR
```

اگر همین پوشه را دارید، فقط `git pull` بزنید.

### قدم ۳.۲ — محیط مجازی Python

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### قدم ۳.۳ — فایل محیطی

```powershell
copy .env.example .env
notepad .env
```

فعلاً فقط `OANDA_API_TOKEN` و `OANDA_ACCOUNT_ID` را بعد از ساخت حساب OANDA پر می‌کنید.

### قدم ۳.۴ — تست نصب

```powershell
$env:PYTHONPATH="src"
pytest -q
```

اگر همه تست‌ها سبز بود، نصب درست است.

---

## ۴. ساخت حساب OANDA

### قدم ۴.۱
به [oanda.com](https://www.oanda.com) بروید و حساب **Practice (دمو)** بسازید.

### قدم ۴.۲
در پنل OANDA:
- بخش **Manage API Access** → یک **v20 API Token** بسازید
- **Account ID** را یادداشت کنید (مثل `101-004-1234567-001`)

### قدم ۴.۳
مطمئن شوید این نمادها در حساب شما فعال است:
- `XAU_USD` (طلا)
- `EUR_USD`

---

## ۵. تنظیم فایل `.env`

فایل `.env` را باز کنید و پر کنید:

```env
# --- OANDA (الزامی برای VPS هلند) ---
OANDA_API_TOKEN=توکن-شما
OANDA_ACCOUNT_ID=101-004-xxxxxxx-001

# --- ایمنی: تا قبل از آمادگی live حتماً no بماند ---
CHRONOSCALP_CONFIRM_LIVE=no
CHRONOSCALP_STOP_TRADING=no

# --- تلگرام (پیشنهاد قوی برای VPS) ---
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# --- اخبار (اختیاری — Finnhub رایگان) ---
NEWS_API_KEY=

LOG_LEVEL=INFO
```

> **هرگز** `.env` را در git commit نکنید.

---

## ۶. تنظیم `config/settings.yaml`

### فاز ۱ — تست روی PC (Paper + داده OANDA)

```yaml
execution:
  broker: paper
  data_source: oanda

oanda:
  environment: practice
```

### فاز ۲ — VPS هلند (همان Paper، روی سرور)

همان تنظیم بالا — فقط روی VPS اجرا می‌شود.

### فاز ۳ — Live روی OANDA Practice

```yaml
execution:
  broker: oanda
  data_source: oanda

oanda:
  environment: practice
```

و در `.env`: `CHRONOSCALP_CONFIRM_LIVE=yes`

### هشدار تلگرام (پیشنهادی)

```yaml
alerting:
  enabled: true
```

---

## ۷. بک‌تست (بدون بروکر)

بک‌تست روی هر OS کار می‌کند؛ نیاز به OANDA یا VPS ندارد.

```powershell
.venv\Scripts\activate
$env:PYTHONPATH="src"
python scripts/run_backtest.py --symbol XAUUSD
python scripts/run_backtest.py --symbol EURUSD --report data/reports/eurusd.json
```

اگر داده CSV ندارید، روی ویندوز با MT5 می‌توانید تاریخچه بگیرید:

```powershell
python scripts/fetch_history.py --symbol XAUUSD --years 2
```

**بهینه‌سازی پارامتر (اختیاری):**

```powershell
python scripts/run_optimize.py --symbol XAUUSD --mode walk-forward --folds 3
```

نتایج فقط JSON است — خودکار در settings نوشته **نمی‌شود** (جلوگیری از overfit).

---

## ۸. اجرای Paper روی PC

بعد از پر کردن `.env` با OANDA:

```powershell
.venv\Scripts\activate
$env:PYTHONPATH="src"
python scripts/run_live.py --mode paper
```

- داده **واقعی** از OANDA می‌آید
- معامله **شبیه‌سازی** می‌شود (پول واقعی در خطر نیست)
- توقف: `Ctrl + C`

حداقل **۲ تا ۴ هفته** paper پایدار قبل از live.

---

## ۹. داشبورد دو زبانه

```powershell
streamlit run scripts/dashboard.py
```

مرورگر: **http://localhost:8501**

- دکمه بالای sidebar: تعویض **فارسی ↔ English**
- وضعیت kill switch، پوزیشن‌ها، اسپرد، بک‌تست، لاگ

داده نمونه (اولین بار):

```powershell
python scripts/seed_dashboard_demo.py
```

---

## ۱۰. استارت و استاپ با یک کلیک

### استارت (Paper)

روی `scripts\start.bat` دوبار کلیک کنید — یا:

```powershell
scripts\start.bat paper
```

دو پنجره باز می‌شود:
1. **ChronoScalp Bot** — ربات
2. **ChronoScalp Dashboard** — داشبورد

### استارت Live (فقط بعد از تست کامل)

```powershell
scripts\start.bat live
```

نیاز: `CHRONOSCALP_CONFIRM_LIVE=yes` در `.env`

### استاپ

روی `scripts\stop.bat` دوبار کلیک کنید.

---

## ۱۱. توقف اضطراری (Kill Switch)

بدون بستن برنامه، **ورود معامله جدید** متوقف می‌شود:

**روش ۱ — فایل:**
```powershell
type nul > data\state\STOP_TRADING
```

**روش ۲ — env:**
```env
CHRONOSCALP_STOP_TRADING=yes
```
سپس bot را restart کنید.

برای ادامه معامله: فایل را حذف کنید یا env را `no` کنید.

---

## ۱۲. هشدار تلگرام

### قدم ۱
با [@BotFather](https://t.me/BotFather) یک bot بسازید → Token بگیرید.

### قدم ۲
به bot پیام بدهید، سپس Chat ID را پیدا کنید:
`https://api.telegram.org/bot<TOKEN>/getUpdates`

### قدم ۳
در `.env` و `settings.yaml` (بخش alerting) پر کنید.

هر باز/بسته شدن معامله، قطع اتصال، و daily loss limit به تلگرام می‌رود.

---

## ۱۳. Deploy روی VPS هلند

> **این بخش کار نهایی شماست.** کد آماده است؛ شما سرور می‌گیرید و دستورات زیر را اجرا می‌کنید.

### قدم ۱۳.۱ — خرید VPS

| مشخصه | پیشنهاد |
|--------|---------|
| لوکیشن | **Amsterdam / Netherlands** |
| OS | Ubuntu 22.04 یا 24.04 LTS |
| RAM | حداقل 1 GB |
| CPU | 1 vCPU |

ارائه‌دهندگان معروف: Hetzner، DigitalOcean، Vultr، Contabo (Amsterdam region).

### قدم ۱۳.۲ — اتصال SSH

از PowerShell یا PuTTY:

```bash
ssh root@IP-سرور-شما
```

### قدم ۱۳.۳ — نصب خودکار (اسکریپت پروژه)

```bash
curl -fsSL https://raw.githubusercontent.com/rashidhamedas-prog/ChronoScalp-XAU-EUR/main/scripts/vps-setup.sh -o vps-setup.sh
bash vps-setup.sh
```

یا دستی:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git python3.11 python3.11-venv docker.io docker-compose-plugin

git clone https://github.com/rashidhamedas-prog/ChronoScalp-XAU-EUR.git
cd ChronoScalp-XAU-EUR
cp .env.example .env
nano .env          # OANDA token و account id
nano config/settings.yaml   # broker: paper, data_source: oanda
```

### قدم ۱۳.۴ — فایروال (پیشنهادی)

```bash
sudo ufw allow OpenSSH
sudo ufw allow 8501/tcp    # فقط اگر dashboard را از بیرون می‌خواهید
sudo ufw enable
```

> داشبورد را روی اینترنت عمومی باز نگذارید مگر با رمز یا VPN.

### قدم ۱۳.۵ — اجرا با Docker (توصیه‌شده)

```bash
cd docker
docker compose up chronoscalp-paper-oanda -d
docker compose logs -f chronoscalp-paper-oanda
```

### قدم ۱۳.۶ — بررسی سلامت

```bash
# لاگ زنده
docker compose logs -f chronoscalp-paper-oanda

# state ذخیره‌شده
cat ../data/state/trading_state_paper.json

# kill switch تست
touch ../data/state/STOP_TRADING
docker compose restart chronoscalp-paper-oanda
```

### قدم ۱۳.۷ — اجرای دائمی بعد از reboot

Docker با `restart: unless-stopped` خودش بالا می‌آید. برای اطمینان:

```bash
sudo systemctl enable docker
```

### قدم ۱۳.۸ — به‌روزرسانی نسخه

```bash
cd ~/ChronoScalp-XAU-EUR
git pull
cd docker
docker compose build --no-cache
docker compose up -d chronoscalp-paper-oanda
```

---

## ۱۴. از Paper به Live

| مرحله | broker | environment | CONFIRM_LIVE |
|--------|--------|-------------|--------------|
| تست PC | paper | practice | no |
| VPS paper | paper | practice | no |
| OANDA practice live | oanda | practice | yes |
| پول واقعی | oanda | live | yes |

**قبل از پول واقعی:**
- [ ] ۲–۴ هفته paper بدون خطای جدی
- [ ] تلگرام کار می‌کند
- [ ] kill switch تست شده
- [ ] بک‌تست و walk-forward بررسی شده
- [ ] با سرمایه **کم** شروع کنید

---

## ۱۵. عیب‌یابی

| مشکل | راه‌حل |
|------|--------|
| `Failed to connect to OANDA` | Token و Account ID را در `.env` چک کنید |
| هیچ معامله‌ای باز نمی‌شود | ساعت GMT — شاید خارج از سشن لندن/نیویورک باشید |
| `Refusing --mode live` | `CHRONOSCALP_CONFIRM_LIVE=yes` در `.env` |
| Bot بعد از restart معامله تکراری نمی‌زند | طبیعی است — dedup و state فعال است |
| Dashboard خالی | `python scripts/seed_dashboard_demo.py` یا bot را اجرا کنید |
| Docker بالا نمی‌آید | `docker compose logs` و `.env` را ببینید |

لاگ‌ها: پوشه `logs/` یا `docker compose logs`.

---

## ۱۶. چک‌لیست نهایی

### روی PC (شما)
- [ ] `pip install -r requirements.txt` و `pytest -q` سبز
- [ ] حساب OANDA Practice + Token
- [ ] `.env` پر شده
- [ ] `run_backtest.py` اجرا شده
- [ ] `run_live.py --mode paper` چند روز تست شده
- [ ] داشبورد و `start.bat` / `stop.bat` امتحان شده
- [ ] (اختیاری) تلگرام فعال

### روی VPS هلند (مرحله نهایی — شما)
- [ ] VPS Amsterdam خریداری شده
- [ ] `git clone` + `.env` + `settings.yaml`
- [ ] `docker compose up chronoscalp-paper-oanda -d`
- [ ] لاگ بدون خطای مکرر
- [ ] ۲–۴ هفته paper روی VPS
- [ ] سپس `broker: oanda` + `environment: practice` + live gate

---

## مسیر خلاصه (یک نگاه)

```
[PC] نصب → بک‌تست → paper + داشبورد
         ↓
[OANDA] حساب practice + API token
         ↓
[VPS هلند] docker compose up (paper)
         ↓
۲–۴ هفته مانیتورینگ + تلگرام
         ↓
[اختیاری] live practice → live واقعی با سرمایه کم
```

---

## فایل‌های مفید

| فایل | محتوا |
|------|--------|
| `docs/RAHNAMA_FA.md` | همین راهنما |
| `docs/DEPLOY_NL_VPS.md` | راهنمای فنی انگلیسی VPS |
| `docs/RISK_DISCLAIMER.md` | سلب مسئولیت — حتماً بخوانید |
| `scripts/start.bat` | استارت bot + dashboard |
| `scripts/stop.bat` | استاپ |
| `scripts/vps-setup.sh` | نصب اولیه VPS |

---

*آخرین به‌روزرسانی: هم‌زمان با تکمیل پروژه — مرحله باقی‌مانده: deploy روی VPS توسط شما.*
