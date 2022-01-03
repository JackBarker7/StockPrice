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

# get correct path to files
files = [
    "data/currency_cache.json",
    "data/config.json",
    "data/portfolio.json",
    "data/stock_cache.csv",
]
[CURRENCY_CACHE_FILE, CONFIG_FILE, PORTFOLIO_FILE, STOCK_CACHE_FILE] = [
    os.path.join(CURRENT_FOLDER, x) for x in files
]

with open(CURRENCY_CACHE_FILE, "r") as f:
    CURRENCY_DATA = json.load(f)

with open(CONFIG_FILE, "r") as f:
    config_data = json.load(f)

BASE_CURRENCY = config_data["BASE_CURRENCY"]


@dataclass
class Stock:
    name: str
    ticker: str
    currency: str
    date_bought: dt.datetime
    holding: int
    book_cost: float
    commission: float
    fx_charge: float
    exchange: str
    date_sold: dt.datetime = dt.date.today()
    data: pd.DataFrame = None
    gained: bool = False

    def __post_init__(self):
        if self.data is None:
            # no data for this stock was present in cache, so fetch new data

            print("getting values")
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
            print(self.data)

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
    to_cache = pd.concat(
        dataframes,
        axis=1,
    )

    to_cache.columns = [stock.name for stock in rep]
    to_cache.to_csv(STOCK_CACHE_FILE, index_label="time")

    return rep


def get_values(
    start: dt.datetime, end: dt.datetime, ticker: str, exchange: str = "LSE"
) -> pd.DataFrame:
    times = config_data["EXCHANGE_TIMES"][exchange]  # open times of various exchanges

    # collect the raw data from Yahoo Finance, take only the open and close columns
    try:
        raw = si.get_data(
            ticker,
            start.strftime("%m/%d/%y"),
            (end + dt.timedelta(days=1)).strftime("%m/%d/%y"),
        )[["open", "close"]]
    except KeyError:
        #some wierd quirk with the yahoo_fin module
        index = pd.date_range(start, end, freq="1D")
        raw = pd.DataFrame(np.nan, columns=["open", "close"], index=index)

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
    return rep.sort_index().assign(time=rep.index.values)


def merge_portfolio(portfolio: List[Stock]) -> pd.DataFrame:
    daily_average_dfs = []
    for stock in portfolio:
        df = stock.data.copy().fillna(method="ffill")
        #get mean for each day
        df = df.groupby([df["time"].dt.date]).mean() * stock.holding
        df["book_cost"] = stock.book_cost * 100.0
        #if stock does not have recorded value for this day, set book cost to 0
        df.loc[np.isnan(df["value"]), "book_cost"] = 0
        daily_average_dfs.append(df)

    rep = reduce(lambda a, b: a.add(b, fill_value=0), daily_average_dfs)
    rep["actual_change"] = rep["value"] - rep["book_cost"]
    rep["percent_change"] = rep["actual_change"] * 100 / rep["book_cost"]

    return rep


def convert_currency(
    value: float, date: dt.datetime = dt.date.today(), c_from: str = "USD"
) -> float:
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
