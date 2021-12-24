import datetime as dt
import pandas as pd
import numpy as np
import json
from functools import reduce
from typing import List
from dataclasses import dataclass
import dash
from dash import dcc, html
from dash.dependencies import Input, Output
import plotly.express as px
from subprocess import Popen
import os
from utility_funcs import *

CURRENT_FOLDER = os.path.dirname(os.path.abspath(__file__))

GRAPH_UNITS = config_data["GRAPH_UNITS"]

with open(os.path.join(CURRENT_FOLDER, "data/config.json"), "r") as f:
    config_data = json.load(f)

# prevent errors by creating cache files if they don't exist already
for filename in ["data/currency_cache.json", "data/stock_cache.csv"]:
    filename = os.path.join(CURRENT_FOLDER, filename)
    if not os.path.isfile(filename):
        open(filename, "a").close()


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
        Popen([config_data["BROWSER_PATH"], "http://127.0.0.1:8050"])
    app.run_server(debug=config_data["DEBUG"], host="0.0.0.0", port="8050")


main()
