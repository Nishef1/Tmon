// Glossary entries behind every number on the site (docs/glossary.md, docs/10-recommendation-engine.md).
// Each number rendered with <Num term="..."> links to /glossary/<term>.

export type Category = "engine" | "result" | "technical" | "board" | "market";

export type Entry = {
  fa: string;
  en: string;
  category: Category;
  definition: string;
  formula?: string;
  why: string;
  limits: string;
  related?: readonly string[];
};

export const CATEGORY_LABEL: Record<Category, string> = {
  engine: "خروجی موتور توصیه",
  result: "ارزیابی و نتایج",
  technical: "اندیکاتورهای تکنیکال",
  board: "تابلوخوانی",
  market: "وضعیت بازار",
};

export const GLOSSARY = {
  p_win: {
    fa: "احتمال موفقیت",
    en: "Calibrated win probability (p_win)",
    category: "engine",
    definition:
      "احتمال اینکه پس از ورود، قیمت پیش از رسیدن به حد ضرر و تا پایان افق معامله به حد سود برسد. خروجی خام مدل با روش ایزوتونیک کالیبره می‌شود تا عدد نهایی با فراوانی واقعیِ گذشته هم‌خوان باشد.",
    formula: "p_win = کالیبراسیون ایزوتونیک (امتیاز مدل LightGBM)",
    why: "هستهٔ تصمیم است: توصیه فقط وقتی منتشر می‌شود که احتمال و سود مورد انتظار هر دو از آستانه‌ها بگذرند.",
    limits:
      "برآوردی آماری از رفتار گذشته است و تضمین نیست. در رژیم‌های جدید بازار ممکن است دقت کمتری داشته باشد؛ نمودار کالیبراسیون را ببینید.",
    related: ["calibration", "brier", "ev", "take_profit", "stop_loss"],
  },
  ev: {
    fa: "سود مورد انتظار",
    en: "Expected value (EV)",
    category: "engine",
    definition:
      "میانگین سود یا زیان هر معامله با فرض تکرار شرایط مشابه، پس از کسر هزینهٔ رفت‌وبرگشت (کارمزد، مالیات و لغزش قیمت).",
    formula: "EV = p × میانگین سود − (1−p) × میانگین زیان − هزینه رفت‌وبرگشت",
    why: "احتمال بالا به‌تنهایی کافی نیست؛ اگر سود بالقوه کوچک‌تر از هزینه‌ها باشد معامله ارزش ندارد.",
    limits:
      "میانگین‌های سود و زیان از نمونه‌های گذشتهٔ همان بازهٔ احتمال برآورد می‌شوند. هزینه‌ها و لغزش قیمت در این نسخه هنوز با داده واقعی تأیید نشده‌اند (docs/OPEN_QUESTIONS.md).",
    related: ["p_win", "round_trip_cost", "take_profit", "stop_loss"],
  },
  round_trip_cost: {
    fa: "هزینه رفت‌وبرگشت",
    en: "Round-trip cost",
    category: "engine",
    definition:
      "مجموع کارمزد خرید و فروش، مالیات فروش و لغزش قیمت برای یک معامله کامل. در محاسبهٔ سود مورد انتظار و بک‌تست کسر می‌شود.",
    why: "معاملات کوتاه‌مدت با هزینهٔ زیاد می‌توانند ظاهراً سودده و در عمل زیان‌ده باشند.",
    limits:
      "مقادیر از جدول قوانین بازار با تاریخ اعتبار خوانده می‌شوند و بخشی از آن‌ها هنوز تأیید نشده است.",
    related: ["ev"],
  },
  entry_price: {
    fa: "قیمت مرجع ورود",
    en: "Reference entry price",
    category: "engine",
    definition:
      "قیمت پایانی روز سیگنال که برای محاسبهٔ حدها مرجع است. ورود در مدل، با قیمت بازگشایی روز معاملاتی بعد فرض می‌شود، بنابراین قیمت واقعی ورود با این عدد تفاوت دارد.",
    why: "سیگنال پس از بسته شدن بازار تولید می‌شود و پیش از آن قابل اجرا نیست.",
    limits:
      "اگر سهم در روز بعد با صف خرید بسته‌شود یا بازگشایی نشود، ورود ممکن نیست. حدها نسبت به قیمت مرجع محاسبه شده‌اند و ممکن است در عمل جابه‌جا شوند.",
    related: ["take_profit", "stop_loss", "horizon"],
  },
  take_profit: {
    fa: "حد سود",
    en: "Take-profit barrier",
    category: "engine",
    definition: "سطح قیمتی بالای قیمت مرجع که رسیدن به آن، معامله را موفق حساب می‌کند.",
    formula: "حد سود = قیمت مرجع + ۲ × ATR۱۴ × √(مقیاس زمانی)",
    why: "فاصلهٔ حدها با نوسان خود سهم تنظیم می‌شود تا برای سهم‌های کم‌نوسان و پرنوسان معنادار باشد.",
    limits: "قیمت‌ها گسسته و دارای دامنهٔ نوسان‌اند؛ رسیدن به یک سطح دقیق تضمین‌شده نیست.",
    related: ["stop_loss", "atr", "triple_barrier"],
  },
  stop_loss: {
    fa: "حد ضرر",
    en: "Stop-loss barrier",
    category: "engine",
    definition: "سطح قیمتی پایین قیمت مرجع که رسیدن به آن، معامله را ناموفق حساب می‌کند.",
    formula: "حد ضرر = قیمت مرجع − ۱ × ATR۱۴ × √(مقیاس زمانی)",
    why: "زیان هر معامله را از پیش محدود و قابل‌اندازه‌گیری می‌کند.",
    limits:
      "در بازار ایران با صف فروش و کف دامنه ممکن است خروج در سطح حد ضرر ممکن نباشد؛ زیان واقعی می‌تواند بیشتر شود.",
    related: ["take_profit", "atr", "triple_barrier"],
  },
  horizon: {
    fa: "افق معامله",
    en: "Trade horizon",
    category: "engine",
    definition:
      "بیشینهٔ تعداد روز معاملاتی که معامله باز می‌ماند. اگر تا آن زمان هیچ‌کدام از حدها لمس نشوند، در قیمت پایانی آخرین روز بسته می‌شود.",
    why: "افق کوتاه، ریسک رویدادهای ناخواسته را کم و مقایسه میان معاملات را ممکن می‌کند.",
    limits:
      "روزهایی که نماد متوقف است در شمارش افق نمی‌آیند و معاملهٔ شامل توقف از آموزش حذف می‌شود.",
    related: ["triple_barrier"],
  },
  position_pct: {
    fa: "سهم پیشنهادی از سرمایه",
    en: "Suggested position size",
    category: "engine",
    definition:
      "بیشینهٔ بخشی از سرمایه که برای این معامله پیشنهاد می‌شود؛ کمینهٔ سه محدودیت: یک‌چهارم کلی، سقف ۱۰٪ و سقف ریسک هر معامله.",
    formula: "min(¼ × Kelly، ۱۰٪، ریسک مجاز ÷ (فاصله حد ضرر))",
    why: "حتی سیگنال خوب را نباید با اندازهٔ نامتناسب اجرا کرد؛ محدودیت‌های نقدشوندگی، همبستگی و سهم صنعت هم اعمال می‌شود.",
    limits: "فرض می‌کند سرمایهٔ مرجع مشخصی دارید. این عدد توصیهٔ شخصی نیست.",
    related: ["ev", "stop_loss"],
  },
  tier: {
    fa: "رده اطمینان",
    en: "Confidence tier",
    category: "engine",
    definition:
      "رده‌بندی سیگنال‌ها بر پایهٔ احتمال و دقت اخیرِ همان بازهٔ احتمال. رده A تنها وقتی منتشر می‌شود که مدل در آزمون خارج از نمونه و پس از هزینه‌ها از baseline بهتر باشد.",
    why: "رده، شدت اعتماد مدل را نشان می‌دهد نه تضمین نتیجه.",
    limits:
      "تا زمانی که شرط‌های اعتبارسنجی برقرار نباشد هیچ سیگنال رده A منتشر نمی‌شود؛ دلیل آن در صفحهٔ توصیه‌ها آمده است.",
    related: ["p_win", "calibration"],
  },
  rank: {
    fa: "رتبه",
    en: "Rank",
    category: "engine",
    definition: "ترتیب سیگنال‌های روز بر پایهٔ سود مورد انتظار، پس از اعمال محدودیت‌های پرتفوی.",
    why: "نشان می‌دهد اگر امکان ورود به همهٔ سیگنال‌ها نیست، کدام‌ها اولویت دارند.",
    limits: "رتبه نتیجه را تضمین نمی‌کند و فقط ترتیب بر پایهٔ برآورد مدل است.",
    related: ["ev"],
  },
  candidates: {
    fa: "نمادهای واجد شرایط",
    en: "Candidates",
    category: "engine",
    definition:
      "تعداد نمادهایی که در آن روز پیش از اعمال محدودیت‌های پرتفوی، آستانهٔ احتمال و سود مورد انتظار را گذراندند.",
    why: "نشان می‌دهد موتور چند فرصت دیده و چرا تعداد توصیه‌ها کم است.",
    limits: "تعداد کم یا صفر وضعیتی عادی است، نه خطا.",
    related: ["p_win", "ev"],
  },
  triple_barrier: {
    fa: "برچسب سه‌مانع",
    en: "Triple-barrier labelling",
    category: "engine",
    definition:
      "روش برچسب‌گذاری معاملات: کدام یک زودتر رخ می‌دهد؟ حد سود، حد ضرر یا پایان افق. برچسب «موفق» یعنی حد سود نخست لمس شده است.",
    why: "هم با مدیریت ریسک واقعی سازگار است و هم نتیجهٔ هر سیگنال را بدون ابهام تعریف می‌کند.",
    limits: "اگر در یک روز هر دو حد لمس شوند، برای محافظه‌کاری حد ضرر نخست فرض می‌شود.",
    related: ["take_profit", "stop_loss", "horizon"],
  },
  defensive_mode: {
    fa: "حالت دفاعی",
    en: "Defensive mode",
    category: "engine",
    definition:
      "وقتی عرض بازار کم است یا خروج پول حقیقی چند روز پیاپی ادامه دارد، آستانهٔ پذیرش سیگنال بالاتر می‌رود.",
    why: "در بازار ضعیف احتمال شکست سیگنال‌های خریدِ یک‌طرفه بیشتر است.",
    limits: "قاعده‌ای ساده بر پایهٔ دو شاخص بازار است و بازار را پیش‌بینی نمی‌کند.",
    related: ["breadth", "net_flow"],
  },
  shap: {
    fa: "سهم عامل در امتیاز (SHAP)",
    en: "SHAP contribution",
    category: "engine",
    definition:
      "اندازهٔ اثر هر ویژگی بر امتیاز مدل برای همین سیگنال. مقدار مثبت امتیاز را بالا و مقدار منفی پایین برده است. واحد آن لگاریتم شانس است، پیش از کالیبراسیون، و احتمال نیست.",
    why: "نشان می‌دهد چرا مدل این نماد را انتخاب کرده و به شما امکان می‌دهد دلیل را بسنجید.",
    limits: "توضیح امتیاز مدل است، نه رابطهٔ علّی میان ویژگی و قیمت.",
    related: ["p_win"],
  },
  feature_value: {
    fa: "مقدار ویژگی",
    en: "Feature value",
    category: "engine",
    definition: "مقدار یک ویژگی محاسباتی در روز سیگنال که مدل از آن استفاده کرده است.",
    why: "برای آنکه ببینید مدل در آن روز چه شرایطی را دیده است.",
    limits: "مقیاس هر ویژگی متفاوت است؛ مقدار بدون زمینه به‌تنهایی معنای سرمایه‌گذاری ندارد.",
    related: ["shap"],
  },
  brier: {
    fa: "امتیاز بریر",
    en: "Brier score",
    category: "result",
    definition: "میانگین مربع اختلاف احتمال پیش‌بینی‌شده و نتیجهٔ واقعی (۰ یا ۱). هرچه کمتر، بهتر.",
    formula: "Brier = میانگین (p − y)²",
    why: "هم تمایز و هم کالیبراسیون پیش‌بینی را با یک عدد می‌سنجد.",
    limits: "به نرخ پایهٔ موفقیت وابسته است؛ برای مقایسه از مهارت بریر استفاده کنید.",
    related: ["brier_skill", "calibration", "base_rate"],
  },
  brier_skill: {
    fa: "مهارت بریر",
    en: "Brier skill score",
    category: "result",
    definition:
      "مقایسهٔ امتیاز بریر مدل با پیش‌بینی ثابتی که همیشه نرخ پایه را می‌گوید. مثبت یعنی بهتر از حدس ثابت.",
    formula: "مهارت = 1 − Brier مدل ÷ Brier نرخ پایه",
    why: "یکی از شروط انتشار رده A است.",
    limits: "نمونهٔ کوچک آن را ناپایدار می‌کند.",
    related: ["brier", "tier"],
  },
  auc: {
    fa: "سطح زیر منحنی ROC (AUC)",
    en: "ROC AUC",
    category: "result",
    definition:
      "احتمال اینکه مدل به یک نمونهٔ موفق، امتیازی بالاتر از یک نمونهٔ ناموفقِ تصادفی بدهد. ۰٫۵ یعنی حدس تصادفی و ۱ یعنی تفکیک کامل.",
    why: "توان تفکیک مدل را مستقل از آستانه می‌سنجد.",
    limits: "نشان نمی‌دهد احتمال‌ها کالیبره‌اند یا سودآوری پس از هزینه مثبت است.",
    related: ["calibration", "brier"],
  },
  calibration: {
    fa: "کالیبراسیون",
    en: "Calibration",
    category: "result",
    definition:
      "تطابق احتمال پیش‌بینی‌شده با فراوانی واقعی. اگر از میان سیگنال‌هایی با احتمال ۶۰٪ نزدیک ۶۰٪ موفق شوند، مدل کالیبره است.",
    why: "محاسبهٔ سود مورد انتظار و اندازهٔ پوزیشن به درستی احتمال‌ها وابسته است.",
    limits: "در بازه‌هایی با نمونهٔ کم، فراوانی واقعی نوسان زیادی دارد.",
    related: ["hit_rate", "brier", "p_win"],
  },
  hit_rate: {
    fa: "نرخ موفقیت واقعی",
    en: "Observed hit rate",
    category: "result",
    definition: "سهمی از سیگنال‌های یک بازهٔ احتمال که واقعاً به حد سود رسیدند.",
    why: "مقایسهٔ آن با احتمال پیش‌بینی‌شده، کالیبراسیون را نشان می‌دهد.",
    limits: "با نمونهٔ کم قابل اتکا نیست؛ تعداد نمونه را کنار آن ببینید.",
    related: ["calibration", "sample_size"],
  },
  base_rate: {
    fa: "نرخ پایه",
    en: "Base rate",
    category: "result",
    definition: "سهم کل نمونه‌ها (بدون در نظر گرفتن مدل) که به حد سود رسیده‌اند.",
    why: "مبنای مقایسه است: مدل باید از همین نرخ ثابت بهتر باشد.",
    limits: "بسته به دوره و بازار تغییر می‌کند.",
    related: ["brier_skill"],
  },
  sample_size: {
    fa: "تعداد نمونه",
    en: "Sample size (n)",
    category: "result",
    definition: "تعداد مشاهده‌هایی که یک آمار روی آن‌ها محاسبه شده است.",
    why: "آمار بر پایهٔ نمونهٔ کم قابل اتکا نیست.",
    limits: "نمونه‌های همپوشان (سیگنال‌های هم‌زمان در یک بازار) مستقل از هم نیستند.",
    related: ["hit_rate"],
  },
  realized_return: {
    fa: "بازده تحقق‌یافته (ناخالص)",
    en: "Realised return (gross)",
    category: "result",
    definition:
      "بازده معاملهٔ گذشته تا لحظهٔ لمس حد سود، حد ضرر یا پایان افق، پیش از کسر هزینه‌ها.",
    why: "نتیجهٔ سیگنال‌های منتشرشده را شفاف و بدون دست‌کاری نشان می‌دهد.",
    limits: "گذشته است و آینده را تضمین نمی‌کند. چون پیش از هزینه است، بازده خالص کمتر خواهد بود.",
    related: ["triple_barrier", "round_trip_cost"],
  },
  signals_count: {
    fa: "تعداد سیگنال‌ها",
    en: "Signal count",
    category: "result",
    definition: "شمار سیگنال‌های منتشرشده در بازهٔ نمایش‌داده‌شده، شامل سیگنال‌های هنوز باز.",
    why: "برای سنجش اینکه نتایج بر چند نمونه استوارند.",
    limits: "نمونهٔ کم نتیجه‌گیری را مخدوش می‌کند.",
    related: ["sample_size"],
  },
  tp_count: {
    fa: "رسیدن به حد سود",
    en: "Take-profit hits",
    category: "result",
    definition: "تعداد سیگنال‌هایی که حد سودشان پیش از حد ضرر و پایان افق لمس شد.",
    why: "بخشی از نتیجهٔ واقعی سیگنال‌ها.",
    limits: "پیش از هزینه‌ها است.",
    related: ["take_profit", "realized_return"],
  },
  sl_count: {
    fa: "رسیدن به حد ضرر",
    en: "Stop-loss hits",
    category: "result",
    definition: "تعداد سیگنال‌هایی که به حد ضرر رسیدند (شامل رسیدن هم‌زمان در یک روز).",
    why: "بخشی از نتیجهٔ واقعی سیگنال‌ها.",
    limits: "زیان واقعی در صف فروش ممکن است از حد ضرر بیشتر باشد.",
    related: ["stop_loss"],
  },
  expiry_count: {
    fa: "پایان افق بدون لمس حد",
    en: "Expired at horizon",
    category: "result",
    definition:
      "تعداد سیگنال‌هایی که تا پایان افق به هیچ‌کدام از حدها نرسیدند و در قیمت پایانی بسته شدند.",
    why: "کامل‌کنندهٔ نتیجهٔ سیگنال‌ها.",
    limits: "پیش از هزینه‌ها است.",
    related: ["horizon"],
  },
  pending_count: {
    fa: "سیگنال‌های باز",
    en: "Open signals",
    category: "result",
    definition: "سیگنال‌هایی که افقشان هنوز تمام نشده و نتیجه‌شان معلوم نیست.",
    why: "از آمار نتیجه کنار گذاشته می‌شوند تا آمار را خوش‌بینانه نکنند.",
    limits: "—",
    related: ["horizon"],
  },
  trained_rows: {
    fa: "تعداد نمونه آموزش",
    en: "Training rows",
    category: "result",
    definition: "تعداد ردیف‌های نماد-روز که مدل روی آن‌ها آموزش دیده است.",
    why: "پایهٔ آماری مدل را نشان می‌دهد.",
    limits: "ردیف‌های همپوشان مستقل نیستند.",
    related: ["sample_size"],
  },
  rsi: {
    fa: "شاخص قدرت نسبی (RSI)",
    en: "Relative Strength Index",
    category: "technical",
    definition: "نوسان‌نمایی بین ۰ تا ۱۰۰ که قدرت رشدهای اخیر را نسبت به افت‌ها می‌سنجد.",
    formula: "RSI = ۱۰۰ − ۱۰۰ ÷ (۱ + میانگین رشد ÷ میانگین افت) روی ۱۴ روز",
    why: "اشباع خرید (بالای ۷۰) یا اشباع فروش (زیر ۳۰) را نشان می‌دهد.",
    limits:
      "در روندهای قوی مدت طولانی در ناحیهٔ اشباع می‌ماند؛ در بازارِ دارای صف خرید گمراه‌کننده است.",
    related: ["macd"],
  },
  macd: {
    fa: "هیستوگرام مکدی (MACD)",
    en: "MACD histogram",
    category: "technical",
    definition: "اختلاف خط مکدی و خط سیگنال آن، به‌صورت درصدی از قیمت.",
    why: "تغییر شتاب روند را پیش از تغییر قیمت نشان می‌دهد.",
    limits: "شاخص تأخیری است و در بازار بدون روند سیگنال کاذب زیاد می‌دهد.",
    related: ["rsi", "adx"],
  },
  adx: {
    fa: "شاخص جهت‌دار (ADX)",
    en: "Average Directional Index",
    category: "technical",
    definition: "قدرت روند را بدون توجه به جهت آن می‌سنجد؛ بالای ۲۵ معمولاً روند قوی است.",
    why: "کمک می‌کند بدانید روندیابی در شرایط فعلی معنا دارد یا نه.",
    limits: "جهت روند را نمی‌گوید و با تأخیر واکنش نشان می‌دهد.",
    related: ["macd"],
  },
  atr: {
    fa: "دامنه واقعی میانگین (ATR)",
    en: "Average True Range",
    category: "technical",
    definition:
      "میانگین دامنهٔ حرکت روزانهٔ قیمت (با لحاظ شکاف) روی ۱۴ روز؛ در این‌جا گاه به‌صورت درصدی از قیمت.",
    why: "مقیاس نوسان سهم است و فاصلهٔ حد سود و حد ضرر بر پایهٔ آن تنظیم می‌شود.",
    limits: "بر پایهٔ گذشته است و جهش نوسان ناگهانی را پیش‌بینی نمی‌کند.",
    related: ["take_profit", "stop_loss"],
  },
  bollinger: {
    fa: "جایگاه در باند بولینگر (%B)",
    en: "Bollinger %B",
    category: "technical",
    definition:
      "موقعیت قیمت میان باند پایین (۰) و باند بالا (۱). مقادیر بیرون از بازه یعنی قیمت از باند خارج شده است.",
    why: "نشان می‌دهد قیمت نسبت به نوسان اخیر خود کجاست.",
    limits: "وابسته به تنظیمات باند است و به‌تنهایی سیگنال خرید یا فروش نیست.",
    related: ["rsi", "atr"],
  },
  vwap: {
    fa: "فاصله از قیمت میانگین موزون (VWAP)",
    en: "Gap to VWAP",
    category: "technical",
    definition: "فاصلهٔ نسبی قیمت پایانی از میانگین قیمت وزن‌دهی‌شده با حجم.",
    why: "نشان می‌دهد معامله‌گران عمدهٔ حجم به چه قیمتی وارد شده‌اند.",
    limits: "در روزهای کم‌حجم یا همراه با صف، معنای ضعیف‌تری دارد.",
    related: ["rel_volume"],
  },
  return_n: {
    fa: "بازده چندروزه",
    en: "N-day return",
    category: "technical",
    definition: "درصد تغییر قیمت تعدیل‌شده در یک بازهٔ گذشته.",
    why: "شتاب و برگشت قیمت را می‌سنجد.",
    limits: "به قیمت تعدیل‌شده وابسته است؛ بازهٔ رویدادهای سرمایه‌ای باید درست اعمال شده باشد.",
    related: ["adjusted_price"],
  },
  moving_average: {
    fa: "فاصله از میانگین متحرک",
    en: "Distance to moving average",
    category: "technical",
    definition: "فاصلهٔ نسبی قیمت از میانگین متحرک ساده (SMA) یا نمایی (EMA) در بازهٔ مشخص.",
    why: "نشان می‌دهد قیمت نسبت به روند میان‌مدت خود چقدر کشیده شده است.",
    limits: "شاخصی تأخیری است.",
    related: ["rsi"],
  },
  adjusted_price: {
    fa: "قیمت تعدیل‌شده",
    en: "Adjusted price",
    category: "technical",
    definition:
      "قیمت‌ها پس از اصلاح برای سود نقدی و افزایش سرمایه تا جهش‌های ساختگی در نمودار نیامد.",
    why: "همهٔ اندیکاتورها و نمودارها روی قیمت تعدیل‌شده‌اند.",
    limits: "شناسایی رویدادها از اختلاف قیمت پایانی دیروز با قیمت مرجع روز است و کامل نیست.",
    related: ["return_n"],
  },
  buy_power: {
    fa: "قدرت خریدار حقیقی",
    en: "Individual buy power",
    category: "board",
    definition:
      "نسبت سرانهٔ خرید به سرانهٔ فروش حقیقی‌ها. مقدار بالای ۱ یعنی هر خریدار حقیقی به‌طور متوسط بیشتر از هر فروشنده خریده است.",
    formula: "قدرت خریدار = سرانه خرید ÷ سرانه فروش",
    why: "رفتار خرد را از تابلو نشان می‌دهد.",
    limits: "با معاملات کم‌حجم یا کدهای عمده تحریف می‌شود.",
    related: ["net_flow", "smart_money"],
  },
  net_flow: {
    fa: "نسبت ورود پول حقیقی",
    en: "Net individual money flow ratio",
    category: "board",
    definition: "خالص ارزش خرید منهای فروش حقیقی‌ها به‌صورت نسبتی از ارزش کل معاملات.",
    why: "نشان می‌دهد پول خرد وارد سهم می‌شود یا خارج.",
    limits: "ورود پول حقیقی لزوماً به معنای رشد قیمت نیست.",
    related: ["buy_power", "smart_money"],
  },
  rel_volume: {
    fa: "حجم نسبی",
    en: "Relative volume",
    category: "board",
    definition: "حجم معاملات روز نسبت به میانگین حجم روزهای اخیر.",
    why: "حرکت با حجم بالا معتبرتر از حرکت با حجم کم است.",
    limits: "سهم‌های کم‌حجم نوسان بالایی دارند و عدد ناپایدار است.",
    related: ["vwap"],
  },
  smart_money: {
    fa: "نشانهٔ پول هوشمند",
    en: "Smart-money flag",
    category: "board",
    definition:
      "برچسب ۰ یا ۱: ترکیبی از قدرت خریدار و ورود پول حقیقی که طبق قاعدهٔ مشخصی نشانگر خرید هماهنگ است.",
    why: "علامتی سریع از هم‌جهت بودن چند شاخص تابلو.",
    limits: "یک قاعدهٔ ساده است و نام آن به معنای اطلاع محرمانه نیست.",
    related: ["buy_power", "net_flow"],
  },
  market_return: {
    fa: "بازده هم‌وزن بازار",
    en: "Equal-weight market return",
    category: "market",
    definition: "میانگین ساده بازده روزانهٔ نمادهای فعال در همان روز.",
    why: "برای جدا کردن حرکت سهم از حرکت کل بازار.",
    limits: "نمادهای کم‌نقدشونده نیز در آن شرکت دارند.",
    related: ["breadth"],
  },
  breadth: {
    fa: "عرض بازار",
    en: "Market breadth",
    category: "market",
    definition: "سهمی از نمادهای فعال که در همان روز مثبت بسته‌اند.",
    why: "پایین‌تر از ۳۵٪ یکی از شروط حالت دفاعی است.",
    limits: "اندازهٔ نمادها را در نظر نمی‌گیرد.",
    related: ["defensive_mode", "market_return"],
  },
} as const satisfies Record<string, Entry>;

export type GlossaryKey = keyof typeof GLOSSARY;

export function glossaryEntry(key: string): (Entry & { key: GlossaryKey }) | undefined {
  return key in GLOSSARY
    ? { key: key as GlossaryKey, ...(GLOSSARY[key as GlossaryKey] as Entry) }
    : undefined;
}

export const GLOSSARY_KEYS = Object.keys(GLOSSARY) as GlossaryKey[];

export type FeatureInfo = { label: string; term: GlossaryKey };

const FEATURES: Record<string, FeatureInfo> = {
  rsi_14: { label: "RSI (۱۴ روزه)", term: "rsi" },
  macd_hist_pct: { label: "هیستوگرام مکدی", term: "macd" },
  adx_14: { label: "ADX (۱۴ روزه)", term: "adx" },
  atr_14_pct: { label: "ATR درصدی", term: "atr" },
  bb_pct_b: { label: "جایگاه در باند بولینگر", term: "bollinger" },
  vwap_gap: { label: "فاصله از VWAP", term: "vwap" },
  ind_buy_power: { label: "قدرت خریدار حقیقی", term: "buy_power" },
  ind_net_flow_ratio: { label: "نسبت ورود پول حقیقی", term: "net_flow" },
  rel_volume: { label: "حجم نسبی", term: "rel_volume" },
  smart_money_flag: { label: "نشانهٔ پول هوشمند", term: "smart_money" },
  mkt_ret_ew: { label: "بازده هم‌وزن بازار", term: "market_return" },
  breadth: { label: "عرض بازار", term: "breadth" },
};

const FAMILIES: { re: RegExp; label: (m: RegExpMatchArray) => string; term: GlossaryKey }[] = [
  { re: /^ret_(\d+)$/, label: (m) => `بازده ${m[1]} روزه`, term: "return_n" },
  { re: /^roc_(\d+)$/, label: (m) => `نرخ تغییر ${m[1]} روزه`, term: "return_n" },
  { re: /^sma_(\d+)_dist$/, label: (m) => `فاصله از SMA ${m[1]}`, term: "moving_average" },
  { re: /^ema_(\d+)_dist$/, label: (m) => `فاصله از EMA ${m[1]}`, term: "moving_average" },
];

/** Persian label and glossary entry for a model feature; unknown features keep their key. */
export function featureInfo(key: string): FeatureInfo {
  const known = FEATURES[key];
  if (known) return known;
  for (const f of FAMILIES) {
    const m = key.match(f.re);
    if (m) return { label: f.label(m), term: f.term };
  }
  return { label: key, term: "feature_value" };
}
