import json
import logging
from dataclasses import dataclass

from services.lib.db import DB
from services.models.base import BaseModelMixin


@dataclass
class ThorInfo(BaseModelMixin):
    cap: int
    stacked: int
    price: float

    @classmethod
    def zero(cls):
        return cls(0, 0, 0)

    @classmethod
    def error(cls):
        return cls(-1, -1, 1e-10)

    @property
    def cap_usd(self):
        return self.price * self.cap

    @property
    def is_ok(self):
        return self.cap >= 1 and self.stacked >= 1

    KEY_INFO = 'th_info'

    @classmethod
    async def get_old_cap(cls, db: DB):
        try:
            j = await db.redis.get(cls.KEY_INFO)
            return ThorInfo.from_json(j)
        except (TypeError, ValueError, AttributeError, json.decoder.JSONDecodeError):
            logging.exception('get_old_cap error')
            return ThorInfo.error()

    async def save(self, db: DB):
        r = await db.get_redis()
        await r.set(self.KEY_INFO, self.as_json)
