import logging
from fetcher import InfoFetcher, ThorInfo
from config import Config, DB
from aiogram import Bot, Dispatcher, executor, types
from aiogram.types import *
from message_format import notify_when_cap_changed, welcome_message, BUTTON_GET_UPDATE


class MyFetcher(InfoFetcher):
    def __init__(self, cfg: Config, db: DB):
        super().__init__(cfg)
        self.db = db

    async def on_got_info(self, info: ThorInfo):
        old_info = await self.db.get_old_cap()
        reached_ath = await self.db.update_ath(info.price)
        await self.db.set_cap(info)

        if info.cap != old_info.cap:
            await notify_when_cap_changed(bot, self.db, old_info, info, reached_ath)


logging.basicConfig(level=logging.INFO)

cfg = Config()
db = DB()
fetcher = MyFetcher(cfg, db)

bot = Bot(token=cfg.telegram.bot.token, parse_mode=ParseMode.HTML)
dp = Dispatcher(bot)


@dp.message_handler(commands=['start', 'help'])
async def send_welcome(message: Message):
    welcome_text = await welcome_message(db)
    await message.answer(welcome_text, reply_markup=ReplyKeyboardMarkup(keyboard=[[
        KeyboardButton(BUTTON_GET_UPDATE)
    ]], resize_keyboard=True), disable_web_page_preview=True)
    my_id = message.from_user.id
    await db.add_user(my_id)


@dp.message_handler()
async def echo(message: Message):
    if message.text == BUTTON_GET_UPDATE:
        await send_welcome(message)
    else:
        await message.reply("Not supported")


async def fetcher_task():
    global fetcher
    fetcher = MyFetcher(cfg, db)
    await db.get_redis()
    await fetcher.fetch_loop()


if __name__ == '__main__':
    dp.loop.create_task(fetcher_task())
    executor.start_polling(dp, skip_updates=True)