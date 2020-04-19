Semi-automated options trading journal

## Requirements
Python3.6+

## Install
```
git clone git@github.com:cknolla/trading-journal.git
cd trading-journal
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## How to Use
Create a file called `.env` within the top-level `trading-journal` directory. Within it, add two variables:
Your Robinhood username (email) and password:
```.env
TJ_USERNAME=user@email.com
TJ_PASSWORD=password
```
These will be loaded from the OS environment to avoid including them in the code. 
The `.env` is automatically ignored in `.gitignore`

Then, run `python3 trading_journal.py`. 
You will be prompted for your Robinhood Two-factor code if the account has it enabled.
The trading journal will then process your trade data and output a report to `/reports`.

