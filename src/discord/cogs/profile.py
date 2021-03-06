import asyncio
import datetime
import random
import string

import discord
from discord.ext import commands, tasks
import emoji
import pycountry

from src.models import Human, Earthling, HumanItem, Pigeon, Mail, Item, database
from src.discord.helpers.converters import convert_to_date, EnumConverter
from src.discord.helpers.waiters import *
import src.discord.helpers.pretty as pretty
from src.discord.errors.base import SendableException
from src.utils.zodiac import ZodiacSign
from src.discord.cogs.core import BaseCog

def is_tester(member):
    with database.connection_context():
        human = config.bot.get_human(user = member)
        return human.tester

class CityWaiter(StrWaiter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, max_words = None, **kwargs)

    def convert(self, argument):
        if argument.isdigit():
            city = self.bot.owm_api.by_id(argument)
        else:
            city = self.bot.owm_api.by_q(*argument.split(","))

        if city is None:
            raise ConversionFailed("City was not found.")

        return city

class Profile(BaseCog):
    def __init__(self, bot):
        super().__init__(bot)

    @commands.Cog.listener()
    async def on_ready(self):
        await asyncio.sleep(datetime.timedelta(hours = 1).seconds)
        self.start_task(self.earthling_purger, check = self.bot.production)

    @commands.command()
    async def parrot(self, ctx, *, text):
        asyncio.gather(ctx.message.delete(), return_exceptions = False)
        with ctx.typing():
            cost = 10

            human = ctx.get_human()
            if human.gold < cost:
                raise SendableException(ctx.translate("not_enough_gold").format(cost = cost))

            asyncio.gather(ctx.send(text))
            human.gold -= cost
            human.save()

    @commands.command()
    @commands.guild_only()
    async def zodiac(self, ctx, sign : EnumConverter(ZodiacSign) = None):
        if sign is None:
            human = ctx.get_human()
            if human.date_of_birth is None:
                raise SendableException(ctx.translate("date_of_birth_not_set"))
            sign = human.zodiac_sign

        query = Human.select(Human.user_id, Human.zodiac_sign)
        query = query.join(Earthling, on=(Human.id == Earthling.human))
        query = query.where(Earthling.guild_id == ctx.guild.id)
        query = query.where(Human.date_of_birth != None)

        table = pretty.Table()
        table.add_row(pretty.Row(["member", "sign"], header = True))

        i = 0

        for human in query:
            if sign != human.zodiac_sign:
                continue
            if human.user is None:
                continue
            values = [str(human.user), str(sign.name)]
            table.add_row(pretty.Row(values))
            i += 1
        await table.to_paginator(ctx, 15).wait()

    @commands.command()
    @commands.guild_only()
    async def scoreboard(self, ctx):
        query = Human.select()
        query = query.join(Earthling, on=(Human.id == Earthling.human))
        query = query.where(Earthling.guild_id == ctx.guild.id)
        query = query.order_by(Human.gold.desc())

        table = pretty.Table()
        table.add_row(pretty.Row(["rank", "gold", "member"], header = True))

        i = 0
        for human in query:
            user = human.user
            if user is None:
                continue
            values = [f"{i+1}", str(human.gold), str(user)]
            table.add_row(pretty.Row(values))
            i += 1
        await table.to_paginator(ctx, 15).wait()

    @commands.group(aliases = ["balance", "wallet", "gold"])
    async def profile(self, ctx, members : commands.Greedy[discord.Member]):
        if ctx.invoked_subcommand is not None:
            return

        member = members[0] if len(members) else ctx.author

        embed = discord.Embed(color = ctx.author.color)
        human = ctx.bot.get_human(user = member)
        field = human.get_embed_field()
        embed.title = field["name"]
        values = field["value"]

        if human.country:
            embed.set_thumbnail(url = human.country.flag())

        footer = []
        unread_mail = human.inbox.where(Mail.read == False).where(Mail.finished == True)
        if len(unread_mail) > 0:
            footer.append(f"You have {unread_mail.count()} unread mail! use '{ctx.prefix}inbox' to view")

        # embed.timestamp = human.next_birthday
        # if embed.timestamp is not None:
        #     footer.append("Next birthday at")

        if len(footer) > 0:
            embed.set_footer(text = "\n".join(footer))

        embed.description = values

        await ctx.send(embed = embed)

    @profile.command(name = "compare")
    async def profile_compare(self, ctx, member : discord.Member):
        embed = discord.Embed(color = ctx.guild_color)

        humans = [ctx.get_human(user = x) for x in (ctx.author, member)]
        for human in humans:
            embed.add_field(**human.get_embed_field(show_all = True))

        cities = [x.city for x in humans]
        if None not in cities:
            cities = [self.bot.owm_api.by_q(x.city, x.country.alpha_2 if self.country else None) for x in humans]
            distance_in_km = int(cities[0].get_distance(cities[1]))
            embed.set_footer(text = f"{distance_in_km}km away")

        await ctx.send(embed = embed)

    @profile.command(name = "clear", aliases = ["reset"])
    async def profile_clear(self, ctx, fields : commands.Greedy[str.lower]):
        if len(fields) == 0:
            fields = ["city", "country", "dateofbirth", "timezone"]

        human = ctx.get_human()
        human.timezone      = None if "timezone" in fields else human.timezone
        human.city          = None if "city" in fields else human.city
        human.country       = None if "country" in fields else human.country
        human.date_of_birth = None if "dateofbirth" in fields else human.date_of_birth
        human.save()
        asyncio.gather(ctx.success())

    @profile.command(name = "setup")
    @commands.max_concurrency(1, per = commands.BucketType.user)
    async def profile_setup(self, ctx, fields : commands.Greedy[str.lower]):
        if len(fields) == 0:
            fields = ["city", "country", "dateofbirth"]

        human = ctx.get_human()

        if "city" in fields:
            waiter = CityWaiter(ctx, prompt =  ctx.translate("human_city_prompt"), skippable = True)
            try:
                city = await waiter.wait()
                human.city = city.name
            except Skipped:
                pass

        if "country" in fields:
            await human.editor_for(ctx, "country")

        timezone = human.calculate_timezone()
        if timezone is not None:
            human.timezone = timezone

        if "timezone" in fields:
            await human.editor_for(ctx, "timezone")

        if "dateofbirth" in fields:
            await human.editor_for(ctx, "date_of_birth")

        human.save()
        await ctx.send(embed = Embed.success(ctx.translate("profile_setup")))

    @commands.command(aliases = ["timezone", "dateofbirth", "city"])
    async def country(self, ctx):
        await self.profile_setup(ctx, ctx.invoked_with)

    @commands.group()
    async def currency(self, ctx):
        pass

    @currency.command(name = "add")
    async def currency_add(self, ctx, currency : lambda x : pycountry.currencies.get(alpha_3 = x.upper()) ):
        human = ctx.get_human()
        if human.currencies is None:
            human.currencies = set()
        human.currencies.add(currency)
        human.save()
        await ctx.success()

    @currency.command(name = "remove")
    async def currency_remove(self, ctx, currency : lambda x : pycountry.currencies.get(alpha_3 = x.upper()) ):
        human = ctx.get_human()
        human.currencies.remove(currency)
        human.save()
        await ctx.success()

    @commands.command()
    async def events(self, ctx, month : int = None):
        if month is None:
            month = datetime.datetime.utcnow().month

        month = max(min(month, 12), 1)

        query = Human.select()
        query = query.where(Human.date_of_birth != None)
        query = query.where(Human.date_of_birth.month == month)
        query = query.order_by(Human.date_of_birth.asc())

        humans = [x for x in query if ctx.guild.get_member(x.user_id) is not None]

        lines = []
        for human in humans:
            lines.append(f"{human.user} - {human.date_of_birth}")
        if len(lines) > 0:
            embed = discord.Embed(color = ctx.guild_color)
            embed.set_author(name = "Birthdays", icon_url = ctx.guild.icon_url)
            embed.description = "\n".join(lines)
            await ctx.send(embed = embed)
        else:
            await ctx.send("No events this month")

    @commands.command()
    async def daily(self, ctx):
        asyncio.gather(ctx.send(ctx.translate("not_implemented_yet")))

    @commands.group()
    async def item(self, ctx):
        pass

    @item.command(name = "create", aliases = ["edit"])
    async def item_create(self, ctx, *, name):
        if name == "":
            raise commands.errors.MissingRequiredArgument("name")
        if not is_tester(ctx.author):
            raise SendableException(ctx.translate("not_a_tester"))

        item, new = Item.get_or_create(name = name)

        if not new:
            await item.editor_for(ctx, "name", skippable = not new)

        await item.editor_for(ctx, "description", skippable = not new)
        await item.editor_for(ctx, "rarity", skippable = True)
        await item.editor_for(ctx, "explorable", skippable = True)

        waiter = AttachmentWaiter(ctx, prompt = ctx.translate("item_image_prompt"), skippable = not new)
        try:
            item.image_url = await waiter.wait(store = True)
        except Skipped: pass

        item.save()
        await ctx.send("OK")

    @item.command(name = "use")
    async def item_use(self, ctx, *, name):
        if name == "":
            raise commands.errors.MissingRequiredArgument("name")

        try:
            item = Item.get(name = name)
        except Item.DoesNotExist:
            raise SendableException("Item not found.")

        if not item.usable:
            raise SendableException(ctx.translate("item_not_usable"))

        waiter = BoolWaiter(ctx, prompt = f"`{item.description}`\nAre you sure you want to use this item?")
        if not await waiter.wait():
            return await ctx.send(ctx.translate("canceled"))

        human = ctx.get_human()
        human_item, created = HumanItem.get_or_create(item = item, human = human)
        if created or human_item.amount == 0:
            raise SendableException(ctx.translate("you_missing_item"))

        used = False

        if item.code == "ban_hammer":
            await ctx.author.ban(reason = "Ban hammer item was used.", delete_message_days = 0)
            used = True

        elif item.code in ("big_bath", "big_snack", "big_toy"):
            pigeon = Pigeon.get_or_none(human = human, condition = Pigeon.Condition.active)
            if pigeon is None:
                raise SendableException(ctx.translate("you_no_pigeon"))
            used = True
            stat = {"big_bath": "cleanliness", "big_snack": "food", "big_toy": "happiness"}[item.code]
            data = {stat: 100}
            pigeon.update_stats(data, increment = False)
            pigeon.save()
        elif item.code == "milky_way":
            return await self.bot.get_command("milkyway create")(ctx)
        elif item.code == "jester_hat":
            member = await MemberWaiter(ctx, prompt = ctx.translate("prank_member_prompt")).wait()
            return await self.bot.get_command("prank nickname")(ctx, member)

        if used:
            human_item.amount -= 1
            human_item.save()
            await ctx.success("Item has been successfully used.")

    @item.command(name = "explorable", aliases = ["exp"])
    async def item_explorable(self, ctx,*, name):
        if name == "":
            raise commands.errors.MissingRequiredArgument("name")

        if not is_tester(ctx.author):
            raise SendableException(ctx.translate("not_a_tester"))
        try:
            item = Item.get(name = name)
        except Item.DoesNotExist:
            raise SendableException("Item not found.")

        await item.editor_for(ctx, "rarity", skippable = True)
        await item.editor_for(ctx, "explorable", skippable = True)

        item.save()
        await ctx.send("OK")

    @commands.has_guild_permissions(administrator = True)
    @item.command(name = "give")
    async def item_give(self, ctx, member : discord.Member, *, name):
        if name == "":
            raise commands.errors.MissingRequiredArgument("name")
        try:
            item = Item.get(name = name)
        except Item.DoesNotExist:
            raise SendableException("Item not found.")

        member = member or ctx.author
        human = ctx.get_human(user = member)
        human.add_item(item, 1)
        await ctx.send("added")

    @item.command(name = "list")
    async def item_list(self, ctx):
        items = Item.select().order_by(Item.chance.desc())

        table = pretty.Table()
        table.add_row(pretty.Row(("name", "rarity"), header = True))
        for item in items:
            table.add_row(pretty.Row((item.name, item.rarity.name)))
        await table.to_paginator(ctx, 15).wait()

    @item.command(name = "usable")
    async def item_usable(self, ctx):
        items = Item.select().where(Item.usable == True)
        embed = discord.Embed(title = "Usable items", color = ctx.guild_color)
        for item in items:
            embed.add_field(name = item.name, value = item.description, inline = False)
        await ctx.send(embed = embed)

    @commands.command()
    async def inventory(self, ctx, member : discord.Member = None):
        human = ctx.get_human(user = (member or ctx.author))

        data = [(x.item.name, x.amount) for x in human.human_items if x.amount > 0]
        data.insert(0, ("name", "amount"))
        table = pretty.Table.from_list(data, first_header = True)
        await table.to_paginator(ctx, 15).wait()

    @item.command(name = "view")
    async def item_view(self, ctx,*, name):
        item = Item.get(name = name)
        await ctx.send(embed = item.embed)

    async def cog_before_invoke(self, ctx):
        attr_name = (ctx.command.root_parent or ctx.command).callback.__name__
        ctx.attr_name = attr_name

    @tasks.loop(hours = 24)
    async def earthling_purger(self):
        with database.connection_context():
            to_purge = []
            earthlings = list(Earthling)
            for earthling in earthlings:
                if earthling.guild is None or earthling.member is None:
                    to_purge.append(earthling)

            if len(to_purge) != len(earthlings):
                for earthling in to_purge:
                    role = earthling.personal_role
                    if role is not None:
                        await role.delete()
                    earthling.delete_instance()

def setup(bot):
    bot.add_cog(Profile(bot))