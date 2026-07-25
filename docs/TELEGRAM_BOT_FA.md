# راه‌اندازی ربات تلگرام ChronoScalp

هشدارهای معامله (باز/بسته شدن) و **کنترل کامل برنامه** از تلگرام کار می‌کنند:
استارت/توقف فرآیند، وضعیت، سود/زیان، پوزیشن‌ها، kill switch، لاگ.

## ۱) ساخت بات در Telegram

1. در تلگرام به [@BotFather](https://t.me/BotFather) بروید
2. `/newbot` بزنید و نام + یوزرنیم بدهید (یوزرنیم باید به `bot` ختم شود)
3. **توکن** را کپی کنید (مثل `123456:ABC-DEF...`)

## ۲) گرفتن Chat ID

```bash
# روی سرور، موقتاً فقط توکن را در .env بگذارید، بعد:
cd ~/ChronoScalp-XAU-EUR
# بات را در تلگرام Start کنید، بعد:
curl "https://api.telegram.org/bot<TOKEN>/getUpdates"
```

عدد `chat.id` را در `.env` بگذارید:

```env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

یا بعد از استارت کنترل‌بات، دستور `/whoami` را بزنید و همان عدد را در `.env` بگذارید.

> بدون `TELEGRAM_CHAT_ID` هر کسی که به بات پیام بدهد می‌تواند دستور بزند — برای production حتماً ست کنید.

## ۳) روشن کردن

### ویندوز / لوکال

```bat
.venv\Scripts\python.exe scripts\telegram_control_bot.py
```

یا در کنار پنل، یک ترمینال جدا باز بگذارید. برای اجرای دائمی روی VPS ویندوز می‌توانید از Task Scheduler استفاده کنید.

### Docker

```bash
cd ~/ChronoScalp-XAU-EUR/docker
docker compose --profile telegram up -d chronoscalp-telegram
docker compose logs -f chronoscalp-telegram
```

## ۴) کنترل برنامه از تلگرام

بعد از `/start` یک کیبورد فارسی ظاهر می‌شود. معادل دستورها:

| دکمه / دستور | کار |
|---|---|
| وضعیت `/status` | فرآیند ربات، PID، بروکر، نمادها، kill switch، تأیید Live |
| استارت Paper `/start_paper` | شروع فرآیند معامله در حالت paper |
| استارت Live `/start_live` | شروع live — **فقط** اگر `CHRONOSCALP_CONFIRM_LIVE=yes` |
| توقف ربات `/bot_stop` | توقف فرآیند ربات |
| سود/زیان `/pnl` | آمار ژورنال |
| پوزیشن‌ها `/open` | لیست پوزیشن‌های باز |
| توقف ورود `/halt` (قدیمی: `/stop`) | kill switch — ورود جدید متوقف |
| ادامه ورود `/resume` | برداشتن kill switch |
| لاگ `/logs` | آخرین خطوط لاگ |
| `/whoami` | نمایش chat id |

### نکات امنیتی

- Live بدون تأیید `.env` از تلگرام استارت **نمی‌شود** (عمدی؛ مثل پنل).
- `/stop` دیگر فرآیند را نمی‌کشد — فقط ورود جدید را متوقف می‌کند. برای خاموش کردن فرآیند از **توقف ربات** / `/bot_stop` استفاده کنید.

## ۵) عکس پروفایل بات

فایل آماده: `assets/brand/chronoscalp-bot-avatar.png`

1. در تلگرام [@BotFather](https://t.me/BotFather) را باز کنید
2. `/setuserpic` بزنید
3. بات `Chronoscalp_bot` را انتخاب کنید
4. همان فایل PNG را بفرستید

اگر دکمه‌های فارسی خراب (حروف عجیب) شدند:

```bat
python scripts\restore_telegram_keyboard.py
```

روی VPS هم همین اسکریپت را یک‌بار اجرا کنید تا کیبورد UTF-8 برگردد.
