# Open interest in Freqtrade: what to check before you build on it

Freqtrade merged open interest candles on **2026-08-30**
([#13503](https://github.com/freqtrade/freqtrade/pull/13503)). You can now pull
open interest into a strategy the same way you pull any informative dataframe.

Two things decide whether an open-interest idea is testable at all, and neither
is obvious from the docs. Both are measured below, not quoted.

```bash
python check_oi_coverage.py          # runs against the live public APIs, no keys
```

---

## 1. History depth is the constraint, and venues differ by two orders of magnitude

Open interest history is nothing like candle history. Measured just now, 1h
open interest, 48-hour probe window ending N days ago:

| days back | Bybit (linear) | Binance (USDT-M) |
|---|---|---|
| 7 | 48 rows | 48 rows |
| 30 | 48 rows | **HTTP 400** |
| 365 | 48 rows | **HTTP 400** |
| 730 | 48 rows | **HTTP 400** |
| 1460 | 48 rows | **HTTP 400** |
| 2190 | **48 rows** | **HTTP 400** |

**Binance refuses anything past about a month** — and refuses it outright with
a 400, rather than returning an empty window.

**Bybit serves open interest back to close to the instrument's listing date.**
BTCUSDT returns data from 2020-08, ETHUSDT from 2021-08; each stops only where
the instrument itself does, not at a fixed retention window.

The windows were checked to land where requested: returned timestamps match the
range asked for, and the open interest values differ per period — so this is
genuine history, not recent data echoed back for an out-of-range request. That
check matters, because plenty of APIs silently ignore time parameters, and
"lots of rows returned" would otherwise prove nothing.

The Freqtrade docs warn that Binance "only serves the last 30 days". What they
don't say is that another supported venue serves years of the same data.

The practical consequence: **download open interest from the venue that has the
history, even if you intend to execute somewhere else.** For a backtest, depth
of history beats matching the execution venue — one month of data cannot
distinguish an edge from a regime, and half-year splits are the single cheapest
way to kill a false one.

## 2. Check which column actually carries data

Freqtrade exposes two columns. Exchanges populate one, the other, or both:

| | `open_interest_amount` (base) | `open_interest_value` (quote) |
|---|---|---|
| Bybit linear | yes — `openInterest` | **all NaN** |
| Binance USDT-M | yes — `sumOpenInterest` | yes — `sumOpenInterestValue` |

Both columns are always *present*. An all-NaN column means the venue doesn't
report that side — not that your download failed. On Bybit, a strategy written
against `open_interest_value` produces NaN everywhere and silently never
triggers.

This matters more than it looks. Base-denominated open interest is a contract
count; quote-denominated is that count times price. **A rising quote value can
mean nothing more than a rising price**, so a signal built on it is partly a
price signal wearing a different name. If you want "leverage entering the
instrument", you want the base column — which on Bybit is the only one you get
anyway.

## The API

```python
# direct
open_interest = self.dp.get_pair_dataframe(
    pair=metadata['pair'], timeframe='1h', candle_type="open_interest"
)
dataframe['open_interest'] = open_interest['open_interest_amount']

# or via the informative decorator, which merges it for you
@informative('1h', candle_type='open_interest')
def populate_indicators_oi_1h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
    dataframe['oi_change'] = dataframe['open_interest_amount'].pct_change()
    return dataframe
```

Open interest is **not** part of the default download:

```bash
freqtrade download-data --exchange bybit --pairs BTC/USDT:USDT \
  --timeframes 1h --trading-mode futures --candle-types open_interest
```

If the exchange can't serve the candle type your strategy asks for, the bot
refuses to start rather than running against a permanently empty dataframe.
That is the right behaviour and worth knowing before you blame your config.

---

# What open interest does and does not predict

The following comes from roughly three dozen hypotheses tested over seven
months on hourly crypto perpetual data, with costs charged at the real taker
rate and out-of-sample data kept separate. The full log is in
[dead-ends](https://github.com/EdgeLuck/dead-ends).

Open interest is the one signal family that survived. That is exactly why the
negative results below are worth more than the positive one — they are the
calibration, and they are not intuitive.

### Rising open interest while price is flat is a losing signal

The intuitive read — "positions are building, something is coming" — is
backwards.

Measured against the unconditional base rate, "range-bound price plus rising
open interest" scores **0.47x**. It underperforms doing nothing. The same open
interest increase, when price is *already moving*, scores up to **7.34x**.

Open interest is not a leading indicator. It is a **confirmation** that a move
which has already started has real money behind it. Build it as a filter on an
existing signal, not as a trigger of its own.

### A higher threshold is worse, not better

Having found that an open interest increase confirms a breakout, the obvious
next move is to demand a bigger increase. It was tested across a range up to
6%.

The relationship is **monotonically negative**: the higher the threshold, the
worse the result, and at the top of the range the system loses money outright.

The plausible reason is selection, not signal. By the time open interest has
moved that much, the entry price has moved with it. You are paying for
confirmation you already had.

### Unconditional open interest statistics do not transfer to breakouts

Sorting all bars into quadrants of (price up/down × open interest up/down)
produces clean, significant-looking numbers. They did not survive being applied
to actual breakout entries, and out-of-sample data is what revealed it.

A statistic computed over every bar describes the average bar. Your entries are
not average bars — they are a selected subset, and selection is exactly what
breaks the transfer. Measure the statistic *on your own signals*, not on the
population.

### Volume adds nothing on top of open interest

The natural companion filter — require a volume z-score on the breakout too —
added nothing measurable once open interest was already in the gate. The entire
apparent effect was confined to a single calendar half-year.

Volume tells you contracts changed hands. Open interest tells you whether
positions were *opened* or merely passed between traders. Once you have the
second, the first is largely redundant.

### Falling open interest after a drop: a concentration trap

"Price drops hard while open interest flows out — leverage is leaving, so it
bounces" passed a criterion declared before the run: mean +0.697%, a 3.48x
margin, zero negative half-years out of six.

Then the best five instruments out of 32 were removed, and the mean fell to
+0.199% — exactly one round turn in costs. Removing eight took it negative.

The mechanism was probably an illiquidity premium that slippage in a panic
eats whole. If you test anything like this, **make a concentration check part
of the criterion before you run it**, or "it passed" tells you nothing.

### One more, since it closes a whole class of ideas

Rising open interest during a breakout is often explained as retail piling in.
Measured against exchange account-ratio data, the share of accounts on the
active side **falls** as open interest rises. Whatever is behind these moves,
it is fewer, larger participants — not a retail stampede.

---

## Files

```
check_oi_coverage.py   measures history depth and column availability, live
example_strategy.py    minimal correct usage of the new candle type
```

`check_oi_coverage.py` needs no API key, no freqtrade install, and no
downloaded data. Run it before you plan a backtest window.

## Related

- [dead-ends](https://github.com/EdgeLuck/dead-ends) — the full research log the
  findings above come from, including the four hypotheses that passed a
  pre-declared criterion and were wrong anyway.
- [research-prod-split](https://github.com/EdgeLuck/research-prod-split) — the
  measurement machinery: half-year splits, paired kept-vs-rejected comparison,
  costs charged at the real rate.

MIT licensed.
