# راه‌اندازی ربات تلگرام ChronoScalp

هشدارهای معامله + **کنترل کامل** + **تنظیمات اتصال و کنترل** از تلگرام:
استارت/توقف، وضعیت، P&L، kill switch، لاگ، بروکر MT5/OANDA، mode، Live confirm، نمادها، استراتژی، ریسک.

## ۱) ساخت بات در Telegram

1. [@BotFather](https://t.me/BotFather) → `/newbot`
2. توکن را در `.env` بگذارید: `TELEGRAM_BOT_TOKEN=...`
3. `/whoami` بزنید و `TELEGRAM_CHAT_ID` را ست کنید

## ۲) روشن کردن

```bat
python scripts\telegram_control_bot.py
```

VPS: Task `ChronoScalpWatchTelegram` یا همان اسکریپت.

## ۳) منوها

| دکمه | کار |
|---|---|
| وضعیت / سود / پوزیشن | مانیتور |
| استارت Paper / Live / توقف ربات | فرآیند |
| توقف ورود / ادامه ورود | kill switch |
| **تنظیمات** | هاب اتصال + کنترل |
| اتصال | بروکر، mode، تست، تأیید Live |
| کنترل | نمادها، استراتژی، ریسک |

### اتصال (دکمه یا دستور)

| دستور | کار |
|---|---|
| `/conn` | خلاصه اتصال |
| `/provider mt5\|oanda` | انتخاب بروکر |
| `/mode paper\|live` | حالت پروفایل |
| `/set_mt5 LOGIN PASS SERVER [PATH]` | ذخیره MT5 |
| `/set_oanda TOKEN ACCOUNT [practice\|live]` | ذخیره OANDA |
| دکمه «بروکر MT5/OANDA» | ویزارد گام‌به‌گام |
| `/test_conn` | تست اتصال |
| `/live_confirm yes\|no` | گیت Live (عمدی؛ مثل پنل) |

### کنترل

| دستور | کار |
|---|---|
| `/config` | همه تنظیمات |
| `/symbols XAUUSD,EURUSD` | نمادهای فعال |
| `/strategies smc_confluence,liquidity_volume` | استراتژی‌ها |
| `/risk 0.5\|1\|1.5` | ریسک (سقف سخت ۱٪) |

بعد از تغییر نماد/استراتژی/mode معمولاً **ری‌استارت ربات معامله** لازم است.

## ۴) امنیت

- بدون `TELEGRAM_CHAT_ID` هر کسی می‌تواند دستور بزند
- Live بدون تأیید استارت نمی‌شود
- رمزها را در چت گروهی نفرستید؛ فقط چت خصوصی با بات

## ۵) عکس پروفایل

`assets/brand/chronoscalp-bot-avatar.png` → BotFather `/setuserpic`

کیبورد خراب شد؟ `python scripts\restore_telegram_keyboard.py`
