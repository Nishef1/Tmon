// Where each chart and risk term of the glossary shows up on a symbol page, so its glossary
// entry can say where to look. Terms that are only defined (no number on the site) are left out.

const CHART = "نمودار شمعی صفحهٔ نماد";
const OVER = `${CHART}، دکمه‌های «روی قیمت»`;
const PANE = `${CHART}، دکمه‌های «زیر نمودار»`;
const TA = "کارت «تابلوی تکنیکال» صفحهٔ نماد";
const RISK = `${TA}، بخش ریسک`;

export const SHOWN_ON: Record<string, readonly string[]> = {
  sma: [`${CHART}: میانگین ۲۰ و ۵۰ روزه، و «میانگین ۲۰۰ روزه» در «روی قیمت»`, TA],
  moving_average: [CHART, TA],
  ema: [`${OVER}: «EMA ۱۲ و ۲۶»`, TA],
  bollinger: [`${OVER}: «باند بولینگر»`, TA],
  ichimoku: [`${OVER}: «ایچیموکو»`, TA],
  vwap: [`${OVER}: «VWAP ۲۰ روزه»`, TA],
  support_resistance: [`${OVER}: «حمایت، مقاومت، پیوت و فیبو»`, TA],
  fibonacci: [`${OVER}: «حمایت، مقاومت، پیوت و فیبو»`, TA],
  rsi: [`${PANE}: RSI`, TA],
  macd: [`${PANE}: MACD`, TA],
  stochastic: [`${PANE}: استوکاستیک`, TA],
  mfi: [`${PANE}: MFI`, TA],
  adx: [`${PANE}: ADX`, TA],
  atr: [`${PANE}: ATR٪`, TA],
  obv: [`${PANE}: OBV`, TA],
  divergence: [`${PANE}: RSI یا OBV (قله‌ها و کف‌های قیمت و اندیکاتور را مقایسه کنید)`, TA],
  gap_fill: [CHART, TA],
  rel_volume: [CHART, TA],
  net_flow: ["کارت جریان پول حقیقی صفحهٔ نماد", TA],
  buy_power: ["کارت جریان پول حقیقی صفحهٔ نماد", TA],
  per_capita_buy: ["کارت جریان پول حقیقی صفحهٔ نماد", TA],
  smart_money: [TA],
  return_n: [CHART, TA],
  volatility: [RISK],
  var: [RISK],
  max_drawdown: [RISK],
  sharpe: [RISK],
  sortino: [RISK],
  beta: [RISK, "کارت «چه چیزی این سهم را بالا و پایین می‌برد؟»"],
  realized_return: [RISK],
};
