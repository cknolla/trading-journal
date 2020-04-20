#!/usr/bin/env python3
import json
import os
import pickle
from datetime import date, datetime, timedelta
from typing import List
import logging

import pytz
import robin_stocks
import yfinance
from dotenv import load_dotenv
from dateutil import parser

from string_conversions import Case, str_dt, convert_keys

load_dotenv('.env')


def create_report(report: dict):
    filepath = os.path.join('reports', datetime.now().isoformat().replace(':', '-') + '.json')
    logging.info(f'Generating output file {filepath}')
    with open(filepath, 'w') as output_file:
        json.dump(convert_keys(report, Case.SNAKE, Case.CAMEL), output_file, indent=2)


def utc_to_eastern(dt_string: str) -> datetime:
    utc_dt = parser.parse(dt_string)
    eastern_dt = utc_dt.astimezone(pytz.timezone('US/Eastern'))
    return eastern_dt


def get_robinhood_data():
    logging.info(f'Logging into Robinhood...')
    login = robin_stocks.login(username=os.getenv('TJ_USERNAME'), password=os.getenv('TJ_PASSWORD'))
    logging.debug(login)
    logging.info(f'Fetching options orders...')
    all_option_orders = reversed(robin_stocks.orders.get_all_option_orders())
    logging.debug(all_option_orders)
    for order in all_option_orders:
        if order['state'] == 'filled':
            for leg in order['legs']:
                instrument_data = instrument_cache.get(leg['option'])
                expiration_date = str_dt(instrument_data['expiration_date'], '%Y-%m-%d').date()
                option_prices = []
                for execution in leg['executions']:
                    option_prices.extend([float(execution['price']) for quantity in range(int(float(execution['quantity'])))])
                account.execute_trade_event(
                    TradeEvent(
                        ticker=order['chain_symbol'],
                        expiration_date=expiration_date,
                        execution_time=utc_to_eastern(order['created_at']),
                        options=[
                            Option(
                                id_=leg['option'],
                                ticker=order['chain_symbol'],
                                expiration_date=expiration_date,
                                strike=float(instrument_data['strike_price']),
                                price=price,
                                is_call=True if instrument_data['type'] == 'call' else False,
                                is_long=True if leg['side'] == 'buy' else False,
                            ) for price in option_prices
                        ]
                    )
                )
    all_stock_orders = reversed(robin_stocks.orders.get_all_stock_orders())
    logging.debug(all_stock_orders)
    for order in all_stock_orders:
        ticker = instrument_cache.get(order['instrument'])['symbol']
        execution_time = utc_to_eastern(order['last_transaction_at'])
        quantity = int(float(order['quantity']))
        is_long = True if order['side'] == 'buy' else False
        logging.info(f'Adding {"+" if is_long else "-"}{quantity} shares of {ticker}')
        if order['state'] == 'filled' and order['cancel'] is None:
            account.add_shares([
                Share(
                    ticker=ticker,
                    open_time=execution_time,
                    open_price=float(order['average_price']),
                    is_long=is_long
                ) for share in range(quantity)
            ])


def get_open_options(options: List['Option']) -> List['Option']:
    inventory = {
        'call': {},
        'put': {}
    }
    for option in options:
        option_type = 'call' if option.is_call else 'put'
        if inventory[option_type].get(option.strike) is None:
            inventory[option_type][option.strike] = []
        counterpart = None
        for same_strike_option in inventory[option_type][option.strike]:
            if option.is_long != same_strike_option.is_long:
                counterpart = same_strike_option
                break
        if counterpart is not None:
            inventory[option_type][option.strike].remove(counterpart)
        else:
            inventory[option_type][option.strike].append(option)
    open_options = []
    for strikes in inventory.values():
        for strike_options in strikes.values():
            open_options.extend(strike_options)
    return open_options


# TODO: Broken. May not be needed
# def get_option_matches(options: List['Option']) -> tuple:
#     matched_options = {
#         'call': {},
#         'put': {},
#     }
#     unmatched_options = {
#         'call': {},
#         'put': {},
#     }
#     for option in options:
#         option_type = 'call' if option.is_call else 'put'
#         unmatched_options[option_type].setdefault(option.strike, []).append(option)
#         # if inventory[option_type].get(option.strike) is None:
#         #     inventory[option_type][option.strike] = []
#         for same_strike_option in filter(lambda op: op is not option, unmatched_options[option_type][option.strike]):
#             if option.is_long != same_strike_option.is_long:
#                 unmatched_options[option_type][option.strike].remove(same_strike_option)
#                 matched_options[option_type].setdefault(option.strike, []).extend([
#                     option,
#                     same_strike_option,
#                 ])
#                 break
#     return matched_options, unmatched_options


def sort_options(options: List['Option']) -> List['Option']:
    sorted_options = sorted(options, key=lambda option: option.strike)
    sorted_options.sort(key=lambda option: option.is_call)
    return sorted_options


class Cache:
    def __init__(self, filepath):
        """
        If filepath is provided, a file will be created to save the cache on program close.
        If filepath is falsy (emptry string ideally), an in-memory cache will be created instead
        :param filepath: string
        """
        self.filepath = filepath
        if filepath:
            try:
                with open(filepath, 'rb') as file:
                    self.cache = pickle.load(file)
            except (FileNotFoundError, pickle.UnpicklingError):
                self.cache = {}
        else:
            self.cache = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.save()

    def save(self):
        if self.filepath:
            with open(self.filepath, 'wb') as file:
                pickle.dump(self.cache, file)

    def get(self, item):
        obj = self.cache.get(item)
        if obj is not None:
            logging.debug(f'item {item} found in {self.__class__.__name__}')
            return obj
        self.cache[item] = self._get(item)
        return self.cache[item]

    def _get(self, item):
        raise NotImplementedError


class InstrumentCache(Cache):
    def __init__(self):
        super().__init__('.instrument_cache')

    def _get(self, item):
        """
        :param item: instrument url
        :return: instrument payload returned from robinhood
        """
        return robin_stocks.helper.request_get(item)


class ClosingPriceCache(Cache):
    def __init__(self):
        super().__init__('.closing_price_cache')

    def _get(self, item):
        """
        :param item: tuple(ticker: str, expiration_date: date)
        :return: float value of ticker closing price on expiration date
        """
        ticker, expiration_date = item
        next_day = expiration_date + timedelta(days=1)
        logging.info(f'Fetching closing price of {ticker} on {expiration_date}...')
        closing_price = yfinance.download(ticker, start=expiration_date.isoformat(), end=next_day.isoformat(), progress=False)['Close'][expiration_date.isoformat()]
        if hasattr(closing_price, 'array'):
            closing_price = closing_price.array[0]
        return closing_price


class TickerEventCache(Cache):
    def __init__(self):
        """
        An in-memory cache to avoid several event lookups for the same ticker
        """
        super().__init__('')

    def _get(self, item):
        """
        :param item: ticker: str
        :return: list of robinhood events related to ticker
        """
        return robin_stocks.get_events(item)


class Account:
    def __init__(self):
        self.trades = {}  # stored as (ticker, expiration_date): trade
        self.open_shares = {}  # stored as ticker: [Share]
        self.closed_shares = {}

    def execute_trade_event(self, trade_event: 'TradeEvent'):
        trade = self.trades.get((trade_event.ticker, trade_event.expiration_date))
        if trade is None:
            trade = Trade(trade_event.ticker, trade_event.expiration_date, self)
            self.trades[(trade_event.ticker, trade_event.expiration_date)] = trade
        trade.add_event(trade_event)

    def report(self):
        logging.info(f'Building output report...')
        all_trades = list(self.trades.values())
        all_trades.sort(key=lambda trade: trade.expiration_date, reverse=True)
        strategy_count_by_name = {}
        for trade in all_trades:
            trade.resolve_events()
            trade.resolve_expired_options()
        closed_trades = list(filter(lambda trade: trade.is_closed, all_trades))
        for trade in closed_trades:
            for event in trade.trade_events:
                if event.duration > timedelta(minutes=5) and event.strategy.name != 'Close Position':
                    strategy_count_by_name.setdefault(event.strategy.name, 0)
                    strategy_count_by_name[event.strategy.name] += 1
            # sort strategy dictionary by popularity (highest value descending)
            strategy_count_by_name = {key: strategy_count_by_name[key] for key in sorted(strategy_count_by_name, key=strategy_count_by_name.get, reverse=True)}
        open_trades = [trade for trade in all_trades if trade not in closed_trades]
        stats = {
            'total_realized_profit': self.get_total_option_premium_profit(closed_trades) + self.get_total_share_profit(),
            'total_share_profit': self.get_total_share_profit(),
            'share_profit_by_ticker': self.get_share_profit_by_ticker(),
            'closed_shares': {
                ticker: len(shares) for ticker, shares in self.closed_shares.items()
            },
            'open_shares': {
                ticker: len(shares) * (1 if shares and shares[0].is_long else -1) for ticker, shares in self.open_shares.items()
            },
            'total_option_premium_profit': self.get_total_option_premium_profit(closed_trades),
            'option_premium_profit_by_ticker': self.get_option_premium_profit_by_ticker(closed_trades),
            'total_trade_profit': self.get_total_trade_profit(closed_trades),
            'average_trade_profit': self.get_average_trade_profit(closed_trades),
            'trade_profit_by_ticker': self.get_trade_profit_by_ticker(closed_trades),
            'total_trade_count': len(all_trades),
            'trade_count_by_ticker': self.get_trade_count_by_ticker(all_trades),
            'win_percent': self.get_win_percent(closed_trades),
            'average_trade_duration': str(self.get_average_trade_duration(closed_trades)),
            'strategy_count_by_name': strategy_count_by_name,
            'closed_trades': [trade.report() for trade in closed_trades],
            'open_trades': [trade.report() for trade in open_trades],
        }
        create_report(stats)

    def get_total_option_premium_profit(self, trades=None) -> float:
        if trades is None:
            trades = self.trades.values()
        return round(sum(trade.premium_profit for trade in trades), 2)

    def get_option_premium_profit_by_ticker(self, trades=None) -> dict:
        profits_by_ticker = {}
        for trade in trades:
            profits_by_ticker.setdefault(trade.ticker, 0)
            profits_by_ticker[trade.ticker] += trade.premium_profit
        return profits_by_ticker

    def get_total_trade_profit(self, trades=None) -> float:
        if trades is None:
            trades = self.trades.values()
        return round(sum(trade.net_profit for trade in trades), 2)

    def get_trade_profit_by_ticker(self, trades=None) -> dict:
        profits_by_ticker = {}
        for trade in trades:
            profits_by_ticker.setdefault(trade.ticker, 0)
            profits_by_ticker[trade.ticker] += trade.net_profit
        return profits_by_ticker

    def get_average_trade_profit(self, trades=None) -> float:
        if trades is None:
            trades = self.trades.values()
        return round(self.get_total_trade_profit(trades) / len(trades), 2)

    def get_win_percent(self, trades=None) -> float:
        if trades is None:
            trades = self.trades.values()
        wins = [True for trade in trades if trade.is_win]
        return round(len(wins) / len(trades) * 100, 2)

    def get_average_trade_duration(self, trades=None) -> timedelta:
        if trades is None:
            trades = self.trades.values()
        total_duration = sum([trade.duration for trade in trades], timedelta(0))
        return total_duration / len(trades)

    def get_trade_count_by_ticker(self, trades=None) -> dict:
        trades_by_ticker = {}
        for trade in trades:
            trades_by_ticker.setdefault(trade.ticker, 0)
            trades_by_ticker[trade.ticker] += 1
        return trades_by_ticker

    def get_share_profit_by_ticker(self) -> dict:
        results = {}
        for ticker, shares in self.closed_shares.items():
            results[ticker] = sum(share.profit for share in shares)
        return results

    def get_total_share_profit(self) -> float:
        total_profit = 0.0
        for profit in self.get_share_profit_by_ticker().values():
            total_profit += profit
        return total_profit

    def add_shares(self, shares: List['Share']):
        ticker = shares[0].ticker
        # is_long = shares[0].is_long
        self.open_shares.setdefault(ticker, [])
        self.closed_shares.setdefault(ticker, [])
        logging.debug(f'Adding {"+" if shares[0].is_long else "-"}{len(shares)} shares of {ticker} @ ${shares[0].open_price}')
        index = 0
        if self.open_shares[ticker]:
            if self.open_shares[ticker][0].is_long != shares[0].is_long:
                for index, share in enumerate(shares):
                    try:
                        self.open_shares[ticker][0].close_price = share.open_price
                        self.open_shares[ticker][0].close_time = share.open_time
                        self.closed_shares[ticker].append(self.open_shares[ticker][0])
                        self.open_shares[ticker].pop(0)
                    except IndexError:
                        break
                index += 1  # because slice below is inclusive, but exclusive is desired
        self.open_shares[ticker].extend(shares[index:])
        # FIFO sort
        self.open_shares[ticker].sort(key=lambda share: share.open_time)


class Option:
    def __init__(
            self,
            id_: str,
            ticker: str,
            strike: float,
            price: float,
            is_call: bool,
            is_long: bool,
            expiration_date: date,
            **kwargs
    ):
        self.id = id_
        self.ticker = ticker.upper()
        self.strike = strike
        self.price = price
        self.is_call = is_call
        self.is_long = is_long
        self.expiration_date = expiration_date
        logging.info(f'Adding option {self}')

    def __repr__(self):
        return self.__str__()

    def __str__(self):
        return f'<Option {self.ticker} {"+" if self.is_long else "-"}{self.strike}{"c" if self.is_call else "p"} {self.expiration_date}>'

    def report(self):
        return {
            'is_call': self.is_call,
            'is_long': self.is_long,
            'strike': self.strike,
            'price': self.price,
        }

    def get_profit_at(self, underlying_price: float) -> float:
        if self.is_call:
            if self.is_long:
                return max((underlying_price * 100) - (self.strike * 100), 0) - (self.price * 100)
            return min((self.strike * 100 - underlying_price * 100), 0) + self.price * 100
        if self.is_long:
            return max((self.strike * 100) - (underlying_price * 100), 0) - (self.price * 100)
        return min((underlying_price * 100) - (self.strike * 100), 0) + self.price * 100

    def get_collateral(self):
        return self.strike * 100


class Share:
    def __init__(
            self,
            ticker: str,
            open_price: float,
            open_time: datetime,
            is_long: bool,
    ):
        self.ticker = ticker
        self.open_price = open_price
        self.open_time = open_time
        self.is_long = is_long
        self.close_price = None
        self.close_time = None

    def __repr__(self):
        return self.__str__()

    def __str__(self):
        if self.is_closed:
            closed = f''
        return f'<Share {self.ticker} {"+" if self.is_long else "-"}{self.open_price}>'

    def close(
            self,
            close_price: float,
            close_time: datetime,
    ):
        self.close_price = close_price
        self.close_time = close_time

    @property
    def is_closed(self) -> bool:
        return self.close_time is not None

    @property
    def profit(self) -> float:
        if self.is_long:
            return self.close_price - self.open_price
        else:
            return self.open_price - self.close_price


class ShareRepository:
    def __init__(
            self,
            ticker: str,
    ):
        self.ticker = ticker
        self.long_shares = []
        self.short_shares = []
        self.profit = 0.0


class Strategy:
    def __init__(
            self,
            trade_event: 'TradeEvent',
            options: List['Option'],
    ):
        self.trade_event = trade_event
        self.options = sort_options(options)
        self.name = f'{len(self.options)}-Option Strategy'
        self.max_profit = float('nan')
        self.max_loss = float('nan')
        self.collateral = 0.0
        if not self.options:
            self.name = 'Close Position'
            self.max_loss = 0.0
            self.max_profit = 0.0
            return
        self._get_name()
        self._get_profit_loss()
        self._get_collateral()

    def _get_name(self):
        options = self.options
        if len(options) == 1:
            if options[0].is_long:
                if options[0].is_call:
                    self.name = 'Long Call'
                else:
                    self.name = 'Long Put'
            else:
                if options[0].is_call:
                    self.name = 'Short Call'
                else:
                    self.name = 'Short Put'
        if len(options) == 2:
            if all([option.is_call for option in options]):
                if options[0].is_long and not options[1].is_long:
                    self.name = 'Long Call Spread'
                if not options[0].is_long and options[1].is_long:
                    self.name = 'Short Call Spread'
            elif all([not option.is_call for option in options]):
                if options[0].is_long and not options[1].is_long:
                    self.name = 'Short Put Spread'
                if not options[0].is_long and options[1].is_long:
                    self.name = 'Long Put Spread'
            else:
                if all([
                    not options[0].is_call,
                    options[0].is_long,
                    options[1].is_call,
                    not options[1].is_long,
                    options[1].strike > options[0].strike,
                ]):
                    self.name = 'Collar'
                elif all([
                    options[0].is_call,
                    options[0].is_long,
                    not options[1].is_call,
                    not options[1].is_long,
                    options[1].strike == options[0].strike,
                ]):
                    self.name = 'Long Combination'
                elif all([
                    not options[0].is_call,
                    not options[0].is_long,
                    options[1].is_call,
                    options[1].is_long,
                    options[1].strike == options[0].strike,
                ]):
                    self.name = 'Short Combination'
                else:
                    position = 'Long'
                    if not options[0].is_long and not options[1].is_long:
                        position = 'Short'
                    if options[0].strike == options[1].strike:
                        spread_type = 'Straddle'
                    else:
                        spread_type = 'Strangle'
                    self.name = f'{position} {spread_type}'
        if len(options) == 3:
            if all([option.is_call for option in options]):
                if all([
                    not options[0].is_long,
                    options[1].is_long,
                    options[2].is_long,
                    options[1].strike == options[2].strike,
                ]):
                    self.name = 'Call Back Spread'
                elif all([
                    options[0].is_long,
                    not options[1].is_long,
                    not options[2].is_long,
                    options[1].strike == options[2].strike,
                ]):
                    self.name = 'Call Front Spread'
            elif all([not option.is_call for option in options]):
                if all([
                    options[0].is_long,
                    options[1].is_long,
                    not options[2].is_long,
                    options[0].strike == options[1].strike
                ]):
                    self.name = 'Put Back Spread'
                elif all([
                    not options[0].is_long,
                    not options[1].is_long,
                    options[2].is_long,
                    options[0].strike == options[1].strike,
                ]):
                    self.name = 'Put Front Spread'
            else:
                if all([
                    not options[0].is_call,
                    options[1].is_call,
                    options[2].is_call,
                ]):
                    if all([
                        not options[0].is_long,
                        not options[1].is_long,
                        options[2].is_long,
                    ]):
                        if options[0].strike == options[1].strike:
                            self.name = 'Short Big Lizard'
                        else:
                            self.name = 'Short Jade Lizard'
                    elif all([
                        options[0].is_long,
                        options[1].is_long,
                        not options[2].is_long,
                    ]):
                        if options[0].strike == options[1].strike:
                            self.name = 'Long Big Lizard'
                        else:
                            self.name = 'Long Jade Lizard'
        if len(options) == 4:
            if options[1].strike - options[0].strike == options[3].strike - options[2].strike:
                if all([
                    not options[0].is_call,
                    not options[1].is_call,
                    options[2].is_call,
                    options[3].is_call,
                ]):
                    if options[1].strike == options[2].strike:
                        spread_type = 'Iron Butterfly'
                    else:
                        spread_type = 'Iron Condor'
                    if all([
                        options[0].is_long,
                        not options[1].is_long,
                        not options[2].is_long,
                        options[3].is_long,
                    ]):
                        self.name = f'Short {spread_type}'
                    elif all([
                        not options[0].is_long,
                        options[1].is_long,
                        options[2].is_long,
                        not options[3].is_long,
                    ]):
                        self.name = f'Long {spread_type}'
                elif all([option.is_call for option in options]):
                    if all([
                        options[0].is_long,
                        not options[1].is_long,
                        not options[2].is_long,
                        options[3].is_long,
                    ]):
                        if options[1].strike == options[2].strike:
                            self.name = f'Long Call Butterfly'
                        else:
                            self.name = 'Long Call Condor'
                    elif all([
                        not options[0].is_long,
                        options[1].is_long,
                        options[2].is_long,
                        not options[3].is_long,
                    ]):
                        if options[1].strike == options[2].strike:
                            self.name = 'Short Call Butterfly'
                        else:
                            self.name = 'Short Call Condor'
                elif all([not option.is_call for option in options]):
                    if all([
                        options[0].is_long,
                        not options[1].is_long,
                        not options[2].is_long,
                        options[3].is_long,
                    ]):
                        if options[1].strike == options[2].strike:
                            self.name = f'Long Put Butterfly'
                        else:
                            self.name = 'Long Put Condor'
                    elif all([
                        not options[0].is_long,
                        options[1].is_long,
                        options[2].is_long,
                        not options[3].is_long,
                    ]):
                        if options[1].strike == options[2].strike:
                            self.name = 'Short Put Butterfly'
                        else:
                            self.name = 'Short Put Condor'

    def _get_profit_loss(self):
        price_points = [min(self.options[0].strike - 1, 0), *[option.strike for option in self.options], self.options[-1].strike + 1]
        profit_losses = []
        for price_point in price_points:
            price_point_profit = 0.0
            for option in self.options:
                price_point_profit += option.get_profit_at(price_point)
            profit_losses.append(round(price_point_profit, 2))
        max_profit_loss = max(profit_losses)
        min_profit_loss = min(profit_losses)
        if max_profit_loss == profit_losses[-1] and profit_losses[-1] > profit_losses[-2]:
            self.max_profit = float('inf')
        elif max_profit_loss == profit_losses[0] and profit_losses[0] > profit_losses[1]:
            self.max_profit = self.options[0].strike * 100
        else:
            self.max_profit = max_profit_loss
        if min_profit_loss == profit_losses[-1] and profit_losses[-1] < profit_losses[-2]:
            self.max_loss = float('inf')
        elif min_profit_loss == profit_losses[0] and profit_losses[0] < profit_losses[1]:
            self.max_loss = self.options[0].strike * 100
        else:
            self.max_loss = abs(min_profit_loss)

    def _get_collateral(self):
        puts_collateral = 0.0
        calls_collateral = 0.0
        for option in self.options:
            if option.is_call:
                calls_collateral += option.get_collateral() if option.is_long else -option.get_collateral()
            else:
                puts_collateral += option.get_collateral() if option.is_long else -option.get_collateral()
        self.collateral = max([abs(calls_collateral), abs(puts_collateral)])

    @property
    def max_return_on_collateral_percent(self):
        return round(self.max_profit / self.collateral * 100, 2)

    def __repr__(self):
        return f'<Strategy "{self.name}">'

    def report(self):
        max_profit = self.max_profit
        if max_profit == float('inf'):
            max_profit = 'inf'
        max_loss = self.max_loss
        if max_loss == float('inf'):
            max_loss = 'inf'
        return {
            'name': self.name,
            'max_profit': max_profit,
            'max_loss': max_loss,
            'collateral': self.collateral,
            'options': [
                option.report() for option in self.options
            ]
        }


class Trade:
    def __init__(self, ticker: str, expiration_date: date, account: 'Account'):
        self.trade_events: List['TradeEvent'] = []
        # self.strategies: List['Strategy'] = []
        self.ticker: str = ticker
        self.expiration_date: date = expiration_date
        self.account = account
        self.exercise_profit = 0.0
        self.underlying_price_at_expiration = None
        self.event_data = None

    def __repr__(self):
        return f'<Trade {self.ticker} Expiring {str(self.expiration_date)}>'

    def report(self):
        stats = {}
        if self.is_closed:
            stats = {
                'win': self.is_win,
                'net_profit': self.net_profit,
                'exercise_profit': self.exercise_profit,
                'premium_profit': self.premium_profit,
                'premium_profit_by_trade_event': self.premium_profit_by_event,
                'weighted_return_on_collateral_percent': self.weighted_return_on_collateral,
                'return_on_collateral_by_event': self.return_on_collateral_by_event,
                'duration': str(self.duration),
            }
        return {
            'ticker': self.ticker,
            'expiration_date': self.expiration_date.strftime('%Y-%m-%d'),
            'underlying_price_at_expiration': self.underlying_price_at_expiration,
            **stats,
            'trade_events': [
                event.report() for event in self.trade_events
            ],
        }

    def resolve_events(self):
        open_options = get_open_options(self.options)
        if open_options:
            if self.event_data is None:
                self.event_data = ticker_event_cache.get(self.ticker)

            option_ids = [option.id for option in open_options]
            for event in self.event_data:
                if event['option'] not in option_ids or event['state'] != 'confirmed' or event['type'] not in ('assignment', 'exercise'):
                    continue
                option = next((option for option in open_options if option.id == event['option']), None)
                event_time = utc_to_eastern(event['created_at'])
                for equity_component in event['equity_components']:
                    price = float(equity_component['price'])
                    is_long = True if equity_component['side'] == 'buy' else False
                    quantity = int(float(equity_component['quantity']))
                    self.account.add_shares([
                        Share(self.ticker, open_price=price, open_time=event_time, is_long=is_long) for share in range(quantity)
                    ])
                    self.exercise_profit += price * quantity * (-1 if is_long else 1)
                self.add_event(
                    TradeEvent(
                        ticker=self.ticker,
                        expiration_date=self.expiration_date,
                        execution_time=event_time,
                        options=[
                            Option(
                                id_=option.id,
                                ticker=self.ticker,
                                expiration_date=self.expiration_date,
                                strike=option.strike,
                                is_call=option.is_call,
                                is_long=not option.is_long,
                                price=0.0,
                            )
                        ],
                        end_time=event_time,
                    )
                )

    def resolve_expired_options(self):
        if not self.is_expired:
            return
        open_options = get_open_options(self.options)
        execution_time = datetime(year=self.expiration_date.year, month=self.expiration_date.month, day=self.expiration_date.day, hour=16, minute=0, second=0, microsecond=0, tzinfo=pytz.timezone('US/Eastern'))
        closing_price = closing_price_cache.get((self.ticker, self.expiration_date))
        self.underlying_price_at_expiration = round(closing_price, 2)
        if self.is_expired and open_options:
            closing_options = []
            for option in open_options:
                closing_options.append(
                    Option(
                        id_=option.id,
                        ticker=self.ticker,
                        expiration_date=self.expiration_date,
                        strike=option.strike,
                        is_call=option.is_call,
                        is_long=not option.is_long,
                        price=0.0,
                    )
                )
            self.add_event(
                TradeEvent(
                    ticker=self.ticker,
                    expiration_date=self.expiration_date,
                    execution_time=execution_time,
                    options=closing_options,
                    end_time=execution_time,
                )
            )

    @property
    def strategies(self) -> List['Strategy']:
        return [
            event.strategy for event in self.trade_events
        ]

    @property
    def options(self) -> List['Option']:
        ops = []
        for event in self.trade_events:
            ops.extend(event.options)
        return ops

    @property
    def is_closed(self) -> bool:
        if self.is_expired or not get_open_options(self.options):
            return True
        return False

    @property
    def is_expired(self) -> bool:
        closing_time = datetime(year=self.expiration_date.year, month=self.expiration_date.month, day=self.expiration_date.day, hour=16, minute=0, second=0, tzinfo=pytz.timezone('US/Eastern'))
        if datetime.now(pytz.timezone('US/Eastern')) > closing_time:
            return True
        return False

    @property
    def net_profit(self) -> float:
        profit = self.premium_profit
        profit += self.exercise_profit
        return round(profit, 2)

    @property
    def premium_profit(self) -> float:
        if not self.is_closed:
            raise ValueError('Cannot get profit of unclosed trade')
        profit = 0.0
        for option in self.options:
            profit += -option.price if option.is_long else option.price
        profit *= 100
        return round(profit, 2)

    @property
    def premium_profit_by_event(self) -> dict:
        if not self.is_closed:
            raise ValueError('Cannot get profit of unclosed trade')
        options = []
        strategy_profits = {}
        for event in self.trade_events:
            # strategy_profits.setdefault(f'{strategy.name} at {strategy.trade_event.execution_time}', 0.0)
            profit = 0.0
            options.extend(event.options)
            open_options = get_open_options(options)
            closed_options = [option for option in options if option not in open_options]
            for option in closed_options:
                profit += -option.price if option.is_long else option.price
                options.remove(option)
            profit *= 100
            strategy_profits[f'{event.strategy.name} at {event.execution_time}'] = round(profit, 2)
        return strategy_profits

    @property
    def return_on_collateral_by_event(self) -> dict:
        if not self.is_closed:
            raise ValueError('Cannot get RoC of unclosed trade')
        event_profits = list(self.premium_profit_by_event.values())
        event_rocs = {}
        for index, event in enumerate(self.trade_events):
            try:
                roc = event_profits[index + 1] / event.strategy.collateral * 100
            except (IndexError, ZeroDivisionError):
                roc = 0.0
            event_rocs[f'{event.strategy.name} at {event.execution_time}'] = round(roc, 2)
        return event_rocs

    @property
    def weighted_return_on_collateral(self):
        if not self.is_closed:
            raise ValueError('Cannot get RoC of unclosed trade')
        event_rocs = self.return_on_collateral_by_event
        rocs = []
        for event in self.trade_events:
            if event.strategy.collateral == 0.0 or event.execution_time == event.end_time:
                continue
            roc = event_rocs[f'{event.strategy.name} at {event.execution_time}']
            roc *= event.duration / self.duration
            rocs.append(roc)
        average_roc = sum(rocs) / len(rocs)
        return round(average_roc, 2)

    @property
    def is_win(self) -> bool:
        if self.net_profit >= 0:
            return True
        return False

    @property
    def duration(self) -> timedelta:
        if not self.is_closed:
            raise ValueError('Cannot get duration of unclosed trade')
        first_event = self.trade_events[0]
        last_event = self.trade_events[-1]
        return last_event.execution_time - first_event.execution_time

    def add_event(self, trade_event: 'TradeEvent'):
        existing_event = False
        for event in self.trade_events:
            if event.ticker == trade_event.ticker and event.execution_time == trade_event.execution_time:
                event.options.extend(trade_event.options)
                existing_event = True
                break
        if not existing_event:
            trade_event.trade = self
            self.trade_events.append(trade_event)
            self.trade_events.sort(key=lambda event: event.execution_time)
        # trade_event.determine_strategy()
        options = []
        # self.strategies = []
        previous_event = None
        for event in self.trade_events:
            options.extend(event.options)
            event.strategy = Strategy(event, get_open_options(options))
            if previous_event:
                previous_event.end_time = event.execution_time
            if event.strategy.name == 'Close Position':
                event.end_time = event.execution_time
            previous_event = event


class TradeEvent:
    def __init__(
            self,
            execution_time: datetime,
            ticker: str,
            expiration_date: date,
            options: List['Option'],
            end_time: datetime = None,
    ):
        self.execution_time = execution_time
        self.ticker = ticker.upper()
        self.expiration_date = expiration_date
        self.options = options
        self.options = sort_options(self.options)
        self.end_time = end_time
        self.strategy = None
        self.trade = None

    def report(self):
        return {
            'execution_time': self.execution_time.isoformat(),
            'end_time': self.end_time.isoformat() if self.end_time else self.end_time,
            'strategy': self.strategy.report(),
            'options': [
                option.report() for option in self.options
            ]
        }

    @property
    def duration(self) -> timedelta:
        if self.end_time is None:
            raise ValueError('Event has not ended')
        return self.end_time - self.execution_time


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    with InstrumentCache() as instrument_cache:
        with ClosingPriceCache() as closing_price_cache:
            with TickerEventCache() as ticker_event_cache:
                account = Account()
                get_robinhood_data()
                # parse_raw_data()
                # process_trade_events_data()
                account.report()
