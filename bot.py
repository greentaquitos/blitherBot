
import discord
import asyncio
import sqlite3
import string
import random
import traceback
import re
import datetime
import pprint

from exceptions import FeedbackError
import bothelp

#todo:

	# ===== IDEAS

	# colors change automatically based on rank
	# command to get info on users
	# more stats on bestowment announcements!



class Bot():
	def __init__(self, debug=True):
		self.debug = debug
		self.confirming = None
		self.do_bestow = True

		self.commands = []
		
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

	async def public_log(self, m):
		self.log(m)
		if self.debug:
			return
		await self.public_log_channel.send(embed=discord.Embed(description=m))

	async def private_log(self, m):
		self.log(m)
		if self.debug:
			return
		await self.private_log_channel.send(m)

	async def private_alert(self, m):
		self.log(m)
		if self.debug:
			return
		m = self.taq.mention + "\n" + m
		await self.private_log_channel.send(m)

	# PROPERTIES

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
		return mrb

	@property
	def active_bestowment(self):
		cur = self.db.execute("SELECT rowid, bestowee FROM bestowments ORDER BY given_to_bestower_at DESC LIMIT 1")
		ab = [[q[0],q[1]] for q in cur.fetchall()]
		ab = ab[0][0] if len(ab) > 0 and not ab[0][1] else None
		return ab

	# EVENTS

	async def on_ready(self):
		self.active_role = discord.utils.get(self.guild.roles, id=self.config.ACTIVE_ROLE)
		self.bestower_role = discord.utils.get(self.guild.roles, id=self.config.BESTOWER_ROLE)
		self.bestowment_channel = discord.utils.get(self.guild.channels, id=self.config.BESTOWMENT_CHANNEL)
		self.lobby_channel = discord.utils.get(self.guild.channels, id=self.config.LOBBY_CHANNEL)
		self.public_log_channel = discord.utils.get(self.guild.channels, id=self.config.PUBLIC_LOG_CHANNEL)
		self.private_log_channel = discord.utils.get(self.guild.channels, id=self.config.PRIVATE_LOG_CHANNEL)
		self.taq = self.guild.get_member(self.config.TAQ)
		self.eg = self.guild.get_member(self.config.EG)

		if not self.debug:
			await self.private_log("I'm back online!")
			await self.audit()

	async def on_message(self,m):
		if m.author.bot:
			return

		try:
			self.save_message(m)
			
			if self.active_role not in m.author.roles:
				await m.author.add_roles(self.active_role)
				await self.private_log("added active role to "+m.author.name)

		
		except Exception as e:
			await self.private_alert(traceback.format_exc())

	async def on_member_join(self,member):
		if member.bot:
			return

		if self.active_bestowment:
			await self.resolve_active_bestowment(member)
		else:
			self.do_bestow = False
			await self.private_alert("no active bestowment for "+member.name+"!")

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
				await self.private_log("removed active role from "+m.name)

	# BESTOWMENT

	async def bestow(self):
		if not self.do_bestow:
			return

		await self.check_for_inactivity()

		for m in self.bestower_role.members[:]:
			await m.remove_roles(self.bestower_role)

		if len(self.eligible_bestowers) < 1:
			await self.private_alert("no eligible bestowers!")
			return

		bestower = self.draw_from_raffle()
		await bestower.add_roles(self.bestower_role)

		invite = await self.lobby_channel.create_invite(max_age=self.config.INVITE_DURATION,max_uses=1)

		await self.bestowment_channel.send(bestower.mention + ", behold! This is the one and only invite link in the server and it's all yours. You may use it to invite one person within the next three days.\n\n||`"+str(invite)+"`||")

		cursor = self.db.cursor()
		cursor.execute("INSERT INTO bestowments(link, bestower, given_to_bestower_at) VALUES(?,?,?)",[invite.url,bestower.id,invite.created_at])
		invite_number = str(cursor.lastrowid)
		self.db.commit()
		cursor.close()

		await self.public_log(bestower.mention+" has been chosen to bestow invite link #"+invite_number+".")

	async def resolve_active_bestowment(self, member):
		cursor = self.db.cursor()
		cursor.execute("UPDATE bestowments SET bestowee = ?, bestowee_joined_at = ? WHERE rowid = ?", [member.id,member.joined_at,self.active_bestowment])
		self.db.commit()
		cursor.close()

		await self.public_log("...and they chose "+member.mention+"! Welcome!")

		await self.bestow()

	async def audit(self):
		if not self.do_bestow:
			return

		cursor = self.db.execute("SELECT bestowee FROM bestowments")
		members = [q[0] for q in cursor.fetchall()]
		cursor.close()

		non_bestowees = []

		for m in self.guild.members:
			if m.id not in [self.config.TAQ,self.config.EG] and m.id not in members and not m.bot:
				non_bestowees.append(m)

		if len(non_bestowees) == 1 and self.active_bestowment:
			await self.resolve_active_bestowment(non_bestowees[0])
		elif len(non_bestowees) == 1:
			self.do_bestow = False
			await self.private_alert("Audit found no active bestowment!")
		elif len(non_bestowees) > 1:
			self.do_bestow = False
			await self.private_alert("Audit found more than one new member!")
		else:
			invites = await self.lobby_channel.invites()
			invites = [i for i in invites if i.inviter.id == self.client.user.id]
			if len(invites) < 1:
				await self.bestow()

		await asyncio.sleep(30)
		await self.audit()

	def draw_from_raffle(self):
		return random.choice(self.build_raffle())

	def build_raffle(self):
		mstats = self.compile_member_stats()
		raffle = []
		for m in mstats:
			for t in range(m['tickets']):
				raffle.append(m['m'])
		return raffle

	def compile_member_stats(self):
		members = self.eligible_bestowers
		member_stats = []
		for m in members:
			cursor = self.db.execute("SELECT rowid FROM bestowments WHERE bestower = ? OR bestowee = ? ORDER BY given_to_bestower_at DESC LIMIT 1", [m.id, m.id])
			touch = cursor.fetchall()[0][0]
			cursor = self.db.execute("SELECT COUNT(rowid) FROM bestowments WHERE bestower = ?",[m.id])
			bestowments = cursor.fetchall()[0][0]
			cursor.close()
			children = self.count_progeny_for(m.id)
			member_stats.append({'name':m.name,'id':m.id,'touch':touch,'bestowments':bestowments,'children':children,'m':m})

		max_touch = max([m['touch'] for m in member_stats])
		max_bestowments = max([m['bestowments'] for m in member_stats])
		max_children = max([m['children'] for m in member_stats])

		for m in member_stats:
			m['tickets'] = max_touch+max_bestowments+max_children-m['touch']-m['bestowments']-m['children']
		return member_stats


	def count_progeny_for(self,member_id):
		progeny = 0
		for c in self.get_children_for(member_id):
			progeny += 1
			progeny += self.count_progeny_for(c)
		return progeny

	def get_children_for(self,member_id):
		cursor = self.db.execute("SELECT bestowee FROM bestowments WHERE bestowee IS NOT NULL AND bestower = ?",[member_id])
		children = [c[0] for c in cursor.fetchall()]
		cursor.close()
		return children
