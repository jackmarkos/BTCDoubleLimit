# Railway deployment refresh
"""Paper strategy: place $50 YES and $50 NO limits at 45 cents, hold to settlement.

Run in VS Code: python kalshi_btc15m_dual45_paper.py
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
    os.getenv('PAPER_STATE_PATH')
    or Path(__file__).with_name('kalshi_btc15m_dual45_state.json')
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

def main():

    instance_lock = acquire_instance_lock()

    if instance_lock is None:
        print(
            f'{clock()} | '
            f'ANOTHER COPY IS ALREADY RUNNING '
            f'WITH THIS PAPER LEDGER',
            flush=True
        )

        return

    state = read_state()

    # -----------------------------------------------------------------
    # Migrate older saved state
    # -----------------------------------------------------------------

    migrated = False

    for record in state.values():

        if (
            not record.get('closed_printed')
            or 'final_pnl_dollars' in record
        ):
            continue

        fills = record.get(
            'fills',
            {}
        )

        if len(fills) == 2:

            record['final_pnl_dollars'] = round(
                CONTRACTS_PER_SIDE
                - sum(
                    fill['cost_dollars']
                    for fill in fills.values()
                ),
                2
            )

        elif not fills:

            record['final_pnl_dollars'] = 0.0

        else:

            # Recheck official settlement for an older
            # one-sided trade.
            record['settled_printed'] = False

        migrated = True

    if migrated:
        write_state(state)

    # -----------------------------------------------------------------
    # Startup
    # -----------------------------------------------------------------

    started = time.time()

    stats = trade_stats(state)

    print(SEPARATOR)

    print(
        f'{clock()} | RUNNING | PAPER ONLY',
        flush=True
    )

    print(
        f'STRATEGY: '
        f'{CONTRACTS_PER_SIDE} YES @ {LIMIT_CENTS}c '
        f'and '
        f'{CONTRACTS_PER_SIDE} NO @ {LIMIT_CENTS}c',
        flush=True
    )

    print(
        f'TOTAL CONFIRMED PAPER P&L: '
        f'${total_pnl(state):+.2f}',
        flush=True
    )

    print(
        f'RECORD: '
        f'{stats["wins"]} wins | '
        f'{stats["losses"]} losses | '
        f'{stats["breakevens"]} breakeven',
        flush=True
    )

    print(SEPARATOR)

    # -----------------------------------------------------------------
    # Main loop
    # -----------------------------------------------------------------

    while True:

        try:

            # Check older markets for close/settlement.
            check_previous(state)

            now = time.time()

            # ---------------------------------------------------------
            # Find currently active BTC 15-minute market
            # ---------------------------------------------------------

            listing = get(
                '/markets',
                {
                    'series_ticker': SERIES,
                    'status': 'open',
                    'limit': 100
                }
            )

            active = [
                market
                for market in listing['markets']
                if (
                    unix(market['open_time'])
                    <= now
                    < unix(market['close_time'])
                )
            ]

            market = (
                min(
                    active,
                    key=lambda m: unix(
                        m['close_time']
                    )
                )
                if active
                else None
            )

            # ---------------------------------------------------------
            # Active market
            # ---------------------------------------------------------

            if market:

                ticker = market['ticker']

                # -----------------------------------------------------
                # New market
                # -----------------------------------------------------

                if ticker not in state:

                    # Do not pretend we placed limits before
                    # the script was started.
                    if (
                        unix(market['open_time'])
                        < started - 2
                    ):
                        time.sleep(POLL_SECONDS)
                        continue

                    state[ticker] = {
                        'close_time': market['close_time'],
                        'fills': {}
                    }

                    write_state(state)

                    print_new_market(ticker)

                record = state[ticker]

                # -----------------------------------------------------
                # Get fresh market prices
                # -----------------------------------------------------

                fresh = get(
                    '/markets/'
                    + urllib.parse.quote(
                        ticker,
                        safe=''
                    )
                )['market']

                # -----------------------------------------------------
                # Check YES and NO limits
                # -----------------------------------------------------

                for side, ask in ask_cents(
                    fresh
                ).items():

                    if (
                        side not in record['fills']
                        and 0 < ask <= LIMIT_CENTS
                    ):

                        fill = {
                            'price_cents': ask,
                            'time': clock(),
                            'contracts': CONTRACTS_PER_SIDE,
                            'cost_dollars': round(
                                CONTRACTS_PER_SIDE
                                * ask
                                / 100,
                                2
                            )
                        }

                        record['fills'][side] = fill

                        write_state(state)

                        print_fill(
                            side,
                            fill
                        )

            # Still polls every 2 seconds.
            # We simply don't print a heartbeat every 30 seconds.
            time.sleep(POLL_SECONDS)

        except KeyboardInterrupt:

            print(
                f'\n{clock()} | STOPPED',
                flush=True
            )

            return

        except Exception as exc:

            print(
                f'{clock()} | ERROR | '
                f'{exc} | retrying in 5 seconds',
                flush=True
            )

            time.sleep(5)


if __name__ == '__main__':
    main()
