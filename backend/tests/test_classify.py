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
