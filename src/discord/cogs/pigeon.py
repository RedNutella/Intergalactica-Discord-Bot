import random
import asyncio

import discord
from discord.ext import commands, tasks

import src.config as config
from src.models import Scene, Scenario, Human, Fight, Pigeon, Bet, Settings, database
from src.discord.helpers.waiters import *
from src.games.game.base import DiscordIdentity
from src.discord.errors.base import SendableException

class PigeonCog(commands.Cog, name = "Pigeon"):

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.message_counts = {}

    def get_base_embed(self, guild):
        embed = discord.Embed(color = self.bot.get_dominant_color(guild))
        embed.set_thumbnail(url = "https://cdn.discordapp.com/attachments/705242963550404658/766680730457604126/pigeon_tiny.png")
        return embed

    def get_pigeon_channel(self, guild):
        with database:
            settings, _ = Settings.get_or_create(guild_id = guild.id)
        return settings.get_channel("pigeon")

    @commands.Cog.listener()
    async def on_ready(self):
        self.poller.start()

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not self.bot.production or message.guild is None:
            return

        guild = message.guild
        try:
            channel = self.get_pigeon_channel(guild)
        except SendableException:
            return

        if guild.id not in self.message_counts:
            self.message_counts[guild.id] = 0

        if message.channel.id == channel.id:
            self.message_counts[guild.id] += 1
            command = self.bot.command_prefix + "pigeon claim"
            if message.content == command:
                return

            likeliness = 4000
            if random.randint(self.message_counts[guild.id], likeliness) >= (likeliness-50):
                self.message_counts[guild.id] = 0
                embed = self.get_base_embed(message.guild)
                embed.title = "💩 Pigeon Droppings 💩"
                embed.description = f"Pigeon dropped something in chat! Type **{command}** it find out what it is."
                await message.channel.send(embed = embed)

                def check(m):
                    return m.content.lower() == command and m.channel.id == channel.id and not m.author.bot
                try:
                    msg = await self.bot.wait_for('message', check = check, timeout = 60)
                except asyncio.TimeoutError:
                    embed = self.get_base_embed(message.guild)
                    embed.title = "💩 Pigeon Droppings 💩"
                    embed.description = f"The pigeon kept its droppings to itself."
                    await message.channel.send(embed = embed)
                else:
                    embed = self.get_base_embed(message.guild)
                    embed.title = "💩 Pigeon Droppings 💩"
                    money = random.randint(0, 100)
                    embed.description = f"{msg.author.mention}, you picked up the droppings and received {self.bot.gold_emoji} {money}"
                    await message.channel.send(embed = embed)
                    identity = DiscordIdentity(msg.author)
                    identity.add_points(money)

    @commands.group()
    async def pigeon(self, ctx):
        pass

    async def perform_scenario(self, ctx):
        with database:
            identity = DiscordIdentity(ctx.author)
            scene = Scene.get(command_name = ctx.command.name, group_name = ctx.command.root_parent.name)
            await scene.send(ctx, identity = identity)

    @pigeon.command(name = "help")
    async def pigeon_help(self, ctx):
        embed_data = {
            "title": "⋆ Broken Pigeon-Phone ⋆",
            "description": "**__Money Generator__**\n• /pigeon feed\n• /pigeon chase\n• /pigeon yell\n• /pigeon fish\n\n**__Interactive__**\n• /pigeon claim: Droppings spawn randomly. Input claim to collect it.\n• /pigeon buy: Purchase a pigeon for the pigeon Fight.\n• /pigeon challenge @mention\n",
            "footer": {
                "text": "There is a 4h cooldown for all Money Generator commands.",
                "icon_url": "https://cdn.discordapp.com/attachments/705242963550404658/766661638224216114/pigeon.png"
            }
        }

        embed = discord.Embed.from_dict(embed_data)
        embed.color = ctx.guild_color
        asyncio.gather(ctx.send(embed = embed))

    @commands.cooldown(1, (3600 * 4), type=commands.BucketType.user)
    @pigeon.command(name = "feed")
    async def pigeon_feed(self, ctx):
        asyncio.gather(self.perform_scenario(ctx))

    @commands.cooldown(1, (3600 * 4), type=commands.BucketType.user)
    @pigeon.command(name = "yell")
    async def pigeon_yell(self, ctx):
        asyncio.gather(self.perform_scenario(ctx))

    @commands.cooldown(1, (3600 * 4), type=commands.BucketType.user)
    @pigeon.command(name = "chase")
    async def pigeon_chase(self, ctx):
        asyncio.gather(self.perform_scenario(ctx))

    @commands.cooldown(1, (3600 * 4), type=commands.BucketType.user)
    @pigeon.command(name = "fish")
    async def pigeon_fish(self, ctx):
        asyncio.gather(self.perform_scenario(ctx))

    @pigeon.command(name = "buy")
    async def pigeon_buy(self, ctx):
        with database:
            human, _ = Human.get_or_create(user_id = ctx.author.id)
            pigeon = human.pigeon
            if pigeon is not None:
                asyncio.gather(ctx.send(ctx.translate("pigeon_already_purchased").format(name = pigeon.name)))
                return

            prompt = lambda x : ctx.translate(f"pigeon_{x}_prompt")

            pigeon = Pigeon(human = human)
            waiter = StrWaiter(ctx, prompt = prompt("name"), max_words = None)
            pigeon.name = await waiter.wait()
            pigeon.save()

            pigeon_price = 50
            identity = DiscordIdentity(ctx.author)
            identity.remove_points(pigeon_price)
            asyncio.gather(ctx.send(ctx.translate("pigeon_purchased")))

    @pigeon.command(name = "challenge", aliases = ["fight"])
    async def pigeon_challenge(self, ctx, member : discord.Member):
        channel = self.get_pigeon_channel(ctx.guild)

        with database:
            challenger, _ = Human.get_or_create(user_id = ctx.author.id)
            challengee, _ = Human.get_or_create(user_id = member.id)

            if challenger.pigeon is None:
                raise SendableException(ctx.translate("you_no_pigeon"))
            if challengee.pigeon is None:
                raise SendableException(ctx.translate("challengee_no_pigeon"))

            query = Fight.select()
            query = query.where( Fight.ended == False )
            query = query.where( (Fight.challenger == challenger) | (Fight.challengee == challenger) | (Fight.challenger == challengee) | (Fight.challengee == challengee) )
            pending_challenge = query.first()
            if pending_challenge is not None:
                raise SendableException(ctx.translate("already_fight_pending"))

            fight = Fight(guild_id = ctx.guild.id)
            fight.challenger = challenger
            fight.challengee = challengee
            fight.save()

        embed = self.get_base_embed(ctx.guild)
        embed.title = "Pigeon Challenge"
        embed.description = f"{challenger.mention} has challenged {challengee.mention} to a pigeon fight."
        embed.set_footer(text = f"use '{ctx.prefix}pigeon accept' to accept") 
        asyncio.gather(channel.send(embed = embed))

    @pigeon.command(name = "accept")
    async def pigeon_accept(self, ctx):
        with database:
            challengee, _ = Human.get_or_create(user_id = ctx.author.id)

            query = Fight.select()
            query = query.where(Fight.ended == False)
            query = query.where(Fight.challengee == challengee)
            fight = query.first()

            if fight is None:
                raise SendableException(ctx.translate("no_challenger"))

            fight.accepted = True
            fight.start_date = datetime.datetime.utcnow() + datetime.timedelta(hours = 1)
            fight.start_date = datetime.datetime.utcnow() + datetime.timedelta(minutes = 5)
            fight.save()

            embed = self.get_base_embed(ctx.guild)
            embed.description = f"{ctx.author.mention} has accepted the challenge!"
            embed.set_footer(text = "Fight will start at")
            embed.timestamp = fight.start_date

            channel = self.get_pigeon_channel(ctx.guild)

            await channel.send(embed = embed)

    @pigeon.command(name = "bet")
    async def pigeon_bet(self, ctx, member : discord.Member):
        with database:
            human, _ = Human.get_or_create(user_id = member.id)

            query = Fight.select()
            query = query.where( Fight.ended == False )
            query = query.where( (Fight.challenger == human) | (Fight.challengee == human))
            fight = query.first()

            if fight is None:
                raise SendableException(ctx.translate("no_fight_found"))

            if fight.challengee.user_id == ctx.author.id or fight.challenger.user_id == ctx.author.id:
                raise SendableException(ctx.translate("cannot_vote_own_fight"))

            Bet.create(fight = fight, human = human)
            asyncio.gather(ctx.send(ctx.translate("bet_created")))

    @tasks.loop(seconds=30)
    async def poller(self):
        with database:
            query = Fight.select()
            query = query.where(Fight.ended == False)
            query = query.where(Fight.accepted == True)
            query = query.where(Fight.start_date <= datetime.datetime.utcnow())
            for fight in query:
                won = random.randint(0, 1) == 0
                guild = fight.guild
                channel = self.get_pigeon_channel(guild)

                if won:
                    winner = fight.challenger
                    loser = fight.challengee
                else:
                    winner = fight.challengee
                    loser = fight.challenger

                embed = self.get_base_embed(guild)
                embed.title = f"{fight.challenger.pigeon.name} vs {fight.challengee.pigeon.name}"

                bet = 50
                embed.description = f"{winner.mention}s pigeon destroys {loser.mention}s pigeon. Winner takes {self.bot.gold_emoji} {bet} from the losers wallet"
                asyncio.gather(channel.send(embed = embed))
                winner.gold += bet
                loser.gold -= bet
                winner.save()
                loser.save()

                loser.pigeon.delete_instance()

                fight.won = won
                fight.ended = True
                fight.save()

def setup(bot):
    bot.add_cog(PigeonCog(bot))