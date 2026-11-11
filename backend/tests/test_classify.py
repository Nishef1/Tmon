from tmon.domain.enums import InstrumentType as T
from tmon.ingest.tsetmc.classify import load_classifier


def test_classifier_rules_and_default():
    c = load_classifier()
    assert c.classify(group_title=None, name_fa="حق تقدم شرکت x") == (T.RIGHT, True)
    assert c.classify(group_title="صندوق سرمایه گذاری قابل معامله", name_fa="x")[0] == T.ETF_EQUITY
    assert c.classify(group_title=None, name_fa="صندوق درآمد ثابت x")[0] == T.ETF_FIXED_INCOME
    assert c.classify(group_title="اوراق مرابحه", name_fa="x")[0] == T.BOND
    assert c.classify(group_title="بازار اول", name_fa="شرکت فولاد") == (T.STOCK, False)
    assert c.is_tradable(T.STOCK) and not c.is_tradable(T.RIGHT) and not c.is_tradable(T.BOND)


def test_derivatives_are_never_stocks_and_universe_follows_adr_0002():
    c = load_classifier()
    # option names are abbreviated on TSETMC; the derivatives board catches whatever rules miss
    assert c.classify(group_title="-'", name_fa="اختیارخ اهرم-30000-1405/08/27")[0] == T.OPTION_CALL
    assert c.classify(group_title=None, name_fa="اختیارف خودرو-9000-1405/09/01")[0] == T.OPTION_PUT
    assert c.classify(group_title=None, name_fa="چیز عجیب", board="بازار مشتقه") == (T.FUTURE, True)

    ok = {"board": "بازار بورس", "group_title": "بازار اول (بورس)"}
    assert c.is_recommendable(T.STOCK, **ok)
    assert c.is_recommendable(T.ETF_EQUITY, **ok) and c.is_recommendable(T.ETF_MIXED, **ok)
    assert c.is_recommendable(
        T.STOCK, board="بازار پایه فرابورس", group_title="بازار پایه زرد فرابورس"
    )
    # out: orange and red base markets, other funds, rights, bonds, derivatives
    for g in ("بازار پایه نارنجی فرابورس", "بازار پایه قرمز فرابورس"):
        assert not c.is_recommendable(T.STOCK, board="بازار پایه فرابورس", group_title=g)
    for t in (T.ETF_FIXED_INCOME, T.ETF_LEVERAGED, T.ETF_COMMODITY, T.RIGHT, T.BOND, T.OPTION_CALL):
        assert not c.is_recommendable(t, **ok)
    assert not c.is_recommendable(T.STOCK, board="بازار مشتقه", group_title=None)
    # kept for the comparison page, though not recommendable
    assert c.is_tradable(T.ETF_FIXED_INCOME) and not c.is_recommendable(T.ETF_FIXED_INCOME, **ok)


def test_type_code_decides_over_keywords():
    """TSETMC's ``yVal`` (names and codes as stored from GetInstrumentInfo in the backfill)."""
    c = load_classifier()
    cases = {
        ("300", "ح. کویر تایر"): T.STOCK,  # code wins over the name
        ("400", "ح. کویر تایر"): T.RIGHT,  # "ح." rights no keyword caught
        ("380", "صندوق طلای عیار مفید"): T.ETF_COMMODITY,
        ("307", "امتیاز تسهیلات مسکن سال1403"): T.OTHER,
        ("308", "سلف استاندارد مغز پسته فنسی"): T.OTHER,
        ("306", "اسنادخزانه اسلامی"): T.BOND,
        ("311", "اختیارخ اهرم-80000-1405/08/27"): T.OPTION_CALL,
        ("321", "اختیارف خودرو"): T.OPTION_PUT,
        ("701", "زعفران"): T.COMMODITY_CERTIFICATE,
    }
    for (code, name), want in cases.items():
        assert c.classify(group_title=None, name_fa=name, type_code=code) == (want, True), name
    # an unknown code falls back to the keyword rules
    assert c.classify(group_title=None, name_fa="حق تقدم x", type_code="999")[0] == T.RIGHT


def test_fund_subtype_from_fund_description_then_name():
    c = load_classifier()

    def fund(desc, name="صندوق س. x"):
        return c.classify(group_title=None, name_fa=name, type_code="305", fund_desc=desc)

    assert fund("نوع صندوق : در اوراق بهادار با درآمد ثابت") == (T.ETF_FIXED_INCOME, True)
    assert fund("نوع صندوق : در اوارق بهادار با درآمد ثابت")[0] == T.ETF_FIXED_INCOME  # typo
    assert fund("نوع صندوق: سهامي")[0] == T.ETF_EQUITY  # Arabic yeh
    assert fund("نوع صندوق : سهامی بخشی در صنعت بانک ها")[0] == T.ETF_EQUITY
    assert fund("نوع صندوق: سهامي شاخصي")[0] == T.ETF_EQUITY
    assert fund("نوع صندوق: در سهام-با ساختار قابل معامله")[0] == T.ETF_EQUITY
    assert fund("نوع صندوق : سهامی اهرمی")[0] == T.ETF_LEVERAGED
    assert fund("نوع صندوق: مختلط")[0] == T.ETF_MIXED
    for desc in ("نوع صندوق : املاک و مستغلات", "نوع صندوق :  جسورانه", "نوع صندوق : خصوصی",
                 "نوع صندوق : صندوق در صندوق"):  # fmt: skip
        assert fund(desc)[0] == T.OTHER, desc
    # no description: the name, then the unit suffix
    assert fund(None, "ص.س.درآمدثابت اندوخته داريوش-د")[0] == T.ETF_FIXED_INCOME
    assert fund(None, "صندوق س.بخشي داريوش4-ب")[0] == T.ETF_EQUITY
    assert fund(None, "صندوق س.آوان ژرف آگاه-س")[0] == T.ETF_EQUITY
    assert fund("", "ص.س املاك وم.كاشانه خليج فارس")[0] == T.OTHER
    # nothing to go on: kept, never recommended, flagged
    assert fund(None, "صندوق نامعلوم") == (T.OTHER, False)
    ok = {"board": "بازار بورس", "group_title": "بازار صندوق های قابل معامله"}
    assert not c.is_recommendable(T.OTHER, **ok) and not c.is_tradable(T.OTHER)


def test_noafarin_market_is_not_in_the_universe():
    c = load_classifier()
    for g in ("بازار نوآفرین - رشد", "بازار نوآفرین - دانش بنیان"):
        assert not c.is_recommendable(T.STOCK, board="بازار فرابورس", group_title=g)
