#!/usr/bin/env python3
import json
import os
import re
from datetime import datetime


def finish_trade_event(trade_event):
    if trade_event != default_trade_event:
        trade_event['expirationDate'] = datetime.strptime(f'{trade_event["time"].year}-{trade_event["expirationDate"]}', '%Y-%m-%d').date().strftime('%Y-%m-%d')
        trade_event['time'] = trade_event['time'].strftime('%Y-%m-%dT%H:%M:%S')
        trade_events.append(trade_event)


trade_events = []
with open(os.path.join('raw_data', 'trades.txt')) as input_file:
    default_trade_event = {
        'options': []
    }
    trade_event = default_trade_event.copy()
    for line in input_file:
        line = line.strip()
        if not line:
            if trade_event != default_trade_event:
                finish_trade_event(trade_event)
                trade_event = {
                    'options': []
                }
                continue
        if option_line := re.search(r'(?:[+-]\d+ )?(\w+) \$(\d+\.?\d*) (\w+) (\d+)\/(\d+) (\w+)', line):
            trade_event['ticker'] = option_line.group(1)
            trade_event['expirationDate'] = option_line.group(4).zfill(2) + '-' + option_line.group(5).zfill(2)
            option_data = {
                'strike': round(float(option_line.group(2)), 2),
                'isCall': True if option_line.group(3) == 'Call' else False,
                'isLong': True if option_line.group(6) == 'Buy' else False,
            }
            for option_detail_line in input_file:
                option_detail_line = option_detail_line.strip()
                if execution_time_line := re.search(r'(\w+) (\d+), (\d{4}), (\d+):(\d+) (\w+) \w+', option_detail_line):
                    month = execution_time_line.group(1)
                    day = execution_time_line.group(2).zfill(2)
                    year = execution_time_line.group(3)
                    hour = execution_time_line.group(4).zfill(2)
                    minute = execution_time_line.group(5).zfill(2)
                    am_pm = execution_time_line.group(6)
                    trade_event['time'] = datetime.strptime(f'{month} {day} {year} {hour}:{minute} {am_pm}', '%b %d %Y %I:%M %p')
                elif quantity_price_line := re.search(r'(\d+) Contract at \$(\d+\.?\d*)', option_detail_line):
                    option_data['quantity'] = int(quantity_price_line.group(1))
                    option_data['price'] = round(float(quantity_price_line.group(2)), 2)
                if trade_event.get('time') and option_data.get('price'):
                    break
            trade_event['options'].append(option_data)

if trade_event != default_trade_event:
    finish_trade_event(trade_event)

with open(os.path.join('trade_events_data', 'trades.json'), 'w') as output_file:
    json.dump(trade_events, output_file, indent=2)
