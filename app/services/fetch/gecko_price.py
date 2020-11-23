import logging

import aiohttp
from aioredis import ReplyError
from tqdm import tqdm

from services.models.time_series import PriceTimeSeries, RUNE_SYMBOL

COIN_CHART_GECKO = "https://api.coingecko.com/api/v3/coins/thorchain/market_chart?vs_currency=usd&days={days}"
COIN_RANK_GECKO = "https://api.coingecko.com/api/v3/coins/thorchain?" \
                  "tickers=false&market_data=false&community_data=false&developer_data=false"


async def get_rune_chart(days):
    async with aiohttp.ClientSession() as session:
        async with session.get(COIN_CHART_GECKO.format(days=days)) as resp:
            j = await resp.json()
            return j['prices']


async def fill_rune_price_from_gecko(db):
    logging.warning('fill_rune_price_from_gecko is called!')
    gecko_data8 = await get_rune_chart(8)
    gecko_data1 = await get_rune_chart(1)

    price_chart = gecko_data8 + gecko_data1
    price_chart.sort(key=lambda p: p[0])

    series = PriceTimeSeries(RUNE_SYMBOL, db)
    await series.clear()

    for ts, price in tqdm(price_chart):
        ident = f'{ts}-0'
        try:
            await series.add(message_id=ident, price=price)
        except ReplyError:
            pass


async def gecko_info(session):
    async with session.get(COIN_RANK_GECKO) as resp:
        j = await resp.json()
        return j