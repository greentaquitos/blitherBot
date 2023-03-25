
import discord
import asyncio
import sqlite3
import string
import random
import traceback
import re
import datetime

from exceptions import FeedbackError
import bothelp

#todo:

	# a new person landing (via the relevant link?) triggers the bestower method

	# an invite expiring triggers the bestower method

	# readying and noticing there's no invite links triggers the bestower method

	# add alert errors for me
	# add public logging




class Bot():
	def __init__(self, debug=True):
		self.debug = debug
		self.confirming = None

		self.commands = []
		
		if not debug:
			self.setup_db()
			self.setup_discord()

	# SETUP

	def setup_db(self):
		con = self.db = sqlite3.connect("db.db")
		schema = {
			"messages (sent_at int, sent_by int unique)",
			"bestowments (link text, bestower int, bestowee int, given_to_bestower_at int, bestowee_joined_at int)"
		}

		for t in schema:
			try:
				con.execute("CREATE TABLE IF NOT EXISTS "+t)
			except Exception as e:
				self.log("Error with SQL:\n"+t+"\n"+str(e))
				break

		con.commit()

	def setup_discord(self):
		intents = discord.Intents.default()
		intents.members = True
		self.client = discord.Client(intents=intents)

	def start_bot(self,config):
		self.config = config
		self.client.run(self.config.TOKEN)

	# UTIL

	def log(self, m):
		print(m)

	def debug_log(self, m):
		if self.debug:
			self.log(m)

	@property
	def guild(self):
		return self.client.get_guild(self.config.GUILD)

	@property
	def eligible_bestowers(self):
		return [m for m in self.guild.members if not m.bot and self.active_role in m.roles and m.id != self.most_recent_bestower]

	@property
	def most_recent_bestower(self):
		cur = self.db.execute("SELECT bestower FROM bestowments ORDER BY given_to_bestower_at DESC LIMIT 1")
		mrb = [q[0] for q in cur.fetchall()]
		mrb = mrb[0] if len(mrb) > 0 else None
		self.log("mrb-er is "+str(mrb))
		return mrb

	# EVENTS

	async def on_ready(self):
		self.log('rhizone ready')
		self.active_role = discord.utils.get(self.guild.roles, id=self.config.ACTIVE_ROLE)
		self.bestower_role = discord.utils.get(self.guild.roles, id=self.config.BESTOWER_ROLE)
		self.bestowment_channel = discord.utils.get(self.guild.channels, id=self.config.BESTOWMENT_CHANNEL)
		self.lobby_channel = discord.utils.get(self.guild.channels, id=self.config.LOBBY_CHANNEL)

	async def on_message(self,m):
		if m.author.bot:
			return

		try:
			self.save_message(m)
			
			if self.active_role not in m.author.roles:
				await m.author.add_roles(self.active_role)
				self.log("added active role to "+m.author.name)

		
		except Exception as e:
			self.log(traceback.format_exc())



	# SAVING

	def save_message(self,m):
		cursor = self.db.cursor()
		sent_by = m.author.id
		sent_at = m.created_at
		cursor.execute("INSERT OR REPLACE INTO messages (sent_at, sent_by) VALUES (?,?)",[sent_at, sent_by])
		self.db.commit()
		cursor.close()

	# ACTIVITY

	async def check_for_inactivity(self):
		one_week_ago = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S.%f")
		cur = self.db.execute("SELECT sent_by, sent_at FROM messages")
		members = [(q[0],q[1]) for q in cur.fetchall()]

		cur.close()

		for i in members:
			if i[1] > one_week_ago:
				continue

			m = self.guild.get_member(i[0])
			if m:
				await m.remove_roles(self.active_role)
				self.log("removed active role from "+m.name)

	# BESTOWMENT

	async def bestow(self):
		await self.check_for_inactivity()

		for m in self.bestower_role.members[:]:
			await m.remove_roles(self.bestower_role)

		if len(self.eligible_bestowers) < 1:
			self.log("no eligible bestowers")
			return

		bestower = random.choice(self.eligible_bestowers)
		await bestower.add_roles(self.bestower_role)

		invite = await self.lobby_channel.create_invite(max_age=self.config.INVITE_DURATION,max_uses=1)

		await self.bestowment_channel.send(bestower.mention + ", behold! This is the one and only invite link in the server. Use it wisely.\n\n||`"+str(invite)+"`||")

		cursor = self.db.cursor()
		cursor.execute("INSERT INTO bestowments(link, bestower, given_to_bestower_at) VALUES(?,?,?)",[invite.url,bestower.id,invite.created_at])
		self.db.commit()
		cursor.close()
