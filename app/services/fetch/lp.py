import asyncio
import logging

from services.fetch.pool_price import PoolPriceFetcher
from services.lib.depcont import DepContainer
from services.models.stake_info import CurrentLiquidity, StakePoolReport, StakeDayGraphPoint

MIDGARD_MY_POOLS = 'https://chaosnet-midgard.bepswap.com/v1/stakers/{address}'
MIDGARD_POOL_LIQUIDITY = 'https://chaosnet-midgard.bepswap.com/v1/pools/detail?asset={pools}&view=simple'

ASGARD_CONSUMER_WEEKLY_HISTORY = 'https://asgard-consumer.vercel.app/api/weekly?address={address}&pool={pool}'
ASGARD_CONSUMER_CURRENT_LIQUIDITY = \
    'https://asgard-consumer.vercel.app/api/v2/history/liquidity?address={address}&pools={pool}'


class LiqPoolFetcher:
    def __init__(self, deps: DepContainer):
        self.deps = deps
        self.logger = logging.getLogger('LiqPoolFetcher')

    async def get_my_pools(self, address):
        url = MIDGARD_MY_POOLS.format(address=address)
        self.logger.info(f'get {url}')
        async with self.deps.session.get(url) as resp:
            j = await resp.json()
            try:
                my_pools = j['poolsArray']
                return my_pools
            except KeyError:
                return None

    async def fetch_one_pool_liquidity_info(self, address, pool):
        url = ASGARD_CONSUMER_CURRENT_LIQUIDITY.format(address=address, pool=pool)
        self.logger.info(f'get {url}')
        async with self.deps.session.get(url) as resp:
            j = await resp.json()
            return CurrentLiquidity.from_asgard(j)

    async def fetch_one_pool_weekly_chart(self, address, pool):
        url = ASGARD_CONSUMER_WEEKLY_HISTORY.format(address=address, pool=pool)
        self.logger.info(f'get {url}')
        async with self.deps.session.get(url) as resp:
            j = await resp.json()
            try:
                return pool, [StakeDayGraphPoint.from_asgard(point) for point in j['data']]
            except TypeError:
                self.logger.warning(f'no weekly chart for {pool} @ {address}')
                return pool, None

    async def fetch_all_pools_weekly_charts(self, address, pools):
        weekly_charts = await asyncio.gather(*[self.fetch_one_pool_weekly_chart(address, pool) for pool in pools])
        return dict(weekly_charts)

    async def fetch_all_pool_liquidity_info(self, address, my_pools=None) -> dict:
        my_pools = (await self.get_my_pools(address)) if my_pools is None else my_pools
        cur_liquidity = await asyncio.gather(*(self.fetch_one_pool_liquidity_info(address, pool) for pool in my_pools))
        return {c.pool: c for c in cur_liquidity}

    async def fetch_stake_report_for_pool(self, liq: CurrentLiquidity, ppf: PoolPriceFetcher) -> StakePoolReport:
        try:
            # get prices at the moment of first stake
            usd_per_rune_start, usd_per_asset_start = await ppf.get_usd_per_rune_asset_per_rune_by_day(
                liq.pool,
                liq.first_stake_ts)
        except Exception as e:
            self.logger.exception(e, exc_info=True)
            usd_per_rune_start, usd_per_asset_start = None, None

        d = self.deps
        stake_report = StakePoolReport(d.price_holder.usd_per_asset(liq.pool),
                                       d.price_holder.usd_per_rune,
                                       usd_per_asset_start, usd_per_rune_start,
                                       liq,
                                       d.price_holder.pool_info_map.get(liq.pool))
        return stake_report
