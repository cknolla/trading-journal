import json
import os
import re

from robinhood_trade_event_parser import parse_robinhood_file
from string_conversions import convert_case, Case


# Not functional: Saving for test purposes if raw data dumps are needed

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
