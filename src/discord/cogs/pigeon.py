import random
import asyncio

import discord
from discord.ext import commands, tasks
from countryinfo import CountryInfo

import src.config as config
from src.models import Scene, Scenario, Human, Fight, Pigeon, Earthling, Item, Exploration, Mail, Settings, database
from src.models.base import PercentageField
from src.discord.helpers.waiters import *
from src.games.game.base import DiscordIdentity
from src.discord.errors.base import SendableException
from src.discord.helpers.pretty import prettify_dict
from src.utils.enums import Gender
from src.discord.helpers.converters import EnumConverter

def choose(items,chances):
    p = chances[0]
    x = random.random()
    i = 0
    while x > p :
        i = i + 1
        p = p + chances[i]
    return items[i]

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
        with database.connection_context():
            settings, _ = Settings.get_or_create(guild_id = guild.id)
        return settings.get_channel("pigeon")

    @commands.Cog.listener()
    async def on_ready(self):
        Pigeon.emojis["gold"] = self.bot.gold_emoji
        if self.bot.production:
            self.fight_ticker.start()
        else:
            self.stats_ticker.start()

    @commands.group()
    async def pigeon(self, ctx):
        pass

    @pigeon.command(name = "buy")
    async def pigeon_buy(self, ctx):
        """Buy a pigeon."""

        human, _ = Human.get_or_create(user_id = ctx.author.id)
        pigeon = human.pigeons.select(Pigeon.dead == False).first()

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

        embed = self.get_base_embed(ctx.guild)
        embed.set_footer(text = f"-{pigeon_price}")
        embed.description = ctx.translate("pigeon_purchased")
        asyncio.gather(ctx.send(embed = embed))

    @pigeon.command(name = "challenge", aliases = ["fight"])
    async def pigeon_challenge(self, ctx, member : discord.Member):
        """Challenge another user to a fight."""

        channel = self.get_pigeon_channel(ctx.guild)
        if member.id == ctx.author.id:
            raise SendableException(ctx.translate("cannot_challenge_self"))

        challenger = get_active_pigeon(ctx.author)
        challengee = get_active_pigeon(member)

        pigeon_raise_if_unavailable(ctx, challenger, name = "challenger")
        pigeon_raise_if_stats_too_low(ctx, challenger, name = "challenger")

        pigeon_raise_if_unavailable(ctx, challengee, name = "challengee")
        pigeon_raise_if_stats_too_low(ctx, challengee, name = "challengee")


        fight = Fight(guild_id = ctx.guild.id, start_date = None)

        prompt = lambda x : ctx.translate(f"fight_{x}_prompt")
        waiter = IntWaiter(ctx, prompt = prompt("bet"), min = 0, max = min([challenger.human.gold, challengee.human.gold]), skippable = True)
        try:
            fight.bet = await waiter.wait()
        except Skipped:
            pass

        if challenger.human.gold < fight.bet:
            raise SendableException(ctx.translate("challenger_not_enough_gold").format(bet = fight.bet))
        if challengee.human.gold < fight.bet:
            raise SendableException(ctx.translate("challengee_not_enough_gold").format(bet = fight.bet))

        fight.challenger = challenger
        fight.challengee = challengee
        fight.save()

        for pigeon in (challenger, challengee):
            pigeon.status = Pigeon.Status.fighting
            pigeon.save()

        embed = self.get_base_embed(ctx.guild)
        embed.title = "Pigeon Challenge"
        embed.description = f"{challenger.name} has challenged {challengee.name} to a pigeon fight.\nThe stake for this fight is {fight.bet}"
        embed.set_footer(text = f"use '{ctx.prefix}pigeon accept' to accept") 
        asyncio.gather(channel.send(embed = embed))

    @pigeon.command(name = "gender")
    async def pigeon_gender(self, ctx, gender : EnumConverter(Gender)):
        pigeon = get_active_pigeon(ctx.author)
        pigeon_raise_if_not_exist(ctx, pigeon)
        pigeon.gender = gender
        pigeon.save()
        asyncio.gather(ctx.send(ctx.translate("gender_set")))

    @pigeon.command(name = "name")
    async def pigeon_name(self, ctx, *, name : str):
        cost = 50
        pigeon = get_active_pigeon(ctx.author)
        notify_condition_pigeon(ctx)
        pigeon_raise_if_not_exist(ctx, pigeon)
        raise_if_not_enough_gold(ctx, cost, pigeon.human)

        pigeon.name = name
        pigeon.save()
        embed = self.get_base_embed(ctx.guild)
        embed.description = f"Okay. Name has been set to {name}"
        embed.set_footer(text = f"-{cost}")
        asyncio.gather(ctx.send(embed = embed))

    @pigeon.command(name = "accept")
    async def pigeon_accept(self, ctx):
        """Accept a pending fight."""

        challengee = get_active_pigeon(ctx.author)
        notify_condition_pigeon(ctx)

        query = Fight.select()
        query = query.where(Fight.finished == False)
        query = query.where(Fight.challengee == challengee)
        fight = query.first()

        if fight is None:
            raise SendableException(ctx.translate("no_challenger"))

        error = None
        if fight.challenger.human.gold < fight.bet:
            error = ctx.translate("challenger_not_enough_gold").format(bet = fight.bet)
        if fight.challengee.human.gold < fight.bet:
            error = ctx.translate("challengee_not_enough_gold").format(bet = fight.bet)
        if error is not None:
            for pigeon in (challenger, challengee):
                pigeon.status = Pigeon.Status.idle
                pigeon.save()
            fight.delete_instance()
            raise SendableException(error)

        fight.accepted = True
        fight.start_date = datetime.datetime.utcnow() + datetime.timedelta(minutes = 5)

        for human in (fight.challenger.human, fight.challengee.human):
            human.gold -= fight.bet
            human.save()

        fight.save()

        embed = self.get_base_embed(ctx.guild)
        embed.description = f"{ctx.author.mention} has accepted the challenge!"
        embed.set_footer(text = "Fight will start at")
        embed.timestamp = fight.start_date

        channel = self.get_pigeon_channel(ctx.guild)

        await channel.send(embed = embed)

    @pigeon.command(name = "explore")
    async def pigeon_explore(self, ctx):
        """Have your pigeon exploring a random location."""
        pigeon = get_active_pigeon(ctx.author)
        notify_condition_pigeon(ctx)
        pigeon_raise_if_unavailable(ctx, pigeon)
        pigeon_raise_if_stats_too_low(ctx, pigeon)

        residence = pigeon.human.country_code or get_random_country_code()
        destination = get_random_country_code()

        exploration = Exploration(residence = residence, destination = destination, pigeon = pigeon)
        exploration.end_date = exploration.start_date + datetime.timedelta(minutes = exploration.calculate_duration())
        pigeon.status = Pigeon.Status.exploring
        pigeon.save()
        exploration.save()

        embed = self.get_base_embed(ctx.guild)
        embed.description = "Okay. Your pigeon is now off to explore a random location!"
        embed.set_footer(text = f"'{ctx.prefix}pigeon retrieve' to check on your pigeon")
        asyncio.gather(ctx.send(embed = embed))

    @pigeon.command(name = "retrieve", aliases = ["return"] )
    async def pigeon_retrieve(self, ctx):
        """Retrieve and check on your pigeon."""
        pigeon = get_active_pigeon(ctx.author)
        notify_condition_pigeon(ctx)
        if pigeon is None:
            raise SendableException(ctx.translate("pigeon_does_not_exist"))
        if pigeon.status == Pigeon.Status.idle:
            raise SendableException(ctx.translate("pigeon_idle"))

        embed = self.get_base_embed(ctx.guild)

        activity = pigeon.current_activity

        if activity is None:
            raise SendableException(ctx.translate("nothing_to_retrieve"))

        if isinstance(activity, Exploration):
            if activity.end_date_passed:
                country_name = pycountry.countries.get(alpha_2 = activity.destination).name
                country_info = CountryInfo(activity.destination)

                text = f"{pigeon.name} soared through the skies for **{activity.duration_in_minutes}** minutes"
                text += f" over a distance of **{int(activity.distance_in_km)}** km"
                text += f" until {pigeon.gender.get_pronoun()} finally reached **{country_name}**"

                bonuses = []

                multiplier = 1
                if random.randint(1,10) == 1:
                    multiplier += 0.5
                    languages = country_info.languages()
                    if languages:
                        if len(languages) == 1:
                            language = pycountry.languages.get(alpha_2 = languages[0])
                        else:
                            language = pycountry.languages.get(alpha_2 = [x for x in languages if x != "en"][0])

                        bonuses.append(f"Some {country_info.demonym()} person also taught {pigeon.gender.get_posessive_pronoun()} some {language.name}!")
                    else:
                        bonuses.append(f"{pigeon.gender.get_pronoun().title()} even picked up some of the local language!")

                if random.randint(0,2) == 0:
                    items = list(Item.select().where(Item.explorable == True))
                    if len(items) > 0:
                        item = random.choices(items, weights = [x.rarity.weight for x in items], k = 1)[0]
                        embed.set_thumbnail(url = item.image_url)
                        bonuses.append(f"On the way {pigeon.gender.get_pronoun()} also found a **{item.name}**")
                        pigeon.human.add_item(item, 1)

                explorations_finished = len(activity.pigeon.explorations)
                if explorations_finished % 10 == 0:
                    multiplier += 1
                    bonuses.append(f"Since this is your **{explorations_finished}th** exploration, you get a bonus!")

                for bonus in bonuses:
                    embed.add_field(name = "Bonus", value = bonus, inline = False)

                embed.description = text

                winnings = {
                    "gold"        : int(activity.gold_worth * multiplier),
                    "experience"  : int(activity.xp_worth * multiplier),
                    "food"        : -random.randint(10,40),
                    "happiness"   : int(random.randint(10,40) * multiplier),
                    "cleanliness" : -random.randint(10,40)
                }

                embed.add_field(
                    name = "Winnings",
                    value = get_winnings_value(**winnings),
                    inline = False
                )

                update_pigeon(pigeon, winnings)
                activity.finished = True
                pigeon.status = Pigeon.Status.idle
                pigeon.human.save()
                pigeon.save()
                activity.save()
            else:
                embed.description = f"**{pigeon.name}** is still on {pigeon.gender.get_posessive_pronoun()} way to explore!"
                embed.set_footer(text = "Check back at", icon_url = "https://www.animatedimages.org/data/media/678/animated-pigeon-image-0045.gif")
                embed.timestamp = activity.end_date
        elif isinstance(activity, Mail):
            if activity.end_date_passed:

                winnings = {
                    "experience"  : int(activity.duration_in_minutes * 0.6),
                    "food"        : -random.randint(10,40),
                    "happiness"   : int(random.randint(10,40)),
                    "cleanliness" : -random.randint(10,40),
                }

                update_pigeon(pigeon, winnings)

                embed.add_field(
                    name = "Winnings",
                    value = get_winnings_value(**winnings)
                )

                embed.description = f"{pigeon.name} comes back from a long journey to {activity.recipient.mention}."
                activity.finished = True
                pigeon.status = Pigeon.Status.idle
                pigeon.human.save()
                pigeon.save()
                activity.save()
            else:
                embed.description = f"**{pigeon.name}** is still on {pigeon.gender.get_posessive_pronoun()} way to send a message!"
                embed.set_footer(text = "Check back at", icon_url = "https://www.animatedimages.org/data/media/678/animated-pigeon-image-0045.gif")
                embed.timestamp = activity.end_date

        asyncio.gather(ctx.send(embed = embed))

    @pigeon.command(name = "mail", aliases = ["message", "send", "letter"])
    async def pigeon_mail(self, ctx, user : discord.User):
        """Send someone a pigeon letter."""
        if user.id == ctx.author.id:
            raise SendableException(ctx.translate("cannot_send_to_self"))

        ctx.channel = ctx.author.dm_channel
        if ctx.channel is None:
            ctx.channel = await ctx.author.create_dm()

        sender = get_active_pigeon(ctx.author)
        notify_condition_pigeon(ctx)
        pigeon_raise_if_unavailable(ctx, sender)
        pigeon_raise_if_stats_too_low(ctx, sender)

        recipient, _ = Human.get_or_create(user_id = user.id)

        prompt = lambda x : ctx.translate(f"mail_{x}_prompt")

        mail = Mail(recipient = recipient, sender = sender, read = False)

        waiter = StrWaiter(ctx, prompt = prompt("message"), max_words = None)
        mail.message = await waiter.wait()

        waiter = IntWaiter(ctx, prompt = prompt("gold"), min = 0, skippable = True)
        try:
            mail.gold = await waiter.wait()
        except Skipped:
            pass

        mail.residence   = sender.human.country_code
        mail.destination = recipient.country_code
        mail.end_date = mail.start_date + datetime.timedelta(minutes = mail.calculate_duration())
        sender.human.gold -= mail.gold
        sender.status = Pigeon.Status.mailing

        mail.save()
        sender.human.save()
        sender.save()

        embed = self.get_base_embed(ctx.guild)
        embed.description = f"Okay. Your pigeon is off to send a package to {recipient.mention}!"
        embed.set_footer(text = f"'{ctx.prefix}pigeon retrieve' to check on your pigeon")
        asyncio.gather(ctx.send(embed = embed))

    @pigeon.command(name = "inbox")
    async def pigeon_inbox(self, ctx):
        """Check your inbox."""
        human, _ = Human.get_or_create(user_id = ctx.author.id)
        unread_mail = human.inbox.where(Mail.read == False).where(Mail.finished == True)
        if len(unread_mail) == 0:
            return await ctx.send(ctx.translate("no_unread_mail"))

        for mail in list(unread_mail):
            embed = self.get_base_embed(ctx.guild)
            if mail.gold > 0:
                embed.description = f"{mail.sender.human.mention} has sent you some gold ({mail.gold}) with a message attached:\n`{mail.message}`"
            else:
                embed.description = f"{mail.sender.human.mention} has sent you a message:\n`{mail.message}`"

            await ctx.send(embed = embed)

            mail.read = True
            mail.recipient.gold += mail.gold
            mail.save()
            mail.recipient.save()

    @pigeon.command(name = "stats")
    async def pigeon_stats(self, ctx, member : discord.Member = None):
        member = member or ctx.author
        pigeon = get_active_pigeon(member)
        notify_condition_pigeon(ctx)
        if pigeon is None:
            raise SendableException(ctx.translate("pigeon_does_not_exist"))

        embed = self.get_base_embed(ctx.guild)

        explorations = pigeon.explorations.where(Exploration.finished == True)
        unique_countries_visited = {x.destination for x in explorations}

        lines = []
        lines.append(f"Total explorations: {len(explorations)}")
        lines.append(f"Unique countries visited: {len(unique_countries_visited)}")
        embed.add_field(name = f"Explorations {Pigeon.Status.exploring.value}", value = "\n".join(lines), inline = False)

        mails = pigeon.outbox.where(Mail.finished == True)
        total_gold_sent = sum([x.gold for x in mails if x.gold is not None])

        lines = []
        lines.append(f"Total mails sent: {len(mails)}")
        lines.append(f"Total gold sent: {total_gold_sent}")
        embed.add_field(name = f"Mails {Pigeon.Status.mailing.value}", value = "\n".join(lines), inline = False)

        fights = pigeon.fights.where(Fight.finished == True)
        fights_won = 0
        fights_lost = 0
        profit = 0
        for fight in fights:
            if fight.challenger == pigeon and fight.won:
                fights_won += 1
                profit += fight.bet
            elif fight.challengee == pigeon and not fight.won:
                fights_won += 1
                profit += fight.bet
            else:
                fights_lost += 1
                profit -= fight.bet

        lines = []
        lines.append(f"Total fights won : {fights_won}")
        lines.append(f"Total fights lost: {fights_lost}")
        lines.append(f"Profit: {profit}")
        embed.add_field(name = f"Fights {Pigeon.Status.fighting.value}", value = "\n".join(lines), inline = False)

        asyncio.gather(ctx.send(embed = embed))

    @pigeon.command(name = "status")
    async def pigeon_status(self, ctx, member : discord.Member = None):
        """Check the status of your pigeon."""
        member = member or ctx.author

        pigeon = get_active_pigeon(member)
        notify_condition_pigeon(ctx)
        pigeon_raise_if_not_exist(ctx, pigeon)

        data = {}
        emojis = []

        for attr, emoji in Pigeon.emojis.items():
            try:
                value = getattr(pigeon, attr)
            except AttributeError:
                continue
            if isinstance(getattr(Pigeon, attr), PercentageField):
                data[attr] = f"{value}%"
            else:
                data[attr] = f"{value}"
            emojis.append(emoji)

        emojis.append(pigeon.status.value)
        data["status"] = pigeon.status.name
        lines = prettify_dict(data, emojis = emojis)
        embed = self.get_base_embed(ctx.guild)
        embed.description = f"```\n{lines}```"
        asyncio.gather(ctx.send(embed = embed))

    def increase_stats(self, ctx, attr_name, attr_increase, cost, message):
        pigeon = get_active_pigeon(ctx.author)
        notify_condition_pigeon(ctx)
        pigeon_raise_if_unavailable(ctx, pigeon)

        value = getattr(pigeon, attr_name)
        if value == 100:
            raise SendableException(ctx.translate(f"{attr_name}_already_max"))

        pigeon.human.gold  -= cost
        setattr(pigeon, attr_name, value+attr_increase )
        pigeon.human.save()
        pigeon.save()

        embed = self.get_base_embed(ctx.guild )
        embed.description = message.format(pigeon = pigeon)
        embed.description += get_winnings_value(**{attr_name : attr_increase, 'gold' : -cost})
        asyncio.gather(ctx.send(embed = embed))

    @commands.cooldown(1, (3600 * 1), type=commands.BucketType.user)
    @pigeon.command(name = "clean")
    async def pigeon_clean(self, ctx):
        self.increase_stats(ctx, 'cleanliness', 20, 15, "You happily clean up **{pigeon.name}s** fecal matter.\n")

    @commands.cooldown(1, (3600 * 1), type=commands.BucketType.user)
    @pigeon.command(name = "feed")
    async def pigeon_feed(self, ctx):
        self.increase_stats(ctx, 'food', 20, 15, "You feed **{pigeon.name}** some seeds and whatever else they eat.\n")

    @pigeon.command(name = "scoreboard")
    async def pigeon_scoreboard(self, ctx):
        query = Human.select()
        query = query.join(Earthling, on = (Human.id == Earthling.human) )
        query = query.join(Pigeon, on = (Human.id == Pigeon.human) )
        query = query.where(Pigeon.dead == False)
        query = query.where(Earthling.guild_id == ctx.guild.id)
        query = query.order_by(Pigeon.experience.desc())

        embed = discord.Embed(title = "Scoreboard")

        top = 1
        rows = []
        i = (top-1)
        for human in query:
            values = []
            pigeon = human.pigeon
            values.append(f"{i+1}")
            values.append(str(pigeon.experience))
            values.append(str(pigeon.name))
            rows.append(values)
            if len(rows) == 10:
                break
            i += 1

        headers = ["rank", "exp", "pigeon"]
        sep = " | "
        lines = []
        longests = [len(x) for x in headers]
        padding = 2
        for row in rows:
            row_text = []
            for i in range(len(row)):
                value = row[i]
                if len(value) > longests[i]:
                    longests[i] = len(value)

                row_text.append(value.ljust(longests[i]+padding) )
            lines.append(sep.join(row_text))

        lines.insert(0, sep.join([x.ljust(longests[i]+padding) for i,x in enumerate(headers)]) )

        equals = sum(longests) + (len(headers) * (padding) ) + len(sep) + padding
        lines.insert(1, "=" * equals )

        embed.description = "```md\n" + ( "\n".join(lines) ) + "```"

        await ctx.send(embed = embed)

    @commands.cooldown(1, (3600 * 1), type=commands.BucketType.user)
    @pigeon.command(name = "heal")
    async def pigeon_heal(self, ctx):
        self.increase_stats(ctx, 'health', 20, 15, "You give **{pigeon.name}** some seed you found inside your couch and convince it of its healing effects.\n")

    @pigeon.command(name = "help")
    async def pigeon_help(self, ctx):
        await ctx.send_help(ctx.command.root_parent)

    @tasks.loop(seconds=30)
    async def fight_ticker(self):
        query = Fight.select()
        query = query.where(Fight.finished == False)
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
            embed.title = f"{winner.name} creeps into {loser.name}’s room. {winner.name}’s jaw unhinges and swallows {loser.name} whole."

            winner_data = {"experience" : 30, "health" : -2}
            loser_data = {"experience" : 5, "health" : -10}

            embed.add_field(name = f"💩 {loser.name}", value = get_winnings_value(**loser_data, gold = -fight.bet))
            embed.add_field(name = f"🏆 {winner.name}", value = get_winnings_value(**winner_data, gold = fight.bet))

            asyncio.gather(channel.send(embed = embed))

            update_pigeon(winner, winner_data)
            update_pigeon(loser, loser_data)

            winner.human.gold += (fight.bet*2)

            winner.status = Pigeon.Status.idle
            loser.status = Pigeon.Status.idle

            winner.save()
            winner.human.save()
            loser.save()

            fight.won = won
            fight.finished = True
            fight.save()

    @tasks.loop(hours = 1)
    async def stats_ticker(self):
        for pigeon in Pigeon.select().where(Pigeon.condition == Pigeon.Condition.active).where(Pigeon.status == Pigeon.Status.idle):
            if pigeon.id != 1:
                continue

            data = {"food": -1, "cleanliness" : -1, "happiness": -1}

            if pigeon.food <= 20 or pigeon.cleanliness <= 20:
                data["health"] = -1
            print(data)
            update_pigeon(pigeon, data)
            pigeon.save()

def get_random_country_code():
    country_code = None
    countries = list(pycountry.countries)
    while country_code is None:
        country_code = random.choice(countries).alpha_2
        try:
            CountryInfo(country_code).capital()
        except KeyError:
            country_code = None
    return country_code

def update_pigeon(pigeon, data):
    for key, value in data.items():
        if key == "gold":
            pigeon.human.gold += value
        else:
            setattr(pigeon, key, (getattr(pigeon, key) + value) )
            if key == "health":
                if pigeon.health <= 0:
                    pigeon.condition = Pigeon.Condition.dead

def get_winnings_value(**kwargs):
    lines = []
    for key, value in kwargs.items():
        emoji = Pigeon.emojis[key]
        if value > 0:
            lines.append(f"{emoji} +{value}")
        elif value < 0:
            lines.append(f"{emoji} {value}")
    return ", ".join(lines)

def notify_condition_pigeon(ctx):
    pigeon = Pigeon.select().where(Pigeon.human == Human.get(user_id = ctx.author.id)).where(Pigeon.condition != Pigeon.Condition.active).where(Pigeon.condition_notified == False).first()
    if pigeon is not None:
        pigeon.condition_notified = True
        pigeon.save()
        raise SendableException(ctx.translate("pigeon_" + pigeon.condition.name).format(pigeon = pigeon))

def get_active_pigeon(user, raise_on_none = False):
    try:
        return Pigeon.get(human = Human.get(user_id = user.id), condition = Pigeon.Condition.active)
    except Pigeon.DoesNotExist:
        return None

def pigeon_raise_if_not_exist(ctx, pigeon, name = "pigeon"):
    if pigeon is None:
        raise SendableException(ctx.translate(f"{name}_does_not_exist"))

def pigeon_raise_if_unavailable(ctx, pigeon, name = "pigeon"):
    pigeon_raise_if_not_exist(ctx, pigeon, name)
    if pigeon.status != Pigeon.Status.idle:
        raise SendableException(ctx.translate(f"{name}_not_idle").format(status = pigeon.status.name))

def pigeon_raise_if_stats_too_low(ctx, pigeon, name = "pigeon"):
    if pigeon.cleanliness <= 10:
        raise SendableException(ctx.translate(f"{name}_too_stinky"))
    if pigeon.happiness <= 10:
        raise SendableException(ctx.translate(f"{name}_too_sad"))
    if pigeon.food <= 10:
        raise SendableException(ctx.translate(f"{name}_too_hungry"))
    if pigeon.health <= 10:
        raise SendableException(ctx.translate(f"{name}_too_wounded"))

def raise_if_not_enough_gold(ctx, gold, human, name = "you"):
    if human.gold < gold:
        raise SendableException(ctx.translate(f"{name}_not_enough_gold"))

def setup(bot):
    bot.add_cog(PigeonCog(bot))