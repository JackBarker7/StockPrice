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

BASE_CURRENCY = "GBP"
EXCHANGE_TIMES = {"LSE": {"open": 8, "close": 17}, "NASDAQ": {"open": 14, "close": 21}}
with open("currency_cache.json", "r") as f:
    CURRENCY_DATA = json.load(f)


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
        if not self.data:
            self.data = get_values(
                parse_date(self.date_bought),
                parse_date(self.date_sold),
                self.ticker,
                exchange=self.exchange,
            )
        # apply currency conversion (if required):
        if self.currency != "GBP":
            self.data["value"] = self.data.apply(
                lambda row: convert_currency(row["value"], row["time"], self.currency)
                * 100,
                axis=1,
            )

        # apply commission/fx charge using book price
        self.data.loc[(self.data.index[0], "value")] = (
            self.book_cost * 100 / self.holding
        )  # equivalent to self.data.iloc[0]["value"], but prevents SettingWithCopyWarning


def load_portfolio(file="portfolio.json") -> List[Stock]:
    """return is a list of Stock objects. Each Stock contains all the information about the stock from the json,
    plus a dataframe showing prices between start date and end date"""
    with open(file, "r") as f:
        stock_list = json.load(f)
    rep = []
    # convert stocks into pandas dataframes

    for stock in stock_list:
        new_stock = Stock(**stock)
        rep.append(new_stock)
    return rep


def get_values(
    start: dt.datetime, end: dt.datetime, ticker: str, exchange="LSE"
) -> pd.DataFrame:
    times = EXCHANGE_TIMES[exchange]
    raw = si.get_data(
        ticker,
        start.strftime("%m/%d/%y"),
        (end + dt.timedelta(days=1)).strftime("%m/%d/%y"),
    )[["open", "close"]]
    rep = pd.concat([raw["open"], raw["close"]]).to_frame().fillna(method="ffill")
    rep.columns = ["value"]
    rep.index = pd.concat(
        [
            raw.index.to_series() + dt.timedelta(hours=times["open"]),
            raw.index.to_series() + dt.timedelta(hours=times["close"]),
        ]
    )
    rep = rep.rename(index={rep.index[-1]: dt.datetime.now()})
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
            f"https://api.exchangerate.host/convert?from={c_from}&to=GBP&date={date_str}"
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

dropdown_options = [{"label": stock.name, "value": stock.ticker} for stock in PORTFOLIO]
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
        fig.update_layout(yaxis_title = "Percent change in portfolio value")

    elif ticker == "ACTUAL.LG":
        if data.iloc[-1]["actual_change"] < data.iloc[0]["actual_change"]:
            color = COLOUR_RED
        fig = px.line(data, x=data.index, y=data["actual_change"]/100)
        fig.update_traces(line_color=color)
        fig.update_layout(yaxis_title = "Change in portfolio value (pounds)")
        
    else:
        for stock in PORTFOLIO:
            if stock.ticker == ticker:
                data = stock.data["value"]
                break
        color = "#00ff04"
        if(data.iloc[-1] < data.iloc[0]):
            color = "red"
        fig = px.line(data, x=data.index, y="value")
        fig.update_traces(line_color=color)
        fig.update_layout(yaxis_title = f"Value of {ticker} (pence)")

    fig.update_layout(xaxis_title="Date")
    fig.update_layout(
        xaxis=dict(
            rangeselector=dict(
                buttons=list([
                    dict(count=1,
                        label="1m",
                        step="month",
                        stepmode="backward"),
                    dict(count=6,
                        label="6m",
                        step="month",
                        stepmode="backward"),
                    dict(count=1,
                        label="YTD",
                        step="year",
                        stepmode="todate"),
                    dict(count=1,
                        label="1y",
                        step="year",
                        stepmode="backward"),
                    dict(step="all")
                ])
            ),
            rangeslider=dict(
                visible=True
            ),
            type="date"
        )
    )
    return fig


"""Popen(
    [r"C:\Program Files\Google\Chrome\Application\chrome.exe", "http://127.0.0.1:8050"]
)"""
app.run_server(debug=True)
