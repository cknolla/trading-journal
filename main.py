#!/usr/bin/env python3
import json
import os
from datetime import date, datetime, timedelta
from typing import List

from string_conversions import Case, convert_case, str_dt


class Account:
    def __init__(self):
        self.value = 0.0
        self.options: List['Option'] = []
        self.trades: List['Trade'] = []

    def withdraw(self, amount: float):
        self.value -= amount

    def deposit(self, amount: float):
        self.value += amount

    def open_trade(self, option: 'Option', open_time: datetime):
        trade = Trade(option, open_time)
        self.trades.append(trade)
        if option.is_long:
            self.withdraw(option.price * 100)
        else:
            self.deposit(option.price * 100)

    def close_trade(self, option: 'Option', close_time: datetime):
        target_trade = None
        for trade in self.trades:
            if all([
                trade.opening_option.ticker == option.ticker,
                trade.opening_option.strike == option.strike,
                trade.opening_option.is_call == option.is_call,
                trade.opening_option.is_long == (not option.is_long),
                trade.opening_option.expiration_date == option.expiration_date,
            ]):
                target_trade = trade
                break
        if target_trade is None:
            raise LookupError(f'No trade could be found to close option {option}')
        target_trade.close(option, close_time)
        if option.is_long:
            self.withdraw(option.price * 100)
        else:
            self.deposit(option.price * 100)

    def get_total_profit(self):
        return round(sum([trade.profit for trade in self.trades if trade.is_closed]), 2)

    def get_average_profit(self):
        return round(self.get_total_profit() / len([trade for trade in self.trades if trade.is_closed]), 2)

    def get_average_profit_percentage(self):
        total_profit_percentage = sum([trade.profit_percentage for trade in self.trades if trade.is_closed])
        return round(total_profit_percentage / len([trade for trade in self.trades if trade.is_closed]), 2)

    def get_win_percentage(self):
        winning_trades = [True for trade in self.trades if trade.profit >= 0]
        return round(len(winning_trades) / len(self.trades) * 100, 2)

    def get_average_duration(self):
        total_duration = sum([trade.duration for trade in self.trades if trade.is_closed], timedelta(0))
        return str(total_duration / len(self.trades))

    def open_option(self, option: 'Option'):
        self.options.append(option)
        if option.is_long:
            self.withdraw(option.price * 100)
        else:
            self.deposit(option.price * 100)

    def close_option(self, option: 'Option'):
        counterpart = None
        for existing_option in self.options:
            if all([
                existing_option.ticker == option.ticker,
                existing_option.strike == option.strike,
                existing_option.is_call == option.is_call,
                existing_option.is_long == (not option.is_long),
                existing_option.expiration_date == option.expiration_date,
            ]):
                counterpart = existing_option
                break
        if option.is_long:
            self.withdraw(option.price * 100)
        else:
            self.deposit(option.price * 100)
        self.options.remove(counterpart)


class Option:
    def __init__(
            self,
            ticker: str,
            strike: float,
            price: float,
            is_call: bool,
            is_long: bool,
            expiration_date: date,
            **kwargs,
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
    def __init__(
            self,
            opening_option: 'Option',
            open_time: datetime,
    ):
        self.opening_option = opening_option
        self.open_time = open_time
        self.is_closed = False
        self.close_time = None
        self.closing_option = None
        self.profit = 0.0
        self.profit_percentage = 0.0
        self.duration = None

    def close(
            self,
            closing_option: 'Option',
            close_time: datetime,
    ):
        self.is_closed = True
        self.closing_option = closing_option
        self.close_time = close_time
        open_value = (self.opening_option.price * 100) if not self.opening_option.is_long else (self.opening_option.price * -100)
        close_value = (self.closing_option.price * 100) if not self.closing_option.is_long else (self.closing_option.price * -100)
        self.profit = open_value + close_value
        try:
            self.profit_percentage = (self.profit / abs(open_value)) * 100
        except ZeroDivisionError:
            self.profit_percentage = -100.0
        self.duration = self.close_time - self.open_time
        # print(f'{self.duration=}')


account = Account()

with open(os.path.join('data', 'trade_events.json')) as data_file:
    events_data = json.load(data_file)

for trade_event in events_data:
    for option_data in trade_event['options']:
        option = Option(
            **{
                convert_case(key, Case.CAMEL, Case.SNAKE): value
                for key, value in option_data.items()}
        )
        if option_data.get('toOpen'):
            account.open_trade(option, str_dt(trade_event.get('time')))
        else:
            account.close_trade(option, str_dt(trade_event.get('time')))
        # print(f'{option=}')
        # add or remove position from account
        # if option_data['toOpen']:
        #     account.open_option(option)
        # else:
        #     account.close_option(option)

print(f'{len(account.trades)=}')
print(f'{account.get_total_profit()=}')
print(f'{account.get_average_profit()=}')
print(f'{account.get_average_profit_percentage()=}')
print(f'{account.get_win_percentage()=}')
print(f'{account.get_average_duration()=}')


