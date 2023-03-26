#!/usr/bin/env LC_ALL=en_US.UTF-8 /usr/local/bin/python3.6

from config import config
from bot import Bot

import sys
sys.stdout = open(1, 'w', encoding='utf-8', closefd=False)

global b


if __name__ == "__main__":
    b = Bot(False)
else:
	exit()

@b.client.event
async def on_ready():
	await b.on_ready()

@b.client.event
async def on_message(message):
	await b.on_message(message)

@b.client.event
async def on_member_join(member):
	await b.on_member_join(member)

b.start_bot(config)
