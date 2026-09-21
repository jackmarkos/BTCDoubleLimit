"""Paper strategy: place $50 YES and $50 NO limits at 45 cents, hold to settlement.

Run in VS Code: python kalshi_btc15m_dual45_paper.py
No API key or account access. Start before a new BTC 15-minute market opens.
"""

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

BASE = 'https://external-api.kalshi.com/trade-api/v2'
SERIES = 'KXBTC15M'
LIMIT_CENTS = 45
BUDGET_PER_SIDE_DOLLARS = 50
CONTRACTS_PER_SIDE = int(BUDGET_PER_SIDE_DOLLARS * 100 // LIMIT_CENTS)
POLL_SECONDS = 2
STATE_PATH = Path(__file__).with_name('kalshi_btc15m_dual45_state.json')


def clock():
    return datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')


def unix(iso):
    return datetime.fromisoformat(iso.replace('Z', '+00:00')).timestamp()


def get(path, params=None):
    query = '?' + urllib.parse.urlencode(params) if params else ''
    request = urllib.request.Request(BASE + path + query,
                                     headers={'User-Agent': 'btc15m-dual45-paper/1.0'})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def ask_cents(market):
    yes_ask = round(float(market['yes_ask_dollars']) * 100, 2)
    no_ask = round(float(market['no_ask_dollars']) * 100, 2)
    return {'YES': yes_ask, 'NO': no_ask}


def read_state():
    return json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}


def write_state(state):
    temporary = STATE_PATH.with_suffix('.tmp')
    temporary.write_text(json.dumps(state, indent=2))
    temporary.replace(STATE_PATH)


def total_pnl(state):
    return round(sum(record.get('final_pnl_dollars', 0)
                     for record in state.values()), 2)


def summarize_close(ticker, record, state):
    fills = record['fills']
    if not fills:
        record['final_pnl_dollars'] = 0.0
        print(f'{clock()} | {ticker} | NO TRADE | market P&L $0.00 | '
              f'total P&L ${total_pnl(state):+.2f} before fees', flush=True)
    else:
        parts = [f'{side}: {fill["contracts"]} contracts at {fill["price_cents"]:.2f}c '
                 f'(${fill["cost_dollars"]:.2f}) ({fill["time"]})'
                 for side, fill in fills.items()]
        spent = round(sum(fill['cost_dollars'] for fill in fills.values()), 2)
        if len(fills) == 2:
            # One YES and one NO of equal size pay out exactly once at settlement.
            record['final_pnl_dollars'] = round(CONTRACTS_PER_SIDE - spent, 2)
            outcome = f'market P&L ${record["final_pnl_dollars"]:+.2f} (both sides filled)'
        else:
            win_pnl = round(CONTRACTS_PER_SIDE - spent, 2)
            loss_pnl = -spent
            outcome = (f'market P&L pending settlement '
                       f'(if held side wins ${win_pnl:+.2f}; '
                       f'if it loses ${loss_pnl:+.2f})')
        print(f'{clock()} | {ticker} | PAPER TRADE: {"; ".join(parts)} | '
              f'{outcome} | total confirmed P&L ${total_pnl(state):+.2f} '
              f'before fees', flush=True)


def check_previous(state):
    now = time.time()
    for ticker, record in list(state.items()):
        if not record.get('closed_printed') and now >= unix(record['close_time']) + 2:
            summarize_close(ticker, record, state)
            record['closed_printed'] = True
            write_state(state)
        if not record.get('closed_printed') or record.get('settled_printed') or not record['fills']:
            continue
        # Kalshi may publish the official result several minutes after trading closes.
        if now - record.get('last_settlement_check', 0) < 30:
            continue
        record['last_settlement_check'] = now
        write_state(state)
        market = get('/markets/' + urllib.parse.quote(ticker, safe=''))['market']
        result = str(market.get('result', '')).upper()
        if result not in ('YES', 'NO'):
            continue
        spent = sum(fill['cost_dollars'] for fill in record['fills'].values())
        payout = record['fills'][result]['contracts'] if result in record['fills'] else 0
        profit = round(payout - spent, 2)
        record['final_pnl_dollars'] = profit
        print(f'{clock()} | {ticker} | SETTLED {result} | '
              f'{len(record["fills"])} paper fill(s) | '
              f'cost ${spent:.2f} | payout ${payout:.2f} | '
              f'market P&L ${profit:+.2f} | '
              f'total P&L ${total_pnl(state):+.2f} before fees', flush=True)
        record['settled_printed'] = True
        write_state(state)


def main():
    state = read_state()
    # Carry completed markets forward if an older version wrote state without P&L.
    migrated = False
    for record in state.values():
        if not record.get('closed_printed') or 'final_pnl_dollars' in record:
            continue
        fills = record.get('fills', {})
        if len(fills) == 2:
            record['final_pnl_dollars'] = round(
                CONTRACTS_PER_SIDE - sum(f['cost_dollars'] for f in fills.values()), 2)
        elif not fills:
            record['final_pnl_dollars'] = 0.0
        else:
            record['settled_printed'] = False  # Recheck its official result.
        migrated = True
    if migrated:
        write_state(state)
    started = time.time()
    last_heartbeat = 0
    print(f'{clock()} | RUNNING | PAPER ONLY | {CONTRACTS_PER_SIDE} contracts '
          f'({BUDGET_PER_SIDE_DOLLARS} dollars max) on each 45c limit; hold to settlement',
          flush=True)
    print(f'{clock()} | TOTAL CONFIRMED PAPER P&L ${total_pnl(state):+.2f} before fees',
          flush=True)
    while True:
        try:
            check_previous(state)
            now = time.time()
            listing = get('/markets', {'series_ticker': SERIES, 'status': 'open', 'limit': 100})
            active = [m for m in listing['markets']
                      if unix(m['open_time']) <= now < unix(m['close_time'])]
            market = min(active, key=lambda m: unix(m['close_time'])) if active else None
            if now - last_heartbeat >= 30:
                if market:
                    left = round(unix(market['close_time']) - now)
                    print(f'{clock()} | RUNNING | {market["ticker"]} | {left}s left', flush=True)
                else:
                    print(f'{clock()} | RUNNING | waiting for next market', flush=True)
                last_heartbeat = now
            if market:
                ticker = market['ticker']
                if ticker not in state:
                    # A new script run does not pretend it placed limits before launch.
                    if unix(market['open_time']) < started - 2:
                        time.sleep(POLL_SECONDS)
                        continue
                    state[ticker] = {'close_time': market['close_time'], 'fills': {}}
                    write_state(state)
                    print(f'{clock()} | {ticker} | PAPER LIMITS PLACED: '
                          f'{CONTRACTS_PER_SIDE} YES at 45c, '
                          f'{CONTRACTS_PER_SIDE} NO at 45c',
                          flush=True)
                record = state[ticker]
                fresh = get('/markets/' + urllib.parse.quote(ticker, safe=''))['market']
                for side, ask in ask_cents(fresh).items():
                    if side not in record['fills'] and 0 < ask <= LIMIT_CENTS:
                        record['fills'][side] = {
                            'price_cents': ask, 'time': clock(),
                            'contracts': CONTRACTS_PER_SIDE,
                            'cost_dollars': round(CONTRACTS_PER_SIDE * ask / 100, 2),
                        }
                        write_state(state)
                        print(f'{clock()} | {ticker} | PAPER FILL {side}: '
                              f'{CONTRACTS_PER_SIDE} contracts at {ask:.2f}c '
                              f'(${record["fills"][side]["cost_dollars"]:.2f})', flush=True)
            time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:
            print(f'\n{clock()} | stopped', flush=True)
            return
        except Exception as exc:
            print(f'{clock()} | ERROR | {exc} | retrying in 5 seconds', flush=True)
            time.sleep(5)


if __name__ == '__main__':
    main()
