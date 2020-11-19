import asyncio
import logging
import random
import time

from localization import LocalizationManager, BaseLocalization
from services.lib.config import Config
from services.lib.cooldown import CooldownTracker
from services.lib.db import DB
from services.fetch.base import INotified
from services.models.price import RuneFairPrice, PriceReport, PriceATH
from services.models.time_series import PriceTimeSeries, RUNE_SYMBOL
from services.notify.broadcast import Broadcaster, telegram_chats_from_config
from services.lib.money import pretty_money, calc_percent_change
from services.lib.datetime import MINUTE, HOUR, DAY, parse_timespan_to_seconds


class PriceNotifier(INotified):
    ATH_KEY = 'runeATH'

    def __init__(self, cfg: Config, db: DB, broadcaster: Broadcaster, loc_man: LocalizationManager):
        self.logger = logging.getLogger('PriceNotification')
        self.broadcaster = broadcaster
        self.loc_man = loc_man
        self.cfg = cfg
        self.db = db
        self.cd = CooldownTracker(db)
        self.global_cd = parse_timespan_to_seconds(cfg.price.global_cd)
        self.change_cd = parse_timespan_to_seconds(cfg.price.change_cd)
        self.percent_change_threshold = cfg.price.percent_change_threshold
        self.time_series = PriceTimeSeries(RUNE_SYMBOL, db)
        self.ath_stickers = cfg.price.ath.stickers
        self.ath_cooldown = parse_timespan_to_seconds(cfg.price.ath.cooldown)

    CD_KEY_PRICE_NOTIFIED = 'price_notified'
    CD_KEY_PRICE_RISE_NOTIFIED = 'price_notified_rise'
    CD_KEY_PRICE_FALL_NOTIFIED = 'price_notified_fall'
    CD_KEY_ATH_NOTIFIED = 'ath_notified'

    async def historical_get_triplet(self):
        price_1h, price_24h, price_7d = await asyncio.gather(
            self.time_series.select_average_ago(HOUR, tolerance=MINUTE * 5),
            self.time_series.select_average_ago(DAY, tolerance=MINUTE * 30),
            self.time_series.select_average_ago(DAY * 7, tolerance=HOUR * 1)
        )
        return price_1h, price_24h, price_7d

    async def send_ath_sticker(self):
        if not self.ath_stickers:
            return
        sticker = random.choice(self.ath_stickers)
        user_lang_map = telegram_chats_from_config(self.cfg, self.loc_man)
        await self.broadcaster.broadcast(user_lang_map.keys(), sticker, message_type='sticker')

    async def do_notify_price_table(self, fair_price, hist_prices, ath):
        await self.cd.do(self.CD_KEY_PRICE_NOTIFIED)

        user_lang_map = telegram_chats_from_config(self.cfg, self.loc_man)

        async def message_gen(chat_id):
            loc: BaseLocalization = user_lang_map[chat_id]
            return loc.price_change(PriceReport(
                *hist_prices, fair_price
            ), ath=ath)

        await self.broadcaster.broadcast(user_lang_map.keys(), message_gen)
        if ath:
            await self.send_ath_sticker()

    async def handle_new_price(self, fair_price: RuneFairPrice):
        hist_prices = await self.historical_get_triplet()
        price = fair_price.real_rune_price

        price_1h = hist_prices[0]
        send_it = False
        if price_1h:
            percent_change = calc_percent_change(price_1h, price)

            if abs(percent_change) >= self.percent_change_threshold:  # significant price change
                if percent_change > 0 and (await self.cd.can_do(self.CD_KEY_PRICE_RISE_NOTIFIED, self.change_cd)):
                    self.logger.info(f'price rise {pretty_money(percent_change)} %')
                    await self.cd.do(self.CD_KEY_PRICE_RISE_NOTIFIED)
                    send_it = True
                elif percent_change < 0 and (await self.cd.can_do(self.CD_KEY_PRICE_FALL_NOTIFIED, self.change_cd)):
                    self.logger.info(f'price fall {pretty_money(percent_change)} %')
                    await self.cd.do(self.CD_KEY_PRICE_FALL_NOTIFIED)
                    send_it = True

        if not send_it and await self.cd.can_do(self.CD_KEY_PRICE_NOTIFIED, self.global_cd):
            self.logger.info('no price change but it is long time elapsed (global cd), so notify anyway')
            send_it = True

        if send_it:
            await self.do_notify_price_table(fair_price, hist_prices, ath=False)

    async def get_prev_ath(self) -> PriceATH:
        try:
            await self.db.get_redis()
            ath_str = await self.db.redis.get(self.ATH_KEY)
            if ath_str is None:
                return PriceATH()
            else:
                return PriceATH.from_json(ath_str)
        except (TypeError, ValueError, AttributeError):
            return PriceATH()

    async def reset_ath(self):
        await self.db.redis.delete(self.ATH_KEY)

    async def update_ath(self, ath: PriceATH):
        if ath.ath_price > 0:
            await self.db.get_redis()
            await self.db.redis.set(self.ATH_KEY, ath.as_json)

    async def handle_ath(self, fair_price):
        ath = await self.get_prev_ath()
        price = fair_price.real_rune_price
        if ath.is_new_ath(price):
            await self.update_ath(PriceATH(
                int(time.time()), price
            ))

            if await self.cd.can_do(self.CD_KEY_ATH_NOTIFIED, self.ath_cooldown):
                await self.cd.do(self.CD_KEY_ATH_NOTIFIED)
                await self.cd.do(self.CD_KEY_PRICE_RISE_NOTIFIED)  # prevent 2 notifications

                hist_prices = await self.historical_get_triplet()
                await self.do_notify_price_table(fair_price, hist_prices, ath=True)
                return True

        return False

    async def on_data(self, fprice: RuneFairPrice):
        # fprice.real_rune_price = 1.19  # debug!!!
        if not await self.handle_ath(fprice):
            await self.handle_new_price(fprice)

    async def on_error(self, e):
        return await super().on_error(e)
