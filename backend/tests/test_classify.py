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
