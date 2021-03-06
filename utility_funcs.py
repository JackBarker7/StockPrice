import numpy as np
import pandas as pd
from dataclasses import dataclass
import datetime as dt
from typing import List
from yahoo_fin import stock_info as si
from functools import reduce
import requests
import json
import os
import sys

if __name__ == "__main__":
    print("Run app.py instead")
    sys.exit()


CURRENT_FOLDER = os.path.dirname(os.path.abspath(__file__))


FIELDS = [
    "Name",
    "Ticker",
    "Currency",
    "Date Bought",
    "Date Sold",
    "Holding",
    "Book Cost",
    "Commission",
    "FX Charge",
    "Exchange",
]  # JSON fields for each stock

files = [
    "data/currency_cache.json",
    "data/config.json",
    "data/portfolio.json",
    "data/stock_cache.csv",
]  # relevant file names
[CURRENCY_CACHE_FILE, CONFIG_FILE, PORTFOLIO_FILE, STOCK_CACHE_FILE] = [
    os.path.join(CURRENT_FOLDER, x) for x in files
]  # get corrent path to files

with open(CURRENCY_CACHE_FILE, "r") as f:
    CURRENCY_DATA = json.load(f)

with open(CONFIG_FILE, "r") as f:
    config_data = json.load(f)

BASE_CURRENCY = config_data["BASE_CURRENCY"]
VERBOSE = config_data["VERBOSE"]


@dataclass
class Stock:
    """Dataclass that holds all relevant information about a stock. 
    After loading, the `data` dataframe is populated with the value of the stock over the required time period."""

    name: str
    ticker: str
    currency: str
    date_bought: dt.datetime
    holding: float
    book_cost: float # in GBP
    commission: float
    fx_charge: float
    exchange: str # either LSE, NASDAQ or CRYPTO
    date_sold: dt.datetime = dt.date.today()
    data: pd.DataFrame = None
    gained: bool = False

    def __post_init__(self):
        if self.data is None:
            # no data for this stock was present in cache, so fetch new data

            if VERBOSE: print("getting values")
            self.data = get_values(
                parse_date(self.date_bought),
                parse_date(self.date_sold),
                self.ticker,
                exchange=self.exchange,
            )
            # apply currency conversion (if required):
            if self.currency != BASE_CURRENCY:
                self.data["value"] = self.data.apply(
                    lambda row: convert_currency(
                        row["value"], row["time"], self.currency
                    )
                    * 100,
                    axis=1,
                )

            # apply commission/fx charge using book price
            self.data.loc[(self.data.index[0], "value")] = (
                self.book_cost * 100 / self.holding
            )  # equivalent to self.data.iloc[0]["value"], but prevents SettingWithCopyWarning
            if VERBOSE: print(self.data)

        else:
            # data was cached, but is not fully up to date
            last_date = self.data.index[-1].date()
            # to avoid confusion/out of date data, remove all data generated on this date
            self.data = self.data[self.data["time"].dt.date != last_date]

            new_data = get_values(
                last_date,
                parse_date(self.date_sold),
                self.ticker,
                exchange=self.exchange,
            )
            new_data.drop_duplicates(inplace=True)
            if self.currency != BASE_CURRENCY:
                new_data["value"] = new_data.apply(
                    lambda row: convert_currency(
                        row["value"], row["time"], self.currency
                    )
                    * 100,
                    axis=1,
                )

            self.data = pd.concat([self.data, new_data])


def load_portfolio(file: str = PORTFOLIO_FILE) -> List[Stock]:
    """return is a list of Stock objects. Each Stock contains all the information about the stock from the json,
    plus a dataframe showing prices between start date and end date"""
    with open(file, "r") as f:
        stock_list = json.load(f)

    # load in cached data
    try:
        imported_data = pd.read_csv(STOCK_CACHE_FILE)
        imported_data["time"] = pd.to_datetime(imported_data["time"])
    except pd.errors.EmptyDataError:
        # handle case where no data in file
        imported_data = pd.DataFrame(columns=["time", *stock_list])

    rep = []
    # create stock objects

    for stock in stock_list:
        name = stock["name"]

        # check if stock has any data cached, and if it does, assign it to the new stock
        if name in list(imported_data.columns):
            stock["data"] = imported_data[["time", name]].fillna(method="ffill")
            stock["data"].columns = ["time", "value"]

            stock["data"].index = stock["data"]["time"]

        new_stock = Stock(**stock)
        rep.append(new_stock)

    # once all stocks have been created and __post_init__() has run, save to cache

    # create a list of all the dataframes
    dataframes: List[pd.DataFrame] = [
        stock.data.drop("time", axis=1).drop(stock.data.index[-1]) for stock in rep
    ]

    # to concaternate, we require that all arrays have the same index. Therefore, we need to fill any missing index values with NaN
    all_timestamps = np.unique(np.concatenate([df.index.values for df in dataframes]))
    for i, df in enumerate(dataframes):

        missing_indices = np.setdiff1d(all_timestamps, df.index.values)
        nan_rows = pd.DataFrame(
            {"value": np.empty(len(missing_indices)).fill(np.nan)},
            index=missing_indices,
            dtype=np.float64,
        )
        dataframes[i] = pd.concat([df, nan_rows]).sort_index()

    # last row in each df is dropped as this is a real-time value and may not be applicable in future
    try:
        to_cache = pd.concat(
            dataframes,
            axis=1,
        )

        to_cache.columns = [stock.name for stock in rep]
        to_cache.to_csv(STOCK_CACHE_FILE, index_label="time")
    except Exception as e:
        # for some reason this is usually a temporary problem that seems to sort itself out when code is run a few days later
        print(f"Caching has failed. Error message: \n{e}")

    return rep


def get_values(
    start: dt.datetime, end: dt.datetime, ticker: str, exchange: str = "LSE"
) -> pd.DataFrame:
    """ Returns the values of a stock between a start and end date in a DataFrame"""
    times = config_data["EXCHANGE_TIMES"][exchange]  # open times of various exchanges

    # collect the raw data from Yahoo Finance, take only the open and close columns
    if VERBOSE: print("Fetching data:")
    try:
        if VERBOSE: print(ticker)
        raw = si.get_data(
            ticker,
            start.strftime("%m/%d/%y"),
            (end + dt.timedelta(days=1)).strftime("%m/%d/%y"),
        )[["open", "close"]]
    except KeyError:
        # some wierd quirk with the yahoo_fin module
        index = pd.date_range(start, end, freq="1D")
        raw = pd.DataFrame(np.nan, columns=["open", "close"], index=index)
    except AssertionError as e:
        print("Assertion error. Ticker likely does not exist")
        print(e)
        raise AssertionError


    # turn into data frame with one column (value) and forward fill any missing values
    rep = pd.concat([raw["open"], raw["close"]]).to_frame().fillna(method="ffill")
    rep.columns = ["value"]

    # add open and close times to index, and return sorted dataframe
    rep.index = pd.concat(
        [
            raw.index.to_series() + dt.timedelta(hours=times["open"]),
            raw.index.to_series() + dt.timedelta(hours=times["close"]),
        ]
    )
    rep: pd.DataFrame = rep.rename(index={rep.index[-1]: dt.datetime.now()})
    if rep.index[-1] < rep.index[-2]:
        rep.drop(rep.index[-1], inplace=True)

    # crypto assets need their currency converted to pence
    if exchange == "CRYPTO":
        rep["value"] = rep["value"] * 100.0
    return rep.sort_index().assign(time=rep.index.values)


def merge_portfolio(portfolio: List[Stock]) -> pd.DataFrame:
    """ Merges all stocks in portfolio into one DataFrame"""
    daily_average_dfs = [] # array of DataFrames, each holding average value of each stock for a period of days
    for stock in portfolio:
        df = stock.data.copy().fillna(method="ffill")
        # get mean for each day
        df = df.groupby([df["time"].dt.date]).mean() * stock.holding
        df["book_cost"] = stock.book_cost * 100.0
        # if stock does not have recorded value for this day, set book cost to 0
        df.loc[np.isnan(df["value"]), "book_cost"] = 0
        daily_average_dfs.append(df)

    # combine dataframes, and add actual change and percentage change columns
    rep = reduce(lambda a, b: a.add(b, fill_value=0), daily_average_dfs)
    rep["actual_change"] = rep["value"] - rep["book_cost"]
    rep["percent_change"] = rep["actual_change"] * 100 / rep["book_cost"]

    return rep


def convert_currency(
    value: float, date: dt.datetime = dt.date.today(), c_from: str = "USD"
) -> float:
    """ Converts currency at `date` from `c_from` to global currency"""
    global CURRENCY_DATA
    date_str = date.strftime("%Y-%m-%d")

    try:
        return value * CURRENCY_DATA[c_from][date]
    except KeyError:
        request = requests.get(
            f"https://api.exchangerate.host/convert?from={c_from}&to={BASE_CURRENCY}&date={date_str}"
        ).json()["info"]["rate"]

        CURRENCY_DATA[c_from][date_str] = request
        with open(CURRENCY_CACHE_FILE, "w") as f:
            json.dump(CURRENCY_DATA, f)
        return value * request


def get_current_price(ticker: str) -> np.float64:
    return si.get_live_price(ticker)


def parse_date(date_string: str) -> dt.datetime:
    """parses date from YYYY-MM-DD to datetime object.
    Returns current date if date_string is empty"""
    if not date_string:
        return dt.date.today()
    return dt.datetime.strptime(date_string, "%Y-%m-%d")


def add_new_stock_to_file(new_data: tuple):
    with open(PORTFOLIO_FILE, "r") as f:
        portfolio = json.load(f)

    new_data = list(new_data)
    new_data[5:9] = [int(i) for i in new_data[5:9]]
    print(new_data)
