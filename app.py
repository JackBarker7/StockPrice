import json
import dash
from dash import dcc, html, callback_context
from dash.dependencies import Input, Output
from dash.exceptions import PreventUpdate
import plotly.express as px
from subprocess import Popen
import os
from utility_funcs import *

CURRENT_FOLDER = os.path.dirname(os.path.abspath(__file__))

GRAPH_UNITS = config_data["GRAPH_UNITS"]

COLOURS = {"positive_green": "#00ff04", "negative_red": "red", "graph_bg": "#082255", "highlighted_bg": "rgb(5, 46, 158)"}

with open(os.path.join(CURRENT_FOLDER, "data/config.json"), "r") as f:
    config_data = json.load(f)

# prevent errors by creating cache files if they don't exist already
for filename in ["data/currency_cache.json", "data/stock_cache.csv"]:
    filename = os.path.join(CURRENT_FOLDER, filename)
    if not os.path.isfile(filename):
        open(filename, "a").close()


PORTFOLIO = load_portfolio()
TOTAL_VALUE = merge_portfolio(PORTFOLIO)
# create the dropdown menu
dropdown_options = [{"label": stock.name, "value": stock.ticker} for stock in PORTFOLIO]
dropdown_options[0:0] = [
    {"label": "Portfolio Percentage Loss/Gain", "value": "PERCENT.LG"},
    {"label": "Portfolio Actual Loss/Gain", "value": "ACTUAL.LG"},
]


def generate_summary_graph(display_var="percent_change"):
    """generates graph showing summary info. display_var should be 'percent_change' or 'actual_change'"""

    data = TOTAL_VALUE[display_var]
    if display_var == "actual_change":
        data = data/100

    # set line colour
    line_color = COLOURS["positive_green"]
    if data.iloc[-1] < 0:
        line_color = COLOURS["negative_red"]

    if display_var == "percent_change":
        fig = px.line(data, x=data.index, y=display_var)
    else:
        fig = px.line(data, x=data.index, y=display_var)

    layout = {
        "xaxis_title": "Date",
        "yaxis_title": "Percentage change in portfolio value",
        "xaxis": {
            "rangeselector": {
                "buttons": [
                    {
                        "count": 1,
                        "label": "1m",
                        "step": "month",
                        "stepmode": "backward",
                    },
                    {
                        "count": 6,
                        "label": "6m",
                        "step": "month",
                        "stepmode": "backward",
                    },
                    {"count": 1, "label": "YTD", "step": "year", "stepmode": "todate"},
                    {"count": 1, "label": "1y", "step": "year", "stepmode": "backward"},
                    {"step": "all"},
                ],
                "font": {"color": "black"},
            },
            "rangeslider": {"visible": True},
            "type": "date",
            "gridcolor": line_color,
        },
        "yaxis": {"gridcolor": line_color},
        "plot_bgcolor": COLOURS["graph_bg"],
        "paper_bgcolor": COLOURS["graph_bg"],
        "font": {"color": "#fff"},
    }

    if display_var == "actual_value":
        layout["yaxis_title"] = "Net change in portfolio value"

    fig.update_layout(layout)
    fig.update_traces(line_color=line_color)
    return fig


app = dash.Dash(__name__)
app.layout = html.Div(
    id="wrapper",
    className="wrapper",
    children=[
        html.Div(
            className="summary",
            children=[
                dcc.Graph(
                    id="summary-chart",
                    className="summary-chart",
                    figure=generate_summary_graph(),
                ),
                html.Div(
                    className="summary-content-wrapper",
                    children=[
                        html.Div(
                            className="summary-content-box top left",
                            children=[
                                html.Div(
                                    className="summary-title",
                                    children="Total Value",
                                ),
                                html.Div(
                                    className="summary-content",
                                    children="£"
                                    + str(
                                        round(TOTAL_VALUE.iloc[-1]["value"] / 100, 2)
                                    ),
                                ),
                            ],
                        ),
                        html.Div(
                            className="summary-content-box top",
                            children=[
                                html.Div(
                                    className="summary-title",
                                    children="Initial Cost",
                                ),
                                html.Div(
                                    className="summary-content",
                                    children="£"
                                    + str(
                                        round(
                                            TOTAL_VALUE.iloc[-1]["book_cost"] / 100, 2
                                        )
                                    ),
                                ),
                            ],
                        ),
                        html.Div(
                            className="summary-content-box left hoverable",
                            id="percent-change-box",
                            n_clicks=0,
                            children=[
                                html.Div(
                                    className="summary-title",
                                    children="Percentage Change",
                                ),
                                html.Div(
                                    className="summary-content",
                                    children=str(
                                        round(TOTAL_VALUE.iloc[-1]["percent_change"], 2)
                                    )
                                    + "%",
                                ),
                            ],
                        ),
                        html.Div(
                            className="summary-content-box hoverable",
                            id="actual-change-box",
                            n_clicks=0,
                            children=[
                                html.Div(
                                    className="summary-title",
                                    children="Actual Change",
                                ),
                                html.Div(
                                    className="summary-content",
                                    children="£"
                                    + str(
                                        round(
                                            TOTAL_VALUE.iloc[-1]["actual_change"] / 100,
                                            2,
                                        )
                                    ),
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        ),
        html.Div(
            className="individual-wrapper",
            children=[
                html.Div(
                    # dropdown menu and graph
                    className="individual-info",
                    children=[
                        dcc.Dropdown(
                            id="ticker_dropdown",
                            options=dropdown_options,
                            value="PERCENT.LG",
                            clearable=False,
                        ),
                        html.Div(id="title-div", className="title-div"),
                        dcc.Graph(
                            id="individual-chart",
                            figure={
                                "layout": {
                                    "plot_bgcolor": COLOURS["graph_bg"],
                                    "paper_bgcolor": COLOURS["graph_bg"],
                                }
                            },
                        ),
                    ],
                ),
                html.Div(
                    id="info-boxes",
                    className="info-boxes-wrapper",
                    children=[
                        html.Div(
                            # current stock value
                            className="info-box",
                            children=[
                                html.Div(
                                    className="header-box",
                                    children=[html.H2("Current Value")],
                                ),
                                html.Div(
                                    id="value-box",
                                    className="data-box",
                                    children=[html.P(id="value-info")],
                                ),
                            ],
                        ),
                        html.Div(
                            # loss/gain
                            className="info-box",
                            children=[
                                html.Div(
                                    className="header-box",
                                    children=[html.H2("Loss/Gain")],
                                ),
                                html.Div(
                                    id="gain-box",
                                    className="data-box",
                                    children=[html.P(id="gain-info")],
                                ),
                            ],
                        ),
                        html.Div(
                            # max price
                            className="info-box",
                            children=[
                                html.Div(
                                    className="header-box",
                                    children=[html.H2("Maximum Value")],
                                ),
                                html.Div(
                                    id="max-box",
                                    className="data-box",
                                    children=[html.P(id="max-info")],
                                ),
                            ],
                        ),
                        html.Div(
                            # min price
                            className="min-info-box",
                            children=[
                                html.Div(
                                    className="header-box",
                                    children=[html.H2("Minimum Value")],
                                ),
                                html.Div(
                                    id="min-box",
                                    className="data-box",
                                    children=[html.P(id="min-info")],
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        ),
    ],
)


@app.callback(
    [Output("summary-chart", "figure"), Output("percent-change-box", "style"), Output("actual-change-box", "style")],
    [Input("percent-change-box", "n_clicks"), Input("actual-change-box", "n_clicks")],
)
def update_summary_graph(percent_new_clicks, actual_new_clicks):
    """updates graph data and style of percent change and actual change divs in summary section when either one is clicked
    the clicked div becomes a lighter blue, and the unclicked one returns to the original darker blue"""
    changed_id = [p['prop_id'] for p in callback_context.triggered][0]

    if percent_new_clicks == None:
        raise PreventUpdate
    elif "actual-change-box" in changed_id:
        return [generate_summary_graph("actual_change"), {"background-color": COLOURS["graph_bg"]}, {"background-color": COLOURS["highlighted_bg"]}]
    else:
        return [generate_summary_graph("percent_change"), {"background-color": COLOURS["highlighted_bg"]}, {"background-color": COLOURS["graph_bg"]}]
    


@app.callback(
    [
        Output("value-info", "children"),
        Output("gain-info", "children"),
        Output("max-info", "children"),
        Output("min-info", "children"),
        Output("title-div", "children"),
        Output("individual-chart", "figure"),
    ],
    [Input("ticker_dropdown", "value")],
)
def update_graph(ticker):
    data = TOTAL_VALUE
    line_color = COLOURS["positive_green"]

    layout = {
        "xaxis_title": "Date",
        "plot_bgcolor": COLOURS["graph_bg"],
        "paper_bgcolor": COLOURS["graph_bg"],
        "font": {"color": "#fff"},
    }

    response = {
        "value": None,
        "gain": None,
        "max": None,
        "min": None,
    }

    if ticker == "PERCENT.LG":
        # if the percent change option is selected
        response["value"] = str(round(data.iloc[-1]["percent_change"], 1)) + "%"
        response["gain"] = response["value"]
        response["max"] = str(round(data["percent_change"].max(), 1)) + "%"
        response["min"] = str(round(data["percent_change"].min(), 1)) + "%"

        if data.iloc[-1]["percent_change"] < 0:
            line_color = COLOURS["negative_red"]
        fig = px.line(data, x=data.index, y="percent_change")

        layout["yaxis_title"] = "Percent change in portfolio value"
        title = "Percent change in portfolio value"

    elif ticker == "ACTUAL.LG":
        # if the actual loss/gain option is selected
        response["value"] = "£" + str(round(data.iloc[-1]["actual_change"] / 100, 2))
        response["gain"] = str(round(data.iloc[-1]["percent_change"], 1)) + "%"
        response["max"] = "£" + str(round(data["actual_change"].max() / 100, 2))
        response["min"] = "£" + str(round(data["actual_change"].min() / 100, 2))

        if data.iloc[-1]["actual_change"] < data.iloc[0]["actual_change"]:
            line_color = COLOURS["negative_red"]
        fig = px.line(data, x=data.index, y=data["actual_change"] / 100)

        layout["yaxis_title"] = "Change in portfolio value (pounds)"
        title = "Actual change in portfolio value"

    else:
        # if an individual stock is selected
        for stock in PORTFOLIO:
            if stock.ticker == ticker:
                data = stock.data["value"].fillna(method="ffill").dropna()
                book_cost_per_share = stock.book_cost * 100 / stock.holding
                name = stock.name
                break

        response["value"] = str(round(data.iloc[-1], 1))
        response["gain"] = (
            str(
                round(
                    (data.iloc[-1] - book_cost_per_share) * 100 / book_cost_per_share, 1
                )
            )
            + "%"
        )
        response["max"] = str(round(data.max(), 1))
        response["min"] = str(round(data.min(), 1))

        if data.iloc[-1] < data.iloc[0]:
            line_color = COLOURS["negative_red"]
        fig = px.line(data, x=data.index, y="value")

        layout["yaxis_title"] = f"Value of {ticker} ({GRAPH_UNITS})"
        title = f"Value of {name}"

    fig.update_traces(line_color=line_color)

    layout["xaxis"] = {
        "rangeselector": {
            "buttons": [
                {"count": 1, "label": "1m", "step": "month", "stepmode": "backward"},
                {"count": 6, "label": "6m", "step": "month", "stepmode": "backward"},
                {"count": 1, "label": "YTD", "step": "year", "stepmode": "todate"},
                {"count": 1, "label": "1y", "step": "year", "stepmode": "backward"},
                {"step": "all"},
            ],
            "font": {"color": "black"},
        },
        "rangeslider": {"visible": True},
        "type": "date",
        "gridcolor": line_color,
    }

    layout["yaxis"] = {"gridcolor": line_color}
    fig.update_layout(layout)
    return *[str(i) for i in response.values()], title, fig


if config_data["AUTO_OPEN_BROWSER"]:
    Popen([config_data["BROWSER_PATH"], "http://127.0.0.1:8050"])

# uncomment to run locally
app.run_server(debug=config_data["DEBUG"], host="0.0.0.0", port="8050")
