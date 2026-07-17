# راه‌اندازی ربات تلگرام ChronoScalp

هشدارهای معامله (باز/بسته شدن) و دستورات کنترل (`/status` `/pnl` `/stop`) از طریق تلگرام کار می‌کنند.

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

یا بعد از استارت کنترل‌بات، دستور `/whoami` را بزنید.

## ۳) روشن کردن روی VPS

```bash
cd ~/ChronoScalp-XAU-EUR/docker
docker compose --profile telegram up -d chronoscalp-telegram
docker compose logs -f chronoscalp-telegram
```

دستورهای بات:
- `/status` وضعیت + kill switch
- `/pnl` آمار سود/زیان
- `/open` پوزیشن‌های باز
- `/stop` توقف ورود جدید
- `/resume` برداشتن توقف
