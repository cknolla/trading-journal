#!/usr/bin/env python3
import json
import os
import re
from datetime import date, datetime, timedelta
from typing import List

import robin_stocks
import yfinance
from dotenv import load_dotenv

from robinhood_trade_event_parser import parse_robinhood_file
from string_conversions import Case, convert_case, str_dt, convert_keys

load_dotenv('.env')


def create_report(report: dict):
    with open(os.path.join('reports', datetime.now().isoformat() + '.json'), 'w') as output_file:
        json.dump(convert_keys(report, Case.SNAKE, Case.CAMEL), output_file, indent=2)


def parse_raw_data():
    # parse all raw data into ingestible json files
    for root, dirs, filenames in os.walk('raw_data'):
        for filename in filenames:
            if re.search(r'\.txt$', filename, re.IGNORECASE):
                parse_robinhood_file(os.path.join(root, filename))


def process_trade_events_data():
    # process all json files in trade events folder
    for root, dirs, filenames in os.walk('trade_events_data'):
        for filename in filenames:
            if re.search(r'\.json$', filename, re.IGNORECASE):
                with open(os.path.join(root, filename)) as data_file:
                    events_data = json.load(data_file)
                    for trade_event_data in events_data:
                        trade_event = TradeEvent(
                            **{
                                convert_case(key, Case.CAMEL, Case.SNAKE): value
                                for key, value in trade_event_data.items()
                            }
                        )
                        account.execute_trade_event(trade_event)


def get_robinhood_data():
    login = robin_stocks.login(username=os.getenv('USERNAME'), password=os.getenv('PASSWORD'))
    all_option_orders = robin_stocks.orders.get_all_option_orders()
    for order in all_option_orders:
        if order['state'] == 'filled':
            for leg in order['legs']:
                instrument_data = robin_stocks.helper.request_get(leg['option'])
                expiration_date = str_dt(instrument_data['expiration_date'], '%Y-%m-%d').date()
                option_prices = []
                for execution in leg['executions']:
                    option_prices.extend([float(execution['price']) for quantity in range(int(float(execution['quantity'])))])
                account.execute_trade_event(
                    TradeEvent(
                        ticker=order['chain_symbol'],
                        expiration_date=expiration_date,
                        execution_time=str_dt(order['created_at'][:-8]),
                        options=[
                            Option(
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


def sort_options(options: List['Option']) -> List['Option']:
    sorted_options = sorted(options, key=lambda option: option.strike)
    sorted_options.sort(key=lambda option: option.is_call)
    return sorted_options


class Account:
    def __init__(self):
        self.trades = {}
        self.shares = []

    def execute_trade_event(self, trade_event: 'TradeEvent'):
        trade = self.trades.get((trade_event.ticker, trade_event.expiration_date))
        if trade is None:
            trade = Trade(trade_event.ticker, trade_event.expiration_date)
            self.trades[(trade_event.ticker, trade_event.expiration_date)] = trade
        trade.add_event(trade_event)

    def report(self):
        all_trades = list(self.trades.values())
        all_trades.sort(key=lambda trade: trade.expiration_date, reverse=True)
        for trade in all_trades:
            trade.resolve_expired_options()
        closed_trades = list(filter(lambda trade: trade.is_closed, all_trades))
        open_trades = [trade for trade in all_trades if trade not in closed_trades]
        stats = {
            'total_profit': self.get_profit(closed_trades),
            'average_profit': self.get_average_profit(closed_trades),
            'win_percent': self.get_win_percent(closed_trades),
            'average_trade_duration': str(self.get_average_trade_duration(closed_trades)),
            'closed_trades': [trade.report() for trade in closed_trades],
            'open_trades': [trade.report() for trade in open_trades],
        }
        create_report(stats)

    def get_profit(self, trades=None) -> float:
        if trades is None:
            trades = self.trades.values()
        return round(sum(trade.profit for trade in trades), 2)

    def get_average_profit(self, trades=None) -> float:
        if trades is None:
            trades = self.trades.values()
        return round(self.get_profit(trades) / len(trades), 2)

    def get_win_percent(self, trades=None) -> float:
        if trades is None:
            trades = self.trades.values()
        wins = [True for trade in trades if trade.is_win]
        return round(len(wins) / len(trades) * 100, 2)

    def get_average_trade_duration(self, trades=None) -> timedelta:
        if trades is None:
            trades = self.trades.values()
        total_duration = sum([trade.duration for trade in trades], start=timedelta(0))
        return total_duration / len(trades)


class Option:
    def __init__(
            self,
            ticker: str,
            strike: float,
            price: float,
            is_call: bool,
            is_long: bool,
            expiration_date: date,
            **kwargs
    ):
        self.ticker = ticker.upper()
        self.strike = strike
        self.price = price
        self.is_call = is_call
        self.is_long = is_long
        self.expiration_date = expiration_date

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
                    self.name = 'Call Debit Spread'
                if not options[0].is_long and options[1].is_long:
                    self.name = 'Call Credit Spread'
            elif all([not option.is_call for option in options]):
                if options[0].is_long and not options[1].is_long:
                    self.name = 'Put Credit Spread'
                if not options[0].is_long and options[1].is_long:
                    self.name = 'Put Debit Spread'
            else:
                if all([
                    not options[0].is_call,
                    options[0].is_long,
                    options[1].is_call,
                    not options[1].is_long,
                    options[1].strike > options[0].strike,
                ]):
                    self.name = 'Protective Collar'
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
        if max_loss == float('-inf'):
            max_loss = '-inf'
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
    def __init__(self, ticker: str, expiration_date: date):
        self.trade_events: List['TradeEvent'] = []
        # self.strategies: List['Strategy'] = []
        self.ticker: str = ticker
        self.expiration_date: date = expiration_date

    def __repr__(self):
        return f'<Trade {self.ticker} Expiring {str(self.expiration_date)}>'

    def report(self):
        stats = {}
        if self.is_closed:
            stats = {
                'profit': self.profit,
                'win': self.is_win,
                'return_on_collateral_percent': self.return_on_collateral_percent,
                'duration': str(self.duration),
            }
        return {
            'ticker': self.ticker,
            'expiration_date': self.expiration_date.strftime('%Y-%m-%d'),
            'trade_events': [
                event.report() for event in self.trade_events
            ],
            **stats,
        }

    def resolve_expired_options(self):
        # if datetime.now() > datetime(year=self.expiration_date.year, month=self.expiration_date.month, day=self.expiration_date.day, hour=16, minute=0) and get_open_options(self.options):
        open_options = get_open_options(self.options)
        if date.today() > self.expiration_date and open_options:
            next_day = self.expiration_date + timedelta(days=1)
            closing_price = yfinance.download(self.ticker, start=self.expiration_date.isoformat(), end=next_day.isoformat())['Close'][self.expiration_date.isoformat()]
            print(f'{self.ticker=} {closing_price=}')
            closing_options = []
            for option in open_options:
                price = 0.0
                if option.is_call and option.strike < closing_price:
                    price = round(closing_price - option.strike, 2)
                elif not option.is_call and option.strike > closing_price:
                    price = round(option.strike - closing_price, 2)
                closing_options.append(
                    Option(
                        ticker=self.ticker,
                        expiration_date=self.expiration_date,
                        strike=option.strike,
                        is_call=option.is_call,
                        is_long=not option.is_long,
                        price=price,
                    )
                )
            self.add_event(
                TradeEvent(
                    ticker=self.ticker,
                    expiration_date=self.expiration_date,
                    execution_time=datetime(year=self.expiration_date.year, month=self.expiration_date.month, day=self.expiration_date.day, hour=16, minute=0, second=0),
                    options=closing_options,
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
        if date.today() > self.expiration_date:
            return True
        if not get_open_options(self.options):
            return True
        return False

    @property
    def profit(self) -> float:
        if not self.is_closed:
            raise ValueError('Cannot get profit of unclosed trade')
        total_profit = 0.0
        for option in self.options:
            total_profit += -option.price if option.is_long else option.price
        return round(total_profit * 100, 2)

    @property
    def is_win(self) -> bool:
        if self.profit >= 0:
            return True
        return False

    @property
    def return_on_collateral_percent(self) -> float:
        if not self.is_closed:
            raise ValueError('Cannot get profit of unclosed trade')
        collaterals = []
        for index, event in enumerate(self.trade_events):
            try:
                close_time = self.trade_events[index + 1].execution_time
            except IndexError:
                break
            collaterals.append(event.strategy.collateral * ((close_time - event.strategy.trade_event.execution_time) / self.duration))
        average_collateral = sum(collaterals) / len(collaterals)
        return round((self.profit / average_collateral) * 100, 2)

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
        for event in self.trade_events:
            options.extend(event.options)
            event.strategy = Strategy(event, get_open_options(options))
            # self.strategies.append(Strategy(get_open_options(options), event.time))


class TradeEvent:
    def __init__(
            self,
            execution_time: datetime,
            ticker: str,
            expiration_date: date,
            options,
    ):
        self.execution_time = execution_time
        self.ticker = ticker.upper()
        self.expiration_date = expiration_date
        self.options = options
        # for option_data in options:
        #     for count in range(option_data['quantity']):
        #         self.options.append(
        #             Option(
        #                 ticker=self.ticker,
        #                 expiration_date=self.expiration_date,
        #                 **{
        #                     convert_case(key, Case.CAMEL, Case.SNAKE): value
        #                     for key, value in option_data.items()
        #                 }
        #             )
        #         )
        self.options = sort_options(self.options)
        self.strategy = None
        self.trade = None

    def report(self):
        return {
            'execution_time': self.execution_time.isoformat(),
            'strategy': self.strategy.report(),
            'options': [
                option.report() for option in self.options
            ]
        }


if __name__ == '__main__':
    account = Account()
    get_robinhood_data()
    # parse_raw_data()
    # process_trade_events_data()
    account.report()
