
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
from discord.ext import tasks
import bothelp


class Bot():
	def __init__(self, debug=True):
		self.debug = debug
		self.confirming = None
		self.do_bestow = True

		self.commands = [
			("help", self.help),
			("stats", self.stats),
			("pass", self.skip),
			("lineage", self.lineage),
			("liniage", self.liniage),
			("progeny", self.progeny),
			("progeni", self.progeni),
			("test", self.test)
		]
		
		self.setup_db()
		self.setup_discord()

	# SETUP

	def setup_db(self):
		con = self.db = sqlite3.connect("db.db")
		schema = {
			"messages (sent_at int, sent_by int unique)",
			"bestowments (link text, bestower int, bestowee int, given_to_bestower_at int, bestowee_joined_at int, released_at int)",
			"inactivity (bestowment_id int, member int unique)"
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
		await self.private_log_channel.send(embed=discord.Embed(description=m))

	async def private_alert(self, m):
		self.log(m)
		if self.debug:
			return
		await self.private_log_channel.send(self.taq.mention,embed=discord.Embed(description=m))

	def nth(self,num):
		last_char = str(num)[-1]
		sec_last_char = str(num)[-2] if len(str(num)) > 1 else None
		if last_char == '1' and sec_last_char != '1':
			return str(num)+'st'
		elif last_char == '2' and sec_last_char != '1':
			return str(num)+'nd'
		elif last_char == '3' and sec_last_char != '1':
			return str(num)+'rd'
		else:
			return str(num)+'th'

	def pronoun_for(self,member,which='subject'):
		pronouns = []
		if self.he_role in member.roles:
			word = 'he' if which == 'subject' else 'him'
			pronouns.append(word)
		if self.she_role in member.roles:
			word = 'she' if which == 'subject' else 'her'
			pronouns.append(word)
		if self.they_role in member.roles or len(pronouns) < 1:
			word = 'they' if which == 'subject' else 'them'
			pronouns.append(word)
		return random.choice(pronouns)

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

	@property
	def audit_count(self):
		if not hasattr(self,'_audit_count'):
			self._audit_count = 0
		else:
			self._audit_count += 1
		return self._audit_count

	# EVENTS

	async def on_ready(self):
		self.active_role = discord.utils.get(self.guild.roles, id=self.config.ACTIVE_ROLE)
		self.bestower_role = discord.utils.get(self.guild.roles, id=self.config.BESTOWER_ROLE)
		self.he_role = discord.utils.get(self.guild.roles, id=self.config.HE_ROLE)
		self.she_role = discord.utils.get(self.guild.roles, id=self.config.SHE_ROLE)
		self.they_role = discord.utils.get(self.guild.roles, id=self.config.THEY_ROLE)

		self.bestowment_channel = discord.utils.get(self.guild.channels, id=self.config.BESTOWMENT_CHANNEL)
		self.lobby_channel = discord.utils.get(self.guild.channels, id=self.config.LOBBY_CHANNEL)
		self.public_log_channel = discord.utils.get(self.guild.channels, id=self.config.PUBLIC_LOG_CHANNEL)
		self.private_log_channel = discord.utils.get(self.guild.channels, id=self.config.PRIVATE_LOG_CHANNEL)
		
		self.taq = self.guild.get_member(self.config.TAQ)
		self.eg = self.guild.get_member(self.config.EG)

		if not self.debug:
			await self.private_log("I'm back online! (v3.23)")
			self.audit.start()

	async def on_message(self,m):
		if m.author.bot:
			return

		try:
			if m.content != 'bot pass':
				self.save_message(m)
				
				if self.active_role not in m.author.roles:
					await m.author.add_roles(self.active_role)
					await self.private_log("added active role to "+m.author.name)

		
		except Exception as e:
			await self.private_alert(traceback.format_exc())


		try:
			if m.content.lower().startswith('bot '):
				await self.parse_command(m)
			else:
				respondable = False

		except FeedbackError as e:
			await self.private_alert(f"Error responding to message: {e}")

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

	# COMMANDS

	async def parse_command(self,m):
		for command,method in self.commands:
			if m.content[4:].lower().startswith(command):
				await method(m)
				return

	async def help(self,m):
		reply = bothelp.default
		await m.reply(embed=discord.Embed(description=reply), mention_author=False)

	async def stats(self,m):
		arguments = m.content[10:]
		if m.channel.id not in self.config.SPAM_CHANNELS:
			await m.reply(embed=discord.Embed(description="This command only works in designated spam channels."))
			return
		await self.print_member_stats(m,arguments)

	async def skip(self,m):
		if self.bestower_role not in m.author.roles:
			await m.reply(embed=discord.Embed(description="Only the bestower can use this command."))
			return
		
		invites = await self.lobby_channel.invites()
		invites = [i for i in invites if i.inviter.id == self.client.user.id and not i.revoked]
		for i in invites:
			await i.delete()

		they = self.pronoun_for(m.author)

		await self.public_log(f"...and {they} chose to abstain.")
		await self.bestow()

	async def progeni(self,m):
		await self.progeny(m,True)

	async def progeny(self,m,showall=False):
		arguments = m.content[12:]
		if m.channel.id not in self.config.SPAM_CHANNELS:
			await m.reply(embed=discord.Embed(description="This command only works in designated spam channels."))
			return
		target = self.select_target(arguments, m)
		if not target:
			await m.reply(embed=discord.Embed(description="Could not find that member."))
			return

		family_tree = self.print_progeny_for(target.id,showall=showall)
		footer = ""
		if family_tree == "":
			family_tree = f"No progeny found for {target.mention}"
		else:
			footer = f"Showing progeny for {target.name}"
		await m.reply(embed=discord.Embed(description=family_tree).set_footer(text=footer))

	
	async def liniage(self,m):
		await self.lineage(m,showall=True)

	async def lineage(self,m,showall=False):
		arguments = m.content[12:]
		if m.channel.id not in self.config.SPAM_CHANNELS:
			await m.reply(embed=discord.Embed(description="This command only works in designated spam channels."))
			return
		await m.reply(embed=discord.Embed(description=self.print_lineage(arguments,m,showall)))

	def print_lineage(self, arguments, m, showall=False):
		target = self.select_target(arguments, m)
		if not target:
			return "Could not find that member."
		parents = [target]
		while True:
			parent = self.get_parent_for(parents[-1])
			if parent == None:
				break
			parents.append(parent)
		parents.reverse()
		return '\n-> '.join(f"#{self.get_invite_number_for(p)} {self.print_name_for(p.id,showall)}" for p in parents)

	def select_target(self, arguments, m):
		arguments = arguments.lower()
		if len(arguments) < 1:
			target = m.author
		else:
			potential_targets = []
			for m in self.guild.members:
				if m.bot:
					continue
				if m.name.lower() == arguments:
					potential_targets.append([m,'exact name'])
				elif m.display_name.lower() == arguments:
					potential_targets.append([m, 'exact display name'])
				elif m.name.lower().startswith(arguments):
					potential_targets.append([m,'name'])
				elif m.display_name.lower().startswith(arguments):
					potential_targets.append([m,'display_name'])

			if len(potential_targets) < 1:
				return None

			if any(i[1] == 'exact name' for i in potential_targets):
				target_type = 'exact name'
			elif any(i[1] == 'exact display name' for i in potential_targets):
				target_type = 'exact display name'
			elif any(i[1] == 'name' for i in potential_targets):
				target_type = 'name'
			else:
				target_type = 'display_name'

			if target_type in ['name', 'exact name']:
				potential_targets.sort(key=lambda x:len(x[0].name))
			else:
				potential_targets.sort(key=lambda x:len(x[0].display_name))

			for t in potential_targets:
				if t[1] == target_type:
					target = t[0]
					break
		return target

	def get_parent_for(self,member):
		cur = self.db.execute("SELECT bestower FROM bestowments WHERE bestowee = ? AND bestower != bestowee",[member.id])
		parent = [q[0] for q in cur.fetchall()]
		parent_m = None
		if parent:
			parent_m = self.guild.get_member(parent[0])
			if not parent_m:
				class Parent:
					def __init__(self,my_id):
						self.id = my_id
						self.mention = f"<@{my_id}>"
				parent_m = Parent(parent[0])

		return parent_m

	def get_invite_number_for(self,member):
		cur = self.db.execute("SELECT rowid FROM bestowments WHERE bestowee = ? AND bestower != bestowee",[member.id])
		inv_num = [q[0] for q in cur.fetchall()]
		return inv_num[0] if inv_num else 0

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
				cursor = self.db.cursor()
				cursor.execute("INSERT OR REPLACE INTO inactivity (bestowment_id, member) VALUES (?,?)",[self.active_bestowment, m.id])
				self.db.commit()
				cursor.close()

	# BESTOWMENT

	async def bestow(self):
		if not self.do_bestow:
			return
		self.do_bestow = False

		await self.check_for_inactivity()

		for m in self.bestower_role.members[:]:
			await m.remove_roles(self.bestower_role)

		if len(self.eligible_bestowers) < 1:
			await self.private_alert("no eligible bestowers!")
			return

		mstats = self.compile_member_stats()
		bestower = self.draw_from_raffle()
		await bestower.add_roles(self.bestower_role)

		invite = await self.lobby_channel.create_invite(max_age=self.config.INVITE_DURATION,max_uses=1)

		await self.bestowment_channel.purge(check=lambda m: m.author.bot)
		await self.bestowment_channel.send(bestower.mention,embed=discord.Embed(description=str(invite)+"\n\nBehold! This is the only invite link in the server, good for exactly one use.\n\nYou may share it with whomever you like or say `bot pass` to hand the duty of bestowment off to someone else.\n\nYou have two days.\n").set_footer(icon_url=random.choice(self.guild.emojis).url,text="The internet is counting on you"))

		cursor = self.db.cursor()
		cursor.execute("INSERT INTO bestowments(link, bestower, given_to_bestower_at) VALUES(?,?,?)",[invite.url,bestower.id,invite.created_at])
		invite_number = str(cursor.lastrowid)
		self.db.commit()
		cursor.close()

		mstats.sort(key=lambda m: m['chance'],reverse=True)
		bstats = [m for m in mstats if m['m'].id == bestower.id][0]
		rank_index = mstats.index(bstats)+1
		total_eligible = str(len(mstats))
		rank = "most" if rank_index == 1 else "least" if rank_index == total_eligible else self.nth(rank_index)+" most"
		chance = str(round(bstats['chance']*100,2))

		they = self.pronoun_for(bestower).capitalize()
		were = 'were' if they == 'They' else 'was'

		an = "an" if str(chance)[0] == '8' or str(chance)[0:2] == '11' else "a"

		msg = f"{bestower.mention} has been chosen to bestow invite link #{invite_number}.\n\n{they} {were} the {rank} likely out of {total_eligible} with {an} {chance}% chance."

		await self.public_log(msg)
		self.do_bestow = True

	async def resolve_active_bestowment(self, member):
		cursor = self.db.execute("SELECT bestower FROM bestowments WHERE rowid = ?",[self.active_bestowment])
		b_id = cursor.fetchall()[0][0]
		cursor.close()
		bestower = self.guild.get_member(b_id) or None
		they = self.pronoun_for(bestower) if bestower else "they"

		cursor = self.db.cursor()
		cursor.execute("UPDATE bestowments SET bestowee = ?, bestowee_joined_at = ? WHERE rowid = ?", [member.id,member.joined_at,self.active_bestowment])
		self.db.commit()
		cursor.close()

		await self.public_log(f"...and {they} chose {member.mention}! Welcome!")
		await self.bestow()

	def stop_auditing(self):
		self.audit.cancel()

	@tasks.loop(seconds=60.0)
	async def audit(self):
		if not self.do_bestow:
			return

		count = self.audit_count

		await self.check_for_inactivity()

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
			invites = [i for i in invites if i.inviter.id == self.client.user.id and not i.revoked]
			if len(invites) < 1:
				await self.bestow()

			elif self.active_bestowment:
				cursor = self.db.execute("SELECT given_to_bestower_at,link,released_at FROM bestowments WHERE rowid = ?",[self.active_bestowment])
				bestowment_time,link,released_at = cursor.fetchall()[0]
				cursor.close()
				if not released_at:

					two_days_ago = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S.%f")

					if bestowment_time < two_days_ago:
						await self.public_log(f"||{link}||")
						cursor = self.db.cursor()
						cursor.execute("UPDATE bestowments SET released_at = ? WHERE rowid = ?",[datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f"),self.active_bestowment])
						self.db.commit()
						cursor.close()

	def draw_from_raffle(self):
		return random.choice(self.build_raffle())

	def build_raffle(self):
		mstats = self.compile_member_stats()
		raffle = []
		for m in mstats:

			if max([i['touch'] for i in mstats]) == 41 and m['id'] != 466466163757678592:
				continue

			for t in range(m['tickets']):
				raffle.append(m['m'])
		return raffle

	def compile_member_stats(self):
		members = self.eligible_bestowers
		member_stats = []
		for m in members:
			cursor = self.db.execute("SELECT rowid FROM bestowments WHERE bestower = ? OR bestowee = ? ORDER BY given_to_bestower_at DESC LIMIT 1", [m.id, m.id])
			touch = cursor.fetchall()[0][0]
			cursor = self.db.execute("SELECT bestowment_id FROM inactivity WHERE member = ? ORDER BY bestowment_id DESC LIMIT 1",[m.id])
			last_inactive = cursor.fetchall()
			last_inactive = last_inactive[0][0] if len(last_inactive) > 0 else None
			cursor = self.db.execute("SELECT rowid FROM bestowments WHERE bestowee = ? ORDER BY given_to_bestower_at DESC LIMIT 1", [m.id])
			invite_number = cursor.fetchall()
			invite_number = invite_number[0][0] if len(invite_number) > 0 else 0
			effective_touch = last_inactive if last_inactive and last_inactive > touch else touch
			cursor = self.db.execute("SELECT COUNT(rowid) FROM bestowments WHERE bestower = ?",[m.id])
			bestowments = cursor.fetchall()[0][0]
			cursor.close()
			children = self.count_progeny_for(m.id)
			member_stats.append({'name':m.name,'id':m.id,'touch':touch,'effective_touch':effective_touch,'bestowments':bestowments,'children':children,'inactive':last_inactive,'m':m, 'invite_number':invite_number})

		max_touch = max([m['touch'] for m in member_stats])
		max_bestowments = max([m['bestowments'] for m in member_stats])
		max_children = max([m['children'] for m in member_stats])

		for m in member_stats:
			m['tickets'] = max_touch+max_bestowments+max_children-m['effective_touch']-m['bestowments']-m['children']
		total_tickets = sum([m['tickets'] for m in member_stats])
		for m in member_stats:
			m['chance'] = m['tickets']/total_tickets

		return member_stats

	async def print_member_stats(self,op,size='l'):
		msg = []
		footer = ""
		stats = self.compile_member_stats()
		stats.sort(key=lambda m:m['chance'],reverse=True)
		count = 0
		for member in stats:
			if size == 's':
				more = " #"+str(member['invite_number'])+" **"+member['m'].name+'**\n'+str(member['tickets'])+" tickets / "+str(round(member['chance']*100,2))+"% chance\n"
			elif size == 'xs':
				more = "**"+member['m'].name+'**: '+str(round(member['chance']*100,2))+'%'
			else:
				more = ""
				more += "#"+str(member['invite_number'])+" **"+member['m'].name+"**\n"
				more += str(member['tickets']) +" tickets / "+str(round(member['chance']*100,2))+"% chance\n"
				more += "last invite #: "+str(member['touch'])+"\n"
				if member['inactive']:
					more += "inactive on invite #: "+str(member['inactive'])+"\n"
				more += "invites given: "+str(member['bestowments'])+"\n"
				more += "descendants: "+str(member['children'])+"\n"
				if not member['inactive']:
					more += '\n'

			if len(more) + sum(len(m) for m in msg) < 3000 and (size in ['xs','s'] or len(msg) < 30):
				msg.append(more)
				count += 1
			else:
				footer = "showing top "+str(count)+" of "+str(len(stats))
				break
		if footer == "":
			footer = "showing all "+str(count)

		fields = []

		if size != 'xs':
			msglen = sum(len(m) for m in msg)
			fields = [[],[],[]]
			fieldlen = -(len(msg) // -len(fields))

			for i,m in enumerate(msg):
				fields[i % 3].append(m)

		description = " "

		if size not in ['s', 'xs']:
			last_invite = max(m['touch'] for m in stats)
			total_tickets = sum(m['tickets'] for m in stats)
			max_descendants = max(m['children'] for m in stats)
			max_descendants_haver = [m['m'] for m in stats if m['children'] == max_descendants][0]
			max_invites = max(m['bestowments'] for m in stats)
			max_invites_haver = [m['m'] for m in stats if m['bestowments'] == max_invites][0]

			description = "current invite #: "+str(last_invite)
			description += "\ntotal tickets: "+str(total_tickets)+"\n"
			description += "most descendants: "+str(max_descendants)+" ("+max_descendants_haver.name+")\n"
			description += "most invites: "+str(max_invites)+" ("+max_invites_haver.name+")"

		if size == 'xs':
			description += '\n'.join(msg)

		embed = discord.Embed(description=description).set_footer(text=footer)
		for f in fields:
			embed.add_field(name=" ",value='\n'.join(f))

		await op.reply(embed=embed, mention_author=False)
		return

	def count_progeny_for(self,member_id):
		progeny = 0
		for c in self.get_children_for(member_id):
			progeny += 1
			progeny += self.count_progeny_for(c[1])
		return progeny

	def print_progeny_for(self,member_id,indents=-1,showall=False):
		progeny = ""
		indents += 1
		for c in self.get_children_for(member_id):
			for k,i in enumerate(range(indents)):
				if k == indents-1:
					progeny += '`  `'
				else:
					progeny += '`  ` '
			progeny += f"#{c[0]} {self.print_name_for(c[1],showall)}\n"
			progeny += self.print_progeny_for(c[1],indents,showall)
		return progeny

	def print_name_for(self,member_id,showall=False):
		name = f"<@{member_id}>"
		member = self.guild.get_member(member_id)
		if member and (self.active_role not in member.roles or showall):
			name = member.name
		if not member:
			name = "~~"+name+"~~"
		return name


	def get_children_for(self,member_id):
		cursor = self.db.execute("SELECT rowid,bestowee FROM bestowments WHERE bestowee IS NOT NULL AND bestower = ? AND bestower != bestowee",[member_id])
		children = [c for c in cursor.fetchall()]
		cursor.close()
		return children

	async def test(self,m):
		if not m.author.id == self.taq.id:
			return
		await m.reply(self.taq.mention,embed=discord.Embed(description="https://discord.gg/abcdefg\n\nBehold! This is the only invite link in the server, good for exactly one use.\n\nYou may share it with whomever you like or say `bot pass` to hand the duty of bestowment off to someone else.\n\nYou have two days.\n").set_footer(icon_url=random.choice(self.guild.emojis).url,text="The internet is counting on you"))
