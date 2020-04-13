Semi-automated options trading journal

## Requirements
Python3.8

## Install
```
git clone git@github.com:cknolla/trading-journal.git
cd trading-journal
python3.8 -m venv venv
source venv/bin/activate
```

## How to Use
Within `/raw_data`, create a `.txt` file named with the date of the trade events that occurred for that day.
For example, `2020-04-09.txt` will contain the trades that occurred on April 9th. The name isn't significant, it just needs to be unique.

From the Robinhood Account --> History page, copy the entire contents of a trade event into the `.txt` file.

For example: 
```
NVDA Put Credit Spread
Apr 9
$325.00
Time in Force
Good for day
Submitted
Apr 9, 2020
Status
Filled
Limit Price
$3.49
Quantity
1
Total
$325.00
-1 NVDA $260 Put 4/9 Sell
Type
Limit Sell
Effect
Close
Filled
Apr 9, 2020, 2:55 PM EDT
Filled Quantity
1 Contract at $1.42
+1 NVDA $265 Put 4/9 Buy
Type
Limit Buy
Effect
Close
Filled
Apr 9, 2020, 2:55 PM EDT
Filled Quantity
1 Contract at $4.67
```

Do this for each trade event for that day. *Important: Separate each trade event by at least 1 blank line.* 
Continue adding trade events until all positions are in a closed state. These can be across several files.

Finally, run `python3.8 trading_journal.py` to parse the `.txt` files into `.json` files (found in `/trade_events_data`)
and report trade data in the console.

