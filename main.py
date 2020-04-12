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


def get_strategy(options: List['Option']):
    if not options:
        return 'Close Position'
    options.sort(key=lambda option: option.strike)
    options.sort(key=lambda option: option.is_call)
    if len(options) == 1:
        position = 'Long' if options[0].is_long else 'Short'
        option_type = 'Call' if options[0].is_call else 'Put'
        return f'{position} {option_type}'
    if len(options) == 2:
        position = '2-Option'
        spread_type = 'Strategy'
        if all([option.is_call for option in options]):
            spread_type = 'Call Spread'
            if options[0].is_long and not options[1].is_long:
                position = 'Long'
            if not options[0].is_long and options[1].is_long:
                position = 'Short'
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
        return sum(trade.profit for trade in self.trades.values())

    @property
    def win_percent(self):
        wins = [True for trade in self.trades.values() if trade.is_win]
        return len(wins) / len(self.trades.values()) * 100

    @property
    def average_profit(self):
        return self.profit / len(self.trades.values())

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
        return f'<Trade {self.ticker} Expiring {str(self.expiration_date)}\nStrategies: {strategies}\nProfit: ${round(self.profit, 2)}\nWin: {self.is_win}>'

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
        return total_profit * 100

    @property
    def is_win(self) -> bool:
        if self.profit >= 0:
            return True
        return False

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
            self.strategies.append((get_strategy(get_open_options(options)), event.time))
        # self.strategies = [
        #     (get_strategy(), event.time)
        #     for event in self.events
        # ]


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
print(f'{round(account.profit, 2)=}')
print(f'{round(account.win_percent, 2)=}')
print(f'{round(account.average_profit, 2)=}')
print(f'{str(account.average_duration)=}')
print(f'{account.trades.values()=}')



