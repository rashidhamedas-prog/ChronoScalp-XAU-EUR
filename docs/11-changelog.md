# تاریخچه تغییرات

تاریخچه‌ی کامل فازها در `docs/ROADMAP.md` است. اینجا فقط تغییرات قابل‌توجه
از زمان نصب AI-DOS ثبت می‌شود.

## Unreleased

### اضافه شد

- سبک معاملات دستی اپراتور به‌صورت استراتژی مستقل `operator_style`
  (نه فیلتر روی دلتا). طلا: فید اسپایک (استوک **و** RSI) / رول‌اوور /
  پولبک HTF داخل سشن ۱۳:۰۰–۱۸:۳۰ تهران. یورو: فید استوک‌محور. هندسه
  ۱٫۵R روی همین موتور؛ دلتای طلا دوباره ۱٫۸R. حجم ۶–۲۵ لات و گرید کپی نشد.

### اصلاح شد

- کاتالوگ زنده طلا/یورو: دلتا + استرادل خبر. اسکلپ M1 از کتاب زنده حذف شد
  بعد از هفتهٔ دمو ۲۷ اوت تا ۳ سپتامبر ۲۰۲۶ (۴۶ تیکت، −۶۹۴۷ دلار MT5).
- تقویم YAML برای NFP ۴ سپتامبر ۲۰۲۶ ۱۲:۳۰ UTC؛ Finnhub 403 دیگر تقویم
  دستی را خالی نمی‌کند.
- پنجرهٔ لندن تا ۱۳:۰۰ محلی تا ساعت ۱۳ ایران در شکاف لندن/نیویورک نیفتد.

### اضافه شد

- لاگ «Entry gate profile» و «Entry guards» موقع استارت حلقه‌ی زنده: استراتژی‌های
  فعال، نمادها، `max_concurrent`، حالت سشن، درصد ریسک، حداقل R:R و وضعیت هر
  گارد ورود (`src/chronoscalp/main.py`).
- WARNING صریح وقتی هیچ استراتژی ورودی فعال نیست.
- `chronoscalp.config_overrides.UNENFORCED_OVERRIDE_KEYS` و
  `unenforced_override_keys()`: یازده کلید overlay که اعتبارسنجی می‌شوند ولی
  هیچ کدی اعمالشان نمی‌کند، حالا موقع استارت با WARNING فهرست می‌شوند.
- `chronoscalp.backtest.engine.LIVE_ONLY_GATES` و فیلد
  `live_only_gates_not_modelled` در خروجی هر بک‌تست، به‌همراه هشدار پایان اجرا.
- تست‌های رگرسیون برای چرن اتصال MT5
  (`tests/test_mt5_connect_idempotent.py`).
- `scripts/analyze_spread_guard.py`: گزارش قیف ورود از روی لاگ‌های روزانه —
  سهم هر دلیل رد شدن به‌ازای هر نماد، و توزیع اسپرد مشاهده‌شده هنگام رد شدن
  در برابر سقف گارد. فقط گزارش می‌دهد و هیچ تنظیمی را تغییر نمی‌دهد.
- زیرساخت AI-DOS: `.ai-dos/`، `ai-dos.yaml`، `prompts/`، `tasks/`،
  `validate_ai_dos.py` و قواعد `.cursor/rules/0*-*.mdc`.

### اصلاح شد

- `MT5Connector.connect()` حالا idempotent است. هر تلاش اتصال اول
  `mt5.shutdown()` می‌زد، پس فراخوان‌های تکراری از سمت آداپتر بروکر و
  پروب‌های وضعیت پنل/تلگرام لینک IPC را وسط کار بازمی‌ساختند. برای بازسازی
  عمدی `force=True` اضافه شد.
- نگهبان idempotent از instance-scoped به process-scoped تغییر کرد
  (`_process_link_matches`). لاگ VPS بعد از دیپلوی نشان داد نگهبان اول بی‌اثر
  است: پنل و تلگرام به‌ازای هر درخواست یک `MT5Connector` یک‌بارمصرف می‌سازند و
  `self._connected` برایشان همیشه `False` است. حالا وضعیت از خود پکیج
  `MetaTrader5` خوانده می‌شود و فقط وقتی لاگین لینک موجود با لاگین درخواستی
  یکی باشد از هندشیک دوباره صرف‌نظر می‌شود.
- `risk.daily_loss_limit_enabled` روی VPS از `false` به `true` برگشت. روی یک
  ربات در حالت `--mode live` با بروکر `mt5` این یک کنترل ریسک خاموش بود.

### برگردانده شد

- `.env.example` که نصب‌کننده‌ی AI-DOS با یک قالب عمومی وب جایگزین کرده بود.
  همه‌ی متغیرهای ChronoScalp (MT5، `CHRONOSCALP_CONFIRM_LIVE`، توکن API،
  OANDA، لایسنس، تقویم خبری) دوباره مستند شدند.
- محدودیت‌های سخت ChronoScalp در `AGENTS.md` که هنگام نصب AI-DOS حذف شده
  بودند: سقف ۱٪ ریسک، حداقل R:R ۱.۵، گیت `CHRONOSCALP_CONFIRM_LIVE`، مرز
  SDK بروکر، ویندوزی‌بودن `MetaTrader5`، الزام تست، و ممنوعیت کامیت سکرت.

### مستندسازی

- `docs/09-known-issues.md` با پنج مورد دارای شواهد پر شد. BUG-005 دلیل کمی
  «تعداد معاملات کم» را با heartbeat سرور ثبت می‌کند.
- `config/runtime_overrides.demo_shadow.example.yaml`: کلیدهای بی‌اثر با
  `# INERT` علامت خوردند و هشدار انحراف overlay اضافه شد.

### دیپلوی

- VPS ویندوزی `45.90.98.99` (پورت SSH ۲۲، نه ۲۲۹۹؛ کاربر `Administrator`) از
  `ca045c9` به `9609c1f` آمد و ربات سه بار با کتاب پوزیشن خالی ری‌استارت شد.
  هر overlay قبل از تغییر بکاپ گرفته شد
  (`runtime_overrides.pre-deploy.bak.yaml` و
  `runtime_overrides.pre-symbols.bak.yaml`).
- overlay سرور با تأیید مالک پروژه: `symbols` به `[XAUUSD, EURUSD]`،
  `strategy.delta.allowed_symbols` به `[XAUUSD, EURUSD]`، و حذف `ultra_scalp`
  از `enabled_strategies` به‌همراه `use_ultra_scalp: false` و حذف بلوک
  تنظیمات آن. تأیید در لاگ استارت:
  `strategies=[liquidity_volume,news_straddle,delta] symbols=[XAUUSD,EURUSD]`.

### هنوز باز

- BUG-006: تصمیم درباره‌ی گارد اسپرد طلا (۲۴٪ از ردها) و `three_strikes`
  (۱۸٪ از ردها، با توقف ۱۲ ساعته). هر دو کنترل ریسک عمدی‌اند و تغییرشان
  تصمیم مالک پروژه است.
- برای تصمیم دقیق درباره‌ی ضریب گارد اسپرد، نمونه‌برداری از *همه‌ی* اسپردها
  لازم است؛ لاگ فعلی فقط ردها را ثبت می‌کند.
- تصمیم درباره‌ی یازده کلید بی‌اثر: پیاده‌سازی یا حذف از schema.
- `risk.max_concurrent_positions: 8` با `independent_symbol_entries: true` و
  گارد همبستگی خاموش، در حالی که فقط دو نماد فعال است — ارزش بازبینی دارد.
- سایر قالب‌های `docs/0*.md` هنوز TODO هستند و باید توسط مالک پروژه پر شوند.
