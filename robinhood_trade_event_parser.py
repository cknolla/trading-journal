import json
import os
import re
from datetime import datetime


def parse_robinhood_file(filepath):
    def finish_trade_event(trade_event):
        if trade_event != default_trade_event:
            trade_event['expirationDate'] = datetime.strptime(f'{trade_event["executionTime"].year}-{trade_event["expirationDate"]}', '%Y-%m-%d').date().strftime('%Y-%m-%d')
            trade_event['executionTime'] = trade_event['executionTime'].strftime('%Y-%m-%dT%H:%M:%S')
            trade_events.append(trade_event)
    trade_events = []
    with open(filepath) as input_file:
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

            if expiration_line := re.search(r'(\w+) \$(\d+\.?\d*) (\w+) Expiration', line):
                trade_event['ticker'] = expiration_line.group(1)
                option_data = {
                    'strike': round(float(expiration_line.group(2)), 2),
                    'isCall': True if expiration_line.group(3) == 'Call' else False,
                    'isLong': None,
                    'price': 0.0,
                }
                for expiration_detail_line in input_file:
                    expiration_detail_line = expiration_detail_line.strip()
                    if re.match(r'Contracts$', expiration_detail_line):
                        quantity_line = re.match(r'(\d+)$', input_file.readline())
                        option_data['quantity'] = int(quantity_line.group(1))
                    elif re.match(r'Date$', expiration_detail_line):
                        exercise_date_line = re.match(r'(\d+)\/(\d+)\/(\d+)$', input_file.readline())
                        month = exercise_date_line.group(1).zfill(2)
                        day = exercise_date_line.group(2).zfill(2)
                        year = exercise_date_line.group(3)
                        trade_event['executionTime'] = datetime.strptime(f'{year}-{month}-{day} 16:00:00', '%Y-%m-%d %H:%M:%S')
                        trade_event['expirationDate'] = f'{month}-{day}'
                        break
                trade_event['options'].append(option_data)

            elif exercise_line := re.search(r'(\w+) \$(\d+\.?\d*) (\w+) Exercise', line):
                trade_event['ticker'] = exercise_line.group(1)
                option_data = {
                    'strike': round(float(exercise_line.group(2)), 2),
                    'isCall': True if exercise_line.group(3) == 'Call' else False,
                    'isLong': False,
                }
                for exercise_detail_line in input_file:
                    if re.match(r'Contracts$', exercise_detail_line):
                        quantity_line = re.match(r'(\d+)$', input_file.readline())
                        option_data['quantity'] = int(quantity_line.group(1))
                    elif re.search(r'\w+ Price at Expiration', exercise_detail_line):
                        price_line = re.match(r'\$(\d+\.?\d*)$', input_file.readline())
                        price = round(float(price_line.group(1)), 2)
                        option_data['price'] = round(abs(price - option_data['strike']), 2)
                    elif re.match(r'Date$', exercise_detail_line):
                        exercise_date_line = re.match(r'(\d+)\/(\d+)\/(\d+)$', input_file.readline())
                        month = exercise_date_line.group(1).zfill(2)
                        day = exercise_date_line.group(2).zfill(2)
                        year = exercise_date_line.group(3)
                        trade_event['executionTime'] = datetime.strptime(f'{year}-{month}-{day} 16:00:00', '%Y-%m-%d %H:%M:%S')
                        trade_event['expirationDate'] = f'{month}-{day}'
                        break
                trade_event['options'].append(option_data)

            elif assignment_line := re.search(r'(\w+) \$(\d+\.?\d*) (\w+) Assignment', line):
                trade_event['ticker'] = assignment_line.group(1)
                option_data = {
                    'strike': round(float(assignment_line.group(2)), 2),
                    'isCall': True if assignment_line.group(3) == 'Call' else False,
                    'isLong': True,
                }
                for assignment_detail_line in input_file:
                    if re.match(r'Contracts$', assignment_detail_line):
                        quantity_line = re.match(r'(\d+)$', input_file.readline())
                        option_data['quantity'] = int(quantity_line.group(1))
                    elif re.search(r'\w+ Price at Expiration', assignment_detail_line):
                        price_line = re.match(r'\$(\d+\.?\d*)$', input_file.readline())
                        price = round(float(price_line.group(1)), 2)
                        option_data['price'] = round(abs(price - option_data['strike']), 2)
                    elif re.match(r'Date$', assignment_detail_line):
                        exercise_date_line = re.match(r'(\d+)\/(\d+)\/(\d+)$', input_file.readline())
                        month = exercise_date_line.group(1).zfill(2)
                        day = exercise_date_line.group(2).zfill(2)
                        year = exercise_date_line.group(3)
                        trade_event['executionTime'] = datetime.strptime(f'{year}-{month}-{day} 16:00:00', '%Y-%m-%d %H:%M:%S')
                        trade_event['expirationDate'] = f'{month}-{day}'
                        break
                trade_event['options'].append(option_data)

            elif option_line := re.search(r'(?:[+-]\d+ )?(\w+) \$(\d+\.?\d*) (\w+) (\d+)\/(\d+) (\w+)', line):
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
                        trade_event['executionTime'] = datetime.strptime(f'{month} {day} {year} {hour}:{minute} {am_pm}', '%b %d %Y %I:%M %p')
                    elif quantity_price_line := re.search(r'(\d+) Contract at \$(\d+\.?\d*)', option_detail_line):
                        option_data['quantity'] = int(quantity_price_line.group(1))
                        option_data['price'] = round(float(quantity_price_line.group(2)), 2)
                    if trade_event.get('executionTime') and option_data.get('price'):
                        break
                trade_event['options'].append(option_data)

    if trade_event != default_trade_event:
        finish_trade_event(trade_event)

    with open(os.path.join('trade_events_data', os.path.splitext(os.path.split(filepath)[1])[0] + '.json'), 'w') as output_file:
        json.dump(trade_events, output_file, indent=2)
