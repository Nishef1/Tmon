"""The dividend per share in a Codal decisions letter (ن-۵۲)."""

from tmon.ingest.codal.dividends import is_captcha, parse_dps

ROW = (
    '<tr class="ComputationalRow"><td class="Hidden PropertyName">DividendPerShare</td>'
    '<td class="DescriptionColumn"><span>سود نقدی هر سهم (ریال)</span></td>'
    '<td class="GridItem YearColumn"><div></div>'
    '<input name="x$txbYear" type="text" value="{v}" id="x_txbYear" '
    'class="Hidden YearColumn CurrentPeriod" style="width:80%;">'
    '<span class="spanFormattedValue">۸۰۰</span></td></tr>'
    '<tr class="ComputationalRow"><td class="Hidden PropertyName">ListedCapital</td></tr>'
)


def test_reads_the_current_period_value() -> None:
    assert parse_dps(ROW.format(v="800")) == 800.0


def test_thousands_separator_and_persian_digits() -> None:
    assert parse_dps(ROW.format(v="۱,۲۵۰")) == 1250.0


def test_blank_cell_or_missing_row_is_none() -> None:
    assert parse_dps(ROW.format(v="")) is None
    assert parse_dps("<html><body>تصمیمات مجمع</body></html>") is None


def test_does_not_read_the_next_row() -> None:
    html = ROW.format(v="").replace('<td class="GridItem', '<td class="Other') + (
        '<tr><td class="Hidden PropertyName">Other</td><input value="9" class="CurrentPeriod"></tr>'
    )
    assert parse_dps(html) is None


def test_captcha_page_is_detected() -> None:
    assert is_captcha('<input id="captchaCode"><title>تأیید کاربر</title>')
    assert not is_captcha(ROW.format(v="800"))
