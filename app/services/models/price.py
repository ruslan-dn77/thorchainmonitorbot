import logging
import time
from dataclasses import dataclass
from typing import Dict

from services.lib.money import weighted_mean
from services.models.base import BaseModelMixin
from services.models.pool_info import PoolInfo
from services.models.time_series import BUSD_SYMBOL, BTCB_SYMBOL, USDT_SYMBOL


@dataclass
class RuneFairPrice:
    circulating: int = 500_000_000
    rune_vault_locked: int = 0
    real_rune_price: float = 0.0
    fair_price: float = 0.0
    tlv_usd: float = 0.0
    rank: int = 0

    @property
    def market_cap(self):
        return self.real_rune_price * self.circulating


REAL_REGISTERED_ATH = 1.18  # BUSD / Rune
REAL_REGISTERED_ATH_DATE = 1598958000  # 1 sept 2020 11:00 UTC


@dataclass
class PriceATH(BaseModelMixin):
    ath_date: int = REAL_REGISTERED_ATH_DATE
    ath_price: float = REAL_REGISTERED_ATH

    def is_new_ath(self, price):
        return price and float(price) > 0 and float(price) > self.ath_price


@dataclass
class PriceReport:
    price_1h: float = 0.0
    price_24h: float = 0.0
    price_7d: float = 0.0
    fair_price: RuneFairPrice = RuneFairPrice()
    last_ath: PriceATH = PriceATH()
    btc_real_rune_price: float = 0.0


class LastPriceHolder:
    def __init__(self):
        self.usd_per_rune = 1.0
        self.btc_per_rune = 0.000001
        self.pool_info_map: Dict[str, PoolInfo] = {}
        self.last_update_ts = 0

    def calculate_weighted_rune_price(self):
        stable_coins = [BUSD_SYMBOL, USDT_SYMBOL]

        prices, weights = [], []
        for stable_symbol in stable_coins:
            pool_info = self.pool_info_map.get(stable_symbol)
            if pool_info and pool_info.balance_rune > 0 and pool_info.asset_per_rune > 0:
                prices.append(pool_info.asset_per_rune)
                weights.append(pool_info.balance_rune)

        if prices:
            self.usd_per_rune = weighted_mean(prices, weights)
        else:
            logging.error(f'LastPriceHolder was unable to find any stable coin pools!')

    def update(self, new_pool_info_map: Dict[str, PoolInfo]):
        self.pool_info_map = new_pool_info_map.copy()
        self.calculate_weighted_rune_price()
        self.btc_per_rune = self.pool_info_map[BTCB_SYMBOL].asset_per_rune
        self.last_update_ts = time.time()

    @property
    def pool_names(self):
        return set(self.pool_info_map.keys())

    def usd_per_asset(self, pool):
        runes_per_asset = self.pool_info_map[pool].runes_per_asset
        return self.usd_per_rune * runes_per_asset
