#!/usr/bin/env python3
import json
import os
from datetime import date, datetime, timedelta
from typing import List

from string_conversions import Case, convert_case, str_dt


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


def get_strategy(options: List['Option']) -> 'Strategy':
    if not options:
        return Strategy(
            'Close Position',
            '',
            0.0,
            0.0,
            0.0,
        )
    options.sort(key=lambda option: option.strike)
    options.sort(key=lambda option: option.is_call)
    if len(options) == 1:
        if options[0].is_long:
            position = 'Long'
            if options[0].is_call:
                return Strategy(
                    'Call',
                    position,
                    options[0].price * 100,
                    float('inf'),
                    options[0].price * 100,
                )
            else:
                return Strategy(
                    'Put',
                    position,
                    options[0].price * 100,
                    options[0].strike * 100,
                    options[0].price * 100,
                )
        else:
            position = 'Short'
            if options[0].is_call:
                return Strategy(
                    'Call',
                    position,
                    float('inf'),
                    options[0].price * 100,
                    float('inf'),
                )
            else:
                return Strategy(
                    'Put',
                    position,
                    options[0].strike * 100,
                    options[0].price * 100,
                    (options[0].strike * 100) - (options[0].price * 100)
                )
    if len(options) == 2:
        if all([option.is_call for option in options]):
            spread_type = 'Call Spread'
            if options[0].is_long and not options[1].is_long:
                return Strategy(
                    'Call Spread',
                    'Long',
                    options[1].strike * 100 - options[0].strike * 100,
                    (options[1].strike * 100 - options[0].strike * 100) - (options[0].price * 100 - options[1].price * 100),
                    (options[0].price * 100 - options[1].price * 100),
                )
            if not options[0].is_long and options[1].is_long:
                return Strategy(
                    'Call Spread',
                    'Short',
                    options[1].strike * 100 - options[0].strike * 100,
                    options[0].price * 100 - options[1].price * 100,
                    (options[1].strike * 100 - options[0].strike * 100) - (options[0].price * 100 - options[1].price * 100)
                )
        elif all([not option.is_call for option in options]):
            spread_type = 'Put Spread'
            if options[0].is_long and not options[1].is_long:
                position = 'Short'
            if not options[0].is_long and options[1].is_long:
                position = 'Long'
        else:
            if options[0].is_long and options[1].is_long:
                position = 'Long'
            elif not options[0].is_long and not options[1].is_long:
                position = 'Short'
            if options[0].strike == options[1].strike:
                spread_type = 'Straddle'
            else:
                spread_type = 'Strangle'
        return f'{position} {spread_type}'
    if len(options) == 3:
        return '3-Option Strategy'
    if len(options) == 4:
        if options[1].strike - options[0].strike == options[3].strike - options[2].strike:
            if not options[0].is_call and not options[1].is_call and options[2].is_call and options[3].is_call:
                if options[1].strike == options[2].strike:
                    spread_type = 'Iron Butterfly'
                elif options[2].strike - options[0].strike == options[3].strike - options[1].strike:
                    spread_type = 'Iron Condor'
                else:
                    return '4-Option Strategy'
                if options[0].is_long and not options[1].is_long and not options[2].is_long and options[3].is_long:
                    return f'Short {spread_type}'
                if not options[0].is_long and options[1].is_long and options[2].is_long and not options[3].is_long:
                    return f'Long {spread_type}'

        return '4-Option Strategy'


class Account:
    def __init__(self):
        self.trades = {}

    def execute_trade_event(self, trade_event: 'TradeEvent'):
        trade = self.trades.get((trade_event.ticker, trade_event.expiration_date))
        if trade is None:
            trade = Trade(trade_event.ticker, trade_event.expiration_date)
            self.trades[(trade_event.ticker, trade_event.expiration_date)] = trade
        trade.add_event(trade_event)

    @property
    def profit(self):
        return round(sum(trade.profit for trade in self.trades.values()), 2)

    @property
    def win_percent(self):
        wins = [True for trade in self.trades.values() if trade.is_win]
        return round(len(wins) / len(self.trades.values()) * 100, 2)

    @property
    def average_profit(self):
        return round(self.profit / len(self.trades.values()), 2)

    @property
    def average_duration(self):
        total_duration = sum([trade.duration for trade in self.trades.values()], start=timedelta(0))
        return total_duration / len(self.trades.values())


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
            options: List['Option']
    ):
        self.name = 'Unknown Strategy'
        self.max_profit = float('nan')
        self.max_loss = float('nan')
        self.collateral = 0.0

        if not options:
            self.name = 'Close Position'
            self.max_loss = 0.0
            self.max_profit = 0.0
            return
        options.sort(key=lambda option: option.strike)
        options.sort(key=lambda option: option.is_call)
        self._get_profit_loss(options)
        self._get_collateral(options)
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
                spread_type = 'Put Spread'
                if options[0].is_long and not options[1].is_long:
                    self.name = 'Put Credit Spread'
                if not options[0].is_long and options[1].is_long:
                    self.name = 'Put Debit Spread'
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
            self.name = '3-Option Strategy'
        if len(options) == 4:
            if options[1].strike - options[0].strike == options[3].strike - options[2].strike:
                if not options[0].is_call and not options[1].is_call and options[2].is_call and options[3].is_call:
                    if options[1].strike == options[2].strike:
                        spread_type = 'Iron Butterfly'
                    elif options[2].strike - options[0].strike == options[3].strike - options[1].strike:
                        spread_type = 'Iron Condor'
                    else:
                        self.name = '4-Option Strategy'
                    if options[0].is_long and not options[1].is_long and not options[2].is_long and options[3].is_long:
                        self.name = f'Short {spread_type}'
                    if not options[0].is_long and options[1].is_long and options[2].is_long and not options[3].is_long:
                        self.name = f'Long {spread_type}'

    def _get_profit_loss(self, sorted_options: List['Option']):
        price_points = [min(sorted_options[0].strike - 1, 0), *[option.strike for option in sorted_options], sorted_options[-1].strike + 1]
        profit_losses = []
        for price_point in price_points:
            price_point_profit = 0.0
            for option in sorted_options:
                price_point_profit += option.get_profit_at(price_point)
            profit_losses.append(round(price_point_profit, 2))
        max_profit_loss = max(profit_losses)
        min_profit_loss = min(profit_losses)
        if any([
            max_profit_loss == profit_losses[-1] and profit_losses[-1] > profit_losses[-2],
            max_profit_loss == profit_losses[0] and profit_losses[0] > profit_losses[1],
        ]):
            self.max_profit = float('inf')
        else:
            self.max_profit = max_profit_loss
        if any([
            min_profit_loss == profit_losses[-1] and profit_losses[-1] < profit_losses[-2],
            min_profit_loss == profit_losses[0] and profit_losses[0] < profit_losses[1],
        ]):
            self.max_loss = float('-inf')
        else:
            self.max_loss = min_profit_loss

    def _get_collateral(self, sorted_options: List['Option']):
        puts_collateral = 0.0
        calls_collateral = 0.0
        for option in sorted_options:
            if option.is_call:
                calls_collateral += option.get_collateral() if option.is_long else -option.get_collateral()
            else:
                puts_collateral += option.get_collateral() if option.is_long else -option.get_collateral()
        self.collateral = max([abs(calls_collateral), abs(puts_collateral)])

    def __repr__(self):
        stakes = ''
        if self.max_profit > 0.0:
            stakes = f' with max profit of ${self.max_profit} and max loss of ${abs(self.max_loss)}'
        collateral = ''
        if self.collateral > 0.0:
            collateral = f' requiring a collateral of ${self.collateral}'
        return f'<Strategy "{self.name}"{stakes}{collateral}'


class Trade:
    def __init__(self, ticker: str, expiration_date: date):
        self.events = []
        self.strategies = []
        self.ticker = ticker
        self.expiration_date = expiration_date

    # TODO
    def __repr__(self):
        strategies = [
            f'{strategy[0]} @ {strategy[1]}' for strategy in self.strategies
        ]
        return f'<Trade {self.ticker} Expiring {str(self.expiration_date)}\nStrategies: {strategies}\nProfit: ${round(self.profit, 2)}\nWin: {self.is_win}\nReturn on Collateral: {self.return_on_collateral_percent}%>'

    @property
    def options(self) -> List['Option']:
        ops = []
        for event in self.events:
            ops.extend(event.options)
        return ops

    @property
    def is_closed(self) -> bool:
        if date.today() > self.expiration_date:
            return True
        if get_open_options(self.options):
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
        for index, strategy in enumerate(self.strategies):
            try:
                close_time = self.strategies[index + 1][1]
            except IndexError:
                break
            collaterals.append(self.strategies[index][0].collateral * ((close_time - self.strategies[index][1]) / self.duration))
        average_collateral = sum(collaterals) / len(collaterals)
        return round((self.profit / average_collateral) * 100, 2)

    @property
    def duration(self) -> timedelta:
        if not self.is_closed:
            raise ValueError('Cannot get duration of unclosed trade')
        first_event = self.events[0]
        last_event = self.events[-1]
        return last_event.time - first_event.time

    def add_event(self, trade_event: 'TradeEvent'):
        self.events.append(trade_event)
        self.events.sort(key=lambda event: event.time)
        options = []
        self.strategies = []
        for event in self.events:
            options.extend(event.options)
            self.strategies.append((Strategy(get_open_options(options)), event.time))


class TradeEvent:
    def __init__(
            self,
            time: str,
            ticker: str,
            expiration_date: str,
            options,
    ):
        self.time = str_dt(time)
        self.ticker = ticker.upper()
        self.expiration_date = str_dt(expiration_date, '%Y-%m-%d').date()
        self.options = [
            Option(
                ticker=self.ticker,
                expiration_date=self.expiration_date,
                **{
                    convert_case(key, Case.CAMEL, Case.SNAKE): value
                    for key, value in option_data.items()
                }
            ) for option_data in options
        ]


account = Account()

with open(os.path.join('data', 'trade_events.json')) as data_file:
    events_data = json.load(data_file)

for trade_event_data in events_data:
    trade_event = TradeEvent(
        **{
            convert_case(key, Case.CAMEL, Case.SNAKE): value
            for key, value in trade_event_data.items()
        }
    )
    account.execute_trade_event(trade_event)


print(f'{len(account.trades)=}')
print(f'{account.profit=}')
print(f'{account.win_percent=}')
print(f'{round(account.average_profit, 2)=}')
print(f'{str(account.average_duration)=}')
print(f'{account.trades.values()=}')



