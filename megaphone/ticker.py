from decimal import Decimal
import grequests
import numpy as np


class TickerError(RuntimeError):
    pass


class Ticker(object):
    """
    Return ticker values.
    """
    URLS = {
        "btc-e": "https://btc-e.com/api/2/%s/ticker",
        "bitfinex": "https://api.bitfinex.com/v1/pubticker/%s",
        "bittrex": "https://bittrex.com/api/v1.1/public/getmarketsummary?market=%s",
        "bitstamp": "https://www.bitstamp.net/api/v2/ticker/%s",
        "coinbase": "https://api.exchange.coinbase.com/products/%s/ticker",
        "poloniex": "https://poloniex.com/public?command=returnTicker&currencyPair=%s"
    }
    RESPONSES = {
        "price": {
            "btc-e": "avg",
            "bitfinex": "last_price",
            "bittrex": "Last",
            "bitstamp": "last",
            "coinbase": "price",
            "poloniex": "last"
        },
        "volume": {
            "btc-e": "vol_cur",
            "bitfinex": "volume",
            "bittrex": "BaseVolume",
            "bitstamp": "volume",
            "coinbase": "volume",
            "poloniex": "baseVolume"
        }
    }

    @staticmethod
    def get_ticker_symbol(currency_pair, exchange_name):
        """
        Return ticker symbol used by an exchange.

        :param currency_pair: (Crypto)currency pair e.g. btc/usd
        :type currency_pair: str
        :param exchange_name: (Crypto)currency exchange name e.g. coinbase
        :type currency_pair: str

        :return: ticker symbol in format used by the exchange
        :rtype str
        """
        if exchange_name not in Ticker.URLS.keys():
            raise TickerError("Exchange %s not supported!")
        if "/" not in currency_pair:
            raise TickerError("Currency pair incorrect format."
                              "Use xxx/yyy e.g. btc/usd!")
        if exchange_name in ["bittrex", "poloniex"]:
            currency_pair = currency_pair.replace("usd", "usdt").upper()
        if exchange_name == "bittrex":
            return "{1}-{0}".format(*currency_pair.split("/"))
        elif exchange_name == "poloniex":
            return "{1}_{0}".format(*currency_pair.split("/"))
        elif exchange_name in ["btc-e"]:
            return currency_pair.replace("/", "_")
        elif exchange_name in ["coinbase"]:
            return currency_pair.replace("/", "-")
        else:
            return currency_pair.replace("/", "")

    @staticmethod
    def price(pair):
        """
        Return VWAP price of a cryptocurrency pair.

        VWAP: Volume Weighted Average Price means the exchange with more volume
        has bigger influence on average price of the cryptocurrency pair.

        :param pair: Cryptocurrency pair. E.g. btcusd
        :type pair: str
        :return: VWAP price
        :rtype float
        """
        prices = {}
        urls = dict((k, v % Ticker.get_ticker_symbol(pair, k))
                    for k, v in Ticker.URLS.items())
        urls_rev = dict((v, k) for k, v in urls.items())
        rs = (grequests.get(u, timeout=2) for u in urls.values())
        responses = list(grequests.map(rs, exception_handler=lambda x, y: ""))

        valid_responses = [x for x in responses
                           if hasattr(x, "status_code")
                           and x.status_code == 200
                           and x.json()]

        for response in valid_responses:
            if "error" in response.json() and \
                    "invalid" in response.json()["error"]:
                continue
            exchange = urls_rev[response.url]
            if exchange in ["okcoin", "btc-e"]:
                data = response.json()["ticker"]
            elif exchange == "bittrex":
                data = response.json()["result"][0]
            elif exchange == "poloniex":
                poloniex_symbol = Ticker.get_ticker_symbol(pair, "poloniex")
                data = response.json()[poloniex_symbol]
            else:
                data = response.json()
            price = float(data[Ticker.RESPONSES["price"][exchange]])
            volume = float(data[Ticker.RESPONSES["volume"][exchange]])
            prices[exchange] = {"price": price,
                                "volume": volume}

        if len(prices) == 0:
            raise TickerError("Could not fetch any %s price." % pair)

        return np.average([x['price'] for x in prices.values()],
                          weights=[x['volume'] for x in prices.values()])

    @staticmethod
    def calc_spread(bid, ask):
        return (1 - (Decimal(bid) / Decimal(ask))) * 100


class Gold(object):
    """
    Return value of 1mg Gold in USD.
    """

    URL = "http://data-asg.goldprice.org/GetData/USD-XAU/1"
    GRAM_PER_OZ = 31.1034768

    @staticmethod
    def price_oz():
        """
        Return price of 1 ounce of Gold in USD

        :return: XAU OZ price in USD, 0.0 if incorrect response
        :rtype float
        """
        rs = grequests.get(Gold.URL, timeout=2)
        response = grequests.map([rs], exception_handler=lambda x, y: "")[0]
        if hasattr(response, "status_code") and response.status_code == 200:
            return float(response.json()[0].split(",")[1])
        return 0.0

    @staticmethod
    def price_mg():
        """
        Return price of 1mg of Gold in USD

        :return: XAU 1mg price in USD
        :rtype: float
        """
        return Gold.price_oz() / Gold.GRAM_PER_OZ / 1000.0
