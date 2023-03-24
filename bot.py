
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

	# bestower method gives bestower role, sends the invite link in the bestowment channel

	# a new person landing (via the relevant link?) triggers the bestower method

	# an invite expiring triggers the bestower method
	
	# the bestower method checks the whole server for inactivity before bestowing




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

	# EVENTS

	async def on_ready(self):
		self.log('rhizone ready')
		self.guild = self.client.get_guild(self.config.GUILD)
		self.active_role = discord.utils.get(self.guild.roles, id=self.config.ACTIVE_ROLE)
		await self.check_for_inactivity()

	async def on_message(self,m):
		if m.author.bot:
			return

		try:
			self.save_message(m)
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
		one_week_ago = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=27)).strftime("%Y-%m-%d %H:%M:%S.%f")
		cur = self.db.execute("SELECT sent_by, sent_at FROM messages")
		members = [(q[0],q[1]) for q in cur.fetchall()]

		cur.close()

		for i in members:
			if i[1] > one_week_ago:
				continue

			m = self.guild.get_member(i[0])
			await m.remove_roles(self.active_role)
			self.log("removed active role from "+m.name)
