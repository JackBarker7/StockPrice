import datetime as dt
import pandas as pd
import numpy as np
import json
from yahoo_fin import stock_info as si
from functools import reduce
from typing import List
from dataclasses import dataclass
import dash
from dash import dcc, html
from dash.dependencies import Input, Output
import plotly.express as px
import requests
from subprocess import Popen
import os

with open("config.json", "r") as f:
    config_data = json.load(f)

BASE_CURRENCY = config_data["BASE_CURRENCY"]
GRAPH_UNITS = config_data["GRAPH_UNITS"]

with open("currency_cache.json", "r") as f:
    CURRENCY_DATA = json.load(f)

#prevent errors by creating cache files if they don't exist already
for filename in ["currency_cache.json", "stock_cache.csv"]:
    if not os.path.isfile(filename):
        open(filename, "a").close()

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



def load_portfolio(file="portfolio.json") -> List[Stock]:
    """return is a list of Stock objects. Each Stock contains all the information about the stock from the json,
    plus a dataframe showing prices between start date and end date"""
    with open(file, "r") as f:
        stock_list = json.load(f)

    # load in cached data
    imported_data = pd.read_csv("stock_cache.csv")
    imported_data["time"] = pd.to_datetime(imported_data["time"])

    rep = []
    # create stock objects

    for stock in stock_list:
        name = stock["name"]

        # check if stock has any data cached, and if it does, assign it to the new stock
        if name in list(imported_data.columns):
            stock["data"] = imported_data[["time", name]].dropna()
            stock["data"].columns = ["time", "value"]

            stock["data"].index = stock["data"]["time"]

        new_stock = Stock(**stock)
        rep.append(new_stock)

    # once all stocks have been created and __post_init__() has run, save to cache

    # last row in each df is dropped as this is a real-time value and may not be applicable in future
    to_cache = pd.concat(
        [stock.data.drop("time", axis=1).drop(stock.data.index[-1]) for stock in rep],
        axis=1,
        ignore_index=True,
    )
    to_cache.columns = [stock.name for stock in rep]
    to_cache.to_csv("stock_cache.csv", index_label="time")

    return rep


def get_values(
    start: dt.datetime, end: dt.datetime, ticker: str, exchange="LSE"
) -> pd.DataFrame:
    times = config_data["EXCHANGE_TIMES"][exchange]  # open times of various exchanges

    # collect the raw data from Yahoo Finance, take only the open and close columns
    raw = si.get_data(
        ticker,
        start.strftime("%m/%d/%y"),
        (end + dt.timedelta(days=1)).strftime("%m/%d/%y"),
    )[["open", "close"]]

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
    if rep.index[-1]<rep.index[-2]:
        rep.drop(rep.index[-1], inplace=True)
    return rep.sort_index().assign(time=rep.index.values)


def merge_portfolio(portfolio: List[Stock]) -> pd.DataFrame:
    daily_average_dfs = []
    for stock in portfolio:
        df = stock.data.copy()
        df = df.groupby([df["time"].dt.date]).mean() * stock.holding
        df["book_cost"] = stock.book_cost * 100.0
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
        with open("currency_cache.json", "w") as f:
            json.dump(CURRENCY_DATA, f)
        return value * request


def get_current_price(ticker):
    return si.get_live_price(ticker)


def parse_date(date_string) -> dt.datetime:
    """parses date from YYYY-MM-DD to datetime object.
    Returns current date if date_string is empty"""
    if not date_string:
        return dt.date.today()
    return dt.datetime.strptime(date_string, "%Y-%m-%d")


PORTFOLIO = load_portfolio()
TOTAL_VALUE = merge_portfolio(PORTFOLIO)


def main():
    dropdown_options = [
        {"label": stock.name, "value": stock.ticker} for stock in PORTFOLIO
    ]
    dropdown_options[0:0] = [
        {"label": "Portfolio Percentage Loss/Gain", "value": "PERCENT.LG"},
        {"label": "Portfolio Actual Loss/Gain", "value": "ACTUAL.LG"},
    ]
    app = dash.Dash(__name__)
    app.layout = html.Div(
        children=[
            dcc.Dropdown(
                id="ticker_dropdown",
                options=dropdown_options,
                value="PERCENT.LG",
                clearable=False,
            ),
            dcc.Graph(id="time-series-chart"),
        ]
    )

    @app.callback(
        Output("time-series-chart", "figure"), [Input("ticker_dropdown", "value")]
    )
    def update_graph(ticker):
        data = TOTAL_VALUE
        COLOUR_GREEN = "#00ff04"
        COLOUR_RED = "red"
        color = COLOUR_GREEN
        if ticker == "PERCENT.LG":
            if data.iloc[-1]["percent_change"] < 0:
                color = COLOUR_RED
            fig = px.line(data, x=data.index, y="percent_change")
            fig.update_traces(line_color=color)
            fig.update_layout(yaxis_title="Percent change in portfolio value")

        elif ticker == "ACTUAL.LG":
            if data.iloc[-1]["actual_change"] < data.iloc[0]["actual_change"]:
                color = COLOUR_RED
            fig = px.line(data, x=data.index, y=data["actual_change"] / 100)
            fig.update_traces(line_color=color)
            fig.update_layout(yaxis_title="Change in portfolio value (pounds)")

        else:
            for stock in PORTFOLIO:
                if stock.ticker == ticker:
                    data = stock.data["value"]
                    break
            color = "#00ff04"
            if data.iloc[-1] < data.iloc[0]:
                color = "red"
            fig = px.line(data, x=data.index, y="value")
            fig.update_traces(line_color=color)
            fig.update_layout(yaxis_title=f"Value of {ticker} ({GRAPH_UNITS})")

        fig.update_layout(xaxis_title="Date")
        fig.update_layout(
            xaxis=dict(
                rangeselector=dict(
                    buttons=list(
                        [
                            dict(
                                count=1, label="1m", step="month", stepmode="backward"
                            ),
                            dict(
                                count=6, label="6m", step="month", stepmode="backward"
                            ),
                            dict(count=1, label="YTD", step="year", stepmode="todate"),
                            dict(count=1, label="1y", step="year", stepmode="backward"),
                            dict(step="all"),
                        ]
                    )
                ),
                rangeslider=dict(visible=True),
                type="date",
            )
        )
        return fig


    if config_data["AUTO_OPEN_BROWSER"]:
        Popen(
            [config_data["BROWSER_PATH"], "http://127.0.0.1:8050"]
        )
    app.run_server(debug=config_data["DEBUG"])


main()
