# Derived from the user-uploaded dual45 source.
# Standalone stdlib, public GET requests only; never submits real orders.
# Paper fills retain the original ask-touch assumption; fees/queue/slippage are not modeled.
# Railway: python -u kalshi_btc15m_choppy_only_paper.py
# For restart persistence set the model-specific state environment variable to a volume path.
# Railway deployment refresh
"""Paper strategy: place $50 YES and $50 NO limits at 45 cents, hold to settlement.

Run in VS Code: python kalshi_btc15m_choppy_only_paper.py
No API key or account access. Start before a new BTC 15-minute market opens.
"""

import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path


# =============================================================================
# SETTINGS
# =============================================================================

BASE = 'https://external-api.kalshi.com/trade-api/v2'
SERIES = 'KXBTC15M'

LIMIT_CENTS = 45
BUDGET_PER_SIDE_DOLLARS = 50

CONTRACTS_PER_SIDE = int(
    BUDGET_PER_SIDE_DOLLARS * 100 // LIMIT_CENTS
)

POLL_SECONDS = 2

STATE_PATH = Path(
    os.getenv('PAPER_CHOPPY_ONLY_STATE_PATH')
    or Path(__file__).with_name('kalshi_btc15m_choppy_only_state.json')
)

SEPARATOR = '=' * 88


# =============================================================================
# BASIC HELPERS
# =============================================================================

def clock():
    """Return local date/time to the second."""
    return datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')


def unix(iso):
    return datetime.fromisoformat(
        iso.replace('Z', '+00:00')
    ).timestamp()


def get(path, params=None):
    query = '?' + urllib.parse.urlencode(params) if params else ''

    request = urllib.request.Request(
        BASE + path + query,
        headers={'User-Agent': 'btc15m-dual45-paper/1.0'}
    )

    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def ask_cents(market):
    yes_ask = round(
        float(market['yes_ask_dollars']) * 100,
        2
    )

    no_ask = round(
        float(market['no_ask_dollars']) * 100,
        2
    )

    return {
        'YES': yes_ask,
        'NO': no_ask
    }


# =============================================================================
# STATE
# =============================================================================

def read_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())

    return {}


def write_state(state):
    STATE_PATH.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    temporary = STATE_PATH.with_name(
        f'{STATE_PATH.name}.{os.getpid()}.tmp'
    )

    for attempt in range(5):
        try:
            temporary.write_text(
                json.dumps(state, indent=2)
            )

            temporary.replace(STATE_PATH)
            return

        except PermissionError:
            if attempt == 4:
                raise

            time.sleep(0.1 * (attempt + 1))


def acquire_instance_lock():
    """
    Prevent two copies of the program from changing
    the same paper-trading ledger.
    """

    STATE_PATH.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    lock_path = STATE_PATH.with_name(
        STATE_PATH.name + '.lock'
    )

    lock = lock_path.open('a+b')

    lock.seek(0, 2)

    if lock.tell() == 0:
        lock.write(b'0')
        lock.flush()

    lock.seek(0)

    try:
        if os.name == 'nt':
            import msvcrt

            msvcrt.locking(
                lock.fileno(),
                msvcrt.LK_NBLCK,
                1
            )

        else:
            import fcntl

            fcntl.flock(
                lock.fileno(),
                fcntl.LOCK_EX | fcntl.LOCK_NB
            )

    except (OSError, BlockingIOError):
        lock.close()
        return None

    return lock


# =============================================================================
# PERFORMANCE STATISTICS
# =============================================================================

def total_pnl(state):
    """Total realized/confirmed paper P&L."""

    return round(
        sum(
            record.get('final_pnl_dollars', 0)
            for record in state.values()
        ),
        2
    )


def trade_stats(state):
    """
    Calculate statistics for completed trades.

    A win = final P&L > $0
    A loss = final P&L < $0
    Breakeven = final P&L == $0

    Markets with no fills are not counted as trades.
    """

    completed = [
        record
        for record in state.values()
        if record.get('settled_printed')
        and record.get('fills')
        and 'final_pnl_dollars' in record
    ]

    wins = sum(
        record['final_pnl_dollars'] > 0
        for record in completed
    )

    losses = sum(
        record['final_pnl_dollars'] < 0
        for record in completed
    )

    breakevens = sum(
        record['final_pnl_dollars'] == 0
        for record in completed
    )

    total = len(completed)

    decided = wins + losses

    win_rate = (
        wins / decided * 100
        if decided
        else 0.0
    )

    return {
        'wins': wins,
        'losses': losses,
        'breakevens': breakevens,
        'total': total,
        'win_rate': win_rate
    }


# =============================================================================
# DISPLAY HELPERS
# =============================================================================

def print_new_market(ticker):
    print()
    print(SEPARATOR)

    print(f'MARKET: {ticker}')

    print()

    print(
        f'{clock()} | PAPER LIMITS PLACED | '
        f'YES: {CONTRACTS_PER_SIDE} @ {LIMIT_CENTS}c | '
        f'NO: {CONTRACTS_PER_SIDE} @ {LIMIT_CENTS}c',
        flush=True
    )


def print_fill(side, fill):
    print(
        f'{fill["time"]} | '
        f'PAPER FILL {side:<3}       | '
        f'{fill["contracts"]} @ '
        f'{fill["price_cents"]:.2f}c | '
        f'Cost: ${fill["cost_dollars"]:.2f}',
        flush=True
    )


def print_missing_fill(side):
    print(
        f'{"":24} | '
        f'PAPER FILL {side:<3}       | NO',
        flush=True
    )


def print_final_result(ticker, record, state, result):
    """
    Print the final settlement and strategy statistics.
    """

    fills = record.get('fills', {})

    # Show any side that never filled.
    if 'YES' not in fills:
        print_missing_fill('YES')

    if 'NO' not in fills:
        print_missing_fill('NO')

    print(
        f'{clock()} | MARKET OUTCOME        | {result}',
        flush=True
    )

    print()

    profit = record.get(
        'final_pnl_dollars',
        0.0
    )

    stats = trade_stats(state)

    decided = (
        stats['wins']
        + stats['losses']
    )

    print(
        f'TRADE P&L: ${profit:+.2f}'
        f'    |    '
        f'TOTAL P&L: ${total_pnl(state):+.2f}'
        f'    |    '
        f'WIN RATE: {stats["win_rate"]:.1f}% '
        f'({stats["wins"]}/{decided})',
        flush=True
    )

    print(SEPARATOR, flush=True)


# =============================================================================
# MARKET CLOSE
# =============================================================================

def summarize_close(ticker, record, state):
    """
    Called shortly after the 15-minute market closes.

    We do NOT assume the outcome yet because Kalshi may
    take additional time to publish the official result.
    """

    fills = record.get('fills', {})

    if not fills:
        record['final_pnl_dollars'] = 0.0

        print(
            f'{clock()} | MARKET CLOSED         | '
            f'NO TRADE | Awaiting official outcome',
            flush=True
        )

        return

    # If both sides filled, the P&L is already mathematically
    # locked in because one side must settle at $1.
    if len(fills) == 2:
        spent = round(
            sum(
                fill['cost_dollars']
                for fill in fills.values()
            ),
            2
        )

        record['final_pnl_dollars'] = round(
            CONTRACTS_PER_SIDE - spent,
            2
        )

    print(
        f'{clock()} | MARKET CLOSED         | '
        f'Awaiting official outcome...',
        flush=True
    )


# =============================================================================
# SETTLEMENT CHECKING
# =============================================================================

def check_previous(state):
    now = time.time()

    for ticker, record in list(state.items()):

        # -------------------------------------------------------------
        # Market has closed
        # -------------------------------------------------------------

        if (
            not record.get('closed_printed')
            and now >= unix(record['close_time']) + 2
        ):
            summarize_close(
                ticker,
                record,
                state
            )

            record['closed_printed'] = True

            write_state(state)

        # -------------------------------------------------------------
        # Nothing else to do yet
        # -------------------------------------------------------------

        if not record.get('closed_printed'):
            continue

        if record.get('settled_printed'):
            continue

        # No fills = nothing financially to settle.
        # We still wait for official outcome so the market block
        # can be completed cleanly.
        # -------------------------------------------------------------

        if (
            now
            - record.get(
                'last_settlement_check',
                0
            )
            < 30
        ):
            continue

        record['last_settlement_check'] = now

        write_state(state)

        # -------------------------------------------------------------
        # Ask Kalshi for official settlement
        # -------------------------------------------------------------

        market = get(
            '/markets/'
            + urllib.parse.quote(
                ticker,
                safe=''
            )
        )['market']

        result = str(
            market.get('result', '')
        ).upper()

        if result not in ('YES', 'NO'):
            continue

        fills = record.get('fills', {})

        # -------------------------------------------------------------
        # Calculate final P&L
        # -------------------------------------------------------------

        if fills:

            spent = round(
                sum(
                    fill['cost_dollars']
                    for fill in fills.values()
                ),
                2
            )

            payout = (
                fills[result]['contracts']
                if result in fills
                else 0
            )

            profit = round(
                payout - spent,
                2
            )

        else:
            profit = 0.0

        record['final_pnl_dollars'] = profit

        # Mark settled BEFORE calculating displayed statistics,
        # so this trade is included in the win rate.
        record['settled_printed'] = True

        write_state(state)

        # -------------------------------------------------------------
        # Final clean output
        # -------------------------------------------------------------

        print_final_result(
            ticker,
            record,
            state,
            result
        )


# =============================================================================
# MAIN
# =============================================================================


from decimal import Decimal
MODEL = 'choppy_only'
MODE = 'choppy'
HEDGE_LIMIT = 0

# Initial forward-test choices, not fitted to Kalshi outcomes:
# 21 consecutive completed 1-minute Coinbase BTC-USD closes (20 returns).
# CHOPPY requires efficiency <= .35, |20m return| <= .25%,
# |OLS slope| <= .015% per minute, reversal rate >= .40 and >= 6 reversals.
# All conditions must pass; ambiguous and directional periods are skipped.
# Tiny moves under .5 basis points are ignored for reversal counting, to avoid
# labeling quote noise as choppiness. Flat/no-movement windows are skipped.
# Only candles completed before cycle open are used. Decision fixed all cycle.
# Public stdlib GET, once per cycle; missing/stale/malformed data -> SKIP.
# https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles
import math
from datetime import timezone


def classify_closes(prices):
    if len(prices) != 21 or any(not math.isfinite(p) or p <= 0 for p in prices):
        raise ValueError('Need 21 valid closes')
    changes = [b - a for a, b in zip(prices, prices[1:])]
    travel = sum(abs(d) for d in changes)
    efficiency = abs(prices[-1] - prices[0]) / travel if travel else 1.0
    return_pct = (prices[-1] / prices[0] - 1) * 100
    mean = sum(prices) / 21
    slope_pct = sum((i - 10) * (p - mean) for i, p in enumerate(prices)) / 770 / mean * 100
    signs = [1 if d > 0 else -1 for p, d in zip(prices, changes) if abs(d) / p >= .00005]
    reversals = sum(a != b for a, b in zip(signs, signs[1:]))
    reversal_rate = reversals / (len(signs) - 1) if len(signs) > 1 else 0
    trade = (efficiency <= .35 and abs(return_pct) <= .25 and abs(slope_pct) <= .015
             and reversals >= 6 and reversal_rate >= .40)
    return dict(decision='TRADE' if trade else 'SKIP',
                reason='CHOPPY' if trade else 'DIRECTIONAL_OR_INSUFFICIENT_CHOP',
                efficiency=efficiency, return_pct=return_pct, slope_pct_per_min=slope_pct,
                reversals=reversals, reversal_rate=reversal_rate, candle_count=21)


def choppy_filter(cycle_open):
    try:
        end = int(cycle_open // 60) * 60
        start = end - 21 * 60
        iso = lambda t: datetime.fromtimestamp(t, timezone.utc).isoformat()
        query = urllib.parse.urlencode(dict(granularity=60, start=iso(start), end=iso(end)))
        request = urllib.request.Request('https://api.exchange.coinbase.com/products/BTC-USD/candles?' + query,
                                         headers={'User-Agent': 'btc15m-choppy-paper/1.0'})
        with urllib.request.urlopen(request, timeout=10) as response:
            rows = json.load(response)
        if not isinstance(rows, list):
            raise ValueError('Invalid candle response')
        candles = {}
        for row in rows:
            timestamp = int(row[0])
            if start <= timestamp < end:
                if timestamp in candles:
                    raise ValueError('Duplicate candle')
                candles[timestamp] = float(row[4])
        expected = list(range(start, end, 60))
        if sorted(candles) != expected:
            raise ValueError('Missing or stale completed minute candles')
        metrics = classify_closes([candles[t] for t in expected])
        metrics.update(source='Coinbase BTC-USD', window_start=iso(start), window_end=iso(end))
        return metrics
    except Exception as exc:
        return dict(decision='SKIP', reason='BTC_DATA_UNAVAILABLE', error=str(exc),
                    efficiency=None, return_pct=None, slope_pct_per_min=None,
                    reversals=None, reversal_rate=None)

def log(event, **fields):
    print(f'{clock()} | {MODEL} | {event} | ' + json.dumps(fields, sort_keys=True), flush=True)


def paper_fill(ask, limit):
    # Size at the resting limit, never increase quantity on price improvement.
    price = Decimal(str(ask))
    if not price.is_finite() or not 0 < price <= limit <= 100:
        raise ValueError('Invalid limit fill')
    quantity = 5000 // limit
    cost = price * quantity
    if quantity <= 0 or cost > 5000:
        raise ValueError('Hard $50 per-side cap exceeded')
    return dict(price_cents=float(price), time=clock(), contracts=quantity,
                cost_dollars=float((cost / 100).quantize(Decimal('0.01'))),
                limit_cents=limit, fill_type='LIMIT')


def fill_limits(record, quotes, key='fills', limits=None):
    fills = record.setdefault(key, {})
    added = []
    for side in ('YES', 'NO'):
        limit = (limits or {}).get(side, 45)
        ask = quotes[side]
        if side not in fills and ask.is_finite() and 0 < ask <= limit:
            fills[side] = paper_fill(ask, limit)
            added.append(side)
    return added


def exact_quotes(market):
    return {side: Decimal(str(market[side.lower() + '_ask_dollars'])) * 100
            for side in ('YES', 'NO')}


def pnl(fills, result):
    return round(fills.get(result, {}).get('contracts', 0) -
                 sum(f['cost_dollars'] for f in fills.values()), 2)


def process_quotes(ticker, record, quotes, state, now):
    if now >= unix(record['close_time']):
        return
    if MODE == 'hedge':
        # First poll at/after minute 10: atomically cancel/replace the missing
        # 45c order, then evaluate the new limit. Persist before any fill.
        if now >= unix(record['open_time']) + 600 and not record.get('ten_minute_check_done'):
            record['ten_minute_check_done'] = True
            if len(record['fills']) == 1:
                missing = 'NO' if 'YES' in record['fills'] else 'YES'
                record['limits'][missing] = HEDGE_LIMIT
                record['replacement_side'] = missing
            write_state(state)
            log('10MIN LIMIT DECISION', ticker=ticker, limits=record['limits'],
                replacement_side=record.get('replacement_side'),
                seconds_late=round(now - unix(record['open_time']) - 600, 2))
        added = fill_limits(record, quotes, limits=record['limits'])
    elif MODE == 'trigger':
        observed = fill_limits(record, quotes, key='hypothetical_fills')
        for side in observed:
            log('HYPOTHETICAL FILL ONLY', ticker=ticker, side=side,
                fill=record['hypothetical_fills'][side])
        added = fill_limits(record, quotes) if record['strategy_active'] else []
    else:
        added = fill_limits(record, quotes) if record['strategy_active'] else []
    write_state(state)
    for side in added:
        log('STRATEGY PAPER FILL', ticker=ticker, side=side, fill=record['fills'][side])


def main():
    instance_lock = acquire_instance_lock()
    if instance_lock is None:
        log('ANOTHER INSTANCE OWNS LEDGER')
        return
    state = read_state()
    started = time.time()
    startup_skips = set()
    log('START PAPER ONLY', state_path=str(STATE_PATH), total_pnl=total_pnl(state))
    while True:
        try:
            check_previous(state)
            listing = get('/markets', {'series_ticker': SERIES, 'status': 'open', 'limit': 100})
            now = time.time()
            active = [m for m in listing['markets']
                      if unix(m['open_time']) <= now < unix(m['close_time'])]
            market = min(active, key=lambda m: unix(m['close_time'])) if active else None
            if market:
                ticker = market['ticker']
                if ticker not in state:
                    record = dict(open_time=market['open_time'], close_time=market['close_time'], fills={})
                    # Do not invent quotes/fills for an already-running cycle.
                    if unix(market['open_time']) < started - 2:
                        if ticker not in startup_skips:
                            log('SKIP STARTUP PARTIAL CYCLE', ticker=ticker)
                            startup_skips.add(ticker)
                        time.sleep(POLL_SECONDS)
                        continue
                    if MODE == 'hedge':
                        record.update(limits={'YES': 45, 'NO': 45}, ten_minute_check_done=False)
                    elif MODE == 'trigger':
                        record.update(hypothetical_fills={}, strategy_active=False)
                    else:
                        record['filter'] = choppy_filter(unix(market['open_time']))
                        record['strategy_active'] = record['filter']['decision'] == 'TRADE'
                        log('BTC FILTER', ticker=ticker, **record['filter'])
                    state[ticker] = record
                    write_state(state)
                    log('NEW CYCLE', ticker=ticker)
                record = state[ticker]
                if MODE == 'trigger':
                    advance_trigger(state)
                fresh = get('/markets/' + urllib.parse.quote(ticker, safe=''))['market']
                # Recheck wall clock after network calls; never fill after expiry.
                if fresh.get('status') in ('open', 'active') and time.time() < unix(record['close_time']):
                    process_quotes(ticker, record, exact_quotes(fresh), state, time.time())
            time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:
            log('STOPPED')
            return
        except Exception as exc:
            log('ERROR RETRY IN 5 SECONDS', error=str(exc))
            time.sleep(5)


if __name__ == '__main__':
    main()
