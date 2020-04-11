#!/usr/bin/env python3
import json
import os
from datetime import date, datetime
from typing import List

from string_conversions import Case, convert_case


class Account:
    def __init__(self):
        self.value = 0.0
        self.options: List['Option'] = []

    def withdraw(self, amount: float):
        self.value -= amount

    def deposit(self, amount: float):
        self.value += amount

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
        self.options.remove(counterpart)
        if option.is_long:
            self.withdraw(option.price * 100)
        else:
            self.deposit(option.price * 100)


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
        # print(f'{option=}')
        # add or remove position from account
        if option_data['toOpen']:
            account.open_option(option)
        else:
            account.close_option(option)

print(f'account ending balance: {account.value=}')

