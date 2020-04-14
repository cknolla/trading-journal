#!/usr/bin/env python3
import json
import os
import re
from datetime import date, datetime, timedelta
from typing import List

from robinhood_trade_event_parser import parse_robinhood_file
from string_conversions import Case, convert_case, str_dt, convert_keys


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


class Account:
    def __init__(self):
        self.trades = {}

    def execute_trade_event(self, trade_event: 'TradeEvent'):
        trade = self.trades.get((trade_event.ticker, trade_event.expiration_date))
        if trade is None:
            trade = Trade(trade_event.ticker, trade_event.expiration_date)
            self.trades[(trade_event.ticker, trade_event.expiration_date)] = trade
        trade.add_event(trade_event)

    def report(self):
        all_trades = list(self.trades.values())
        all_trades.sort(key=lambda trade: trade.expiration_date, reverse=True)
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
        with open(os.path.join('reports', datetime.now().isoformat() + '.json'), 'w') as output_file:
            json.dump(convert_keys(stats, Case.SNAKE, Case.CAMEL), output_file, indent=2)

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
            options: List['Option'],
            start_time: datetime,
    ):
        self.name = 'Unknown Strategy'
        self.max_profit = float('nan')
        self.max_loss = float('nan')
        self.collateral = 0.0
        self.start_time = start_time
        self.options = options

        if not options:
            self.name = 'Close Position'
            self.max_loss = 0.0
            self.max_profit = 0.0
            return
        options.sort(key=lambda option: option.strike)
        options.sort(key=lambda option: option.is_call)
        self.options = options
        self._get_profit_loss()
        self._get_collateral()
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
            self.name = '3-Option Strategy'
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
                # elif all([
                #     options[0].is_call,
                #     not options[1].is_call,
                #     options[2].is_call,
                # ]):
                #     if all([
                #         not options[0].is_long,
                #         not options[1].is_long,
                #         options[2].is_long,
                #     ]):
                #         self.name = 'Short Big Lizard'
                #     elif all([
                #         options[0].is_long,
                #         options[1].is_long,
                #         not options[2].is_long,
                #     ]):
                #         self.name = 'Long Big Lizard'
        if len(options) == 4:
            self.name = '4-Option Strategy'
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
        if any([
            max_profit_loss == profit_losses[-1] and profit_losses[-1] > profit_losses[-2],
            max_profit_loss == profit_losses[0] and profit_losses[0] > profit_losses[1],
        ]):
            self.max_profit = float('inf')
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
            'start_time': self.start_time.isoformat(),
            'max_profit': max_profit,
            'max_loss': max_loss,
            'collateral': self.collateral,
            'options': [
                option.report() for option in self.options
            ]
        }


class Trade:
    def __init__(self, ticker: str, expiration_date: date):
        self.events: List['TradeEvent'] = []
        self.strategies: List['Strategy'] = []
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
            'strategies': [
                strategy.report() for strategy in self.strategies
            ],
            **stats,
        }

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
            return False
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
                close_time = self.strategies[index + 1].start_time
            except IndexError:
                break
            collaterals.append(self.strategies[index].collateral * ((close_time - self.strategies[index].start_time) / self.duration))
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
        existing_event = False
        for event in self.events:
            if event.ticker == trade_event.ticker and event.time == trade_event.time:
                event.options.extend(trade_event.options)
                existing_event = True
                break
        if not existing_event:
            self.events.append(trade_event)
            self.events.sort(key=lambda event: event.time)
        options = []
        self.strategies = []
        for event in self.events:
            options.extend(event.options)
            self.strategies.append(Strategy(get_open_options(options), event.time))


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
        self.options = []
        for option_data in options:
            for count in range(option_data['quantity']):
                self.options.append(
                    Option(
                        ticker=self.ticker,
                        expiration_date=self.expiration_date,
                        **{
                            convert_case(key, Case.CAMEL, Case.SNAKE): value
                            for key, value in option_data.items()
                        }
                    )
                )


account = Account()

# parse all raw data into ingestible json files
for root, dirs, filenames in os.walk('raw_data'):
    for filename in filenames:
        if re.search(r'\.txt$', filename, re.IGNORECASE):
            parse_robinhood_file(os.path.join(root, filename))

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

account.report()
# report statistics
# print(f'{len(account.trades)=}')
# print(f'{account.profit=}')
# print(f'{account.win_percent=}')
# print(f'{account.average_profit=}')
# print(f'{str(account.average_trade_duration)=}')
# print(f'{account.trades.values()=}')



