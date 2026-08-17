# تاریخچه تغییرات

تاریخچه‌ی کامل فازها در `docs/ROADMAP.md` است. اینجا فقط تغییرات قابل‌توجه
از زمان نصب AI-DOS ثبت می‌شود.

## Unreleased

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
- زیرساخت AI-DOS: `.ai-dos/`، `ai-dos.yaml`، `prompts/`، `tasks/`،
  `validate_ai_dos.py` و قواعد `.cursor/rules/0*-*.mdc`.

### اصلاح شد

- `MT5Connector.connect()` حالا idempotent است. هر تلاش اتصال اول
  `mt5.shutdown()` می‌زد، پس فراخوان‌های تکراری از سمت آداپتر بروکر و
  پروب‌های وضعیت پنل/تلگرام لینک IPC را وسط کار بازمی‌ساختند. برای بازسازی
  عمدی `force=True` اضافه شد.

### برگردانده شد

- `.env.example` که نصب‌کننده‌ی AI-DOS با یک قالب عمومی وب جایگزین کرده بود.
  همه‌ی متغیرهای ChronoScalp (MT5، `CHRONOSCALP_CONFIRM_LIVE`، توکن API،
  OANDA، لایسنس، تقویم خبری) دوباره مستند شدند.
- محدودیت‌های سخت ChronoScalp در `AGENTS.md` که هنگام نصب AI-DOS حذف شده
  بودند: سقف ۱٪ ریسک، حداقل R:R ۱.۵، گیت `CHRONOSCALP_CONFIRM_LIVE`، مرز
  SDK بروکر، ویندوزی‌بودن `MetaTrader5`، الزام تست، و ممنوعیت کامیت سکرت.

### مستندسازی

- `docs/09-known-issues.md` با چهار مورد دارای شواهد پر شد.
- `config/runtime_overrides.demo_shadow.example.yaml`: کلیدهای بی‌اثر با
  `# INERT` علامت خوردند و هشدار انحراف overlay اضافه شد.

### هنوز باز

- فایل `config/runtime_overrides.yaml` روی VPS همچنان `delta` را غیرفعال
  دارد. سرور از ایستگاه توسعه در دسترس نبود.
- تصمیم درباره‌ی یازده کلید بی‌اثر: پیاده‌سازی یا حذف از schema.
- سایر قالب‌های `docs/0*.md` هنوز TODO هستند و باید توسط مالک پروژه پر شوند.
