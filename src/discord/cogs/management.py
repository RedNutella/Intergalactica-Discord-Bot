import re
import json

import discord
from discord.ext import commands

import src.config as config
from src.models import Settings, EmojiUsage, NamedEmbed, Translation, Locale, database
from src.discord.helpers.waiters import *

emoji_match = lambda x : [int(x) for x in re.findall(r'<a?:[a-zA-Z0-9\_]+:([0-9]+)>', x)]

def increment_emoji(guild, emoji):
    with database:
        usage, _ = EmojiUsage.get_or_create(guild_id = guild.id, emoji_id = emoji.id)
        usage.total_uses += 1
        usage.save()

class Management(discord.ext.commands.Cog):

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        if not self.bot.production:
            return

        if message.author.bot:
            return

        ids = emoji_match(message.content)
        for id in ids:
            emoji = self.bot.get_emoji(id)
            if emoji in message.guild.emojis:
                increment_emoji(message.guild, emoji)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if not self.bot.production:
            return

        emoji = payload.emoji

        if payload.member.bot:
            return

        if emoji.id is None:
            return

        member = payload.member

        if emoji not in member.guild.emojis:
            return

        increment_emoji(member.guild, emoji)

    @commands.command()
    async def emojis(self, ctx, order = "least"):

        if order == "least":
            emoji_usages = [x for x in EmojiUsage.select().where(EmojiUsage.guild_id == ctx.guild.id).order_by(EmojiUsage.total_uses.desc()) if x.emoji is not None]
        else:
            emoji_usages = [x for x in EmojiUsage.select().where(EmojiUsage.guild_id == ctx.guild.id).order_by(EmojiUsage.total_uses.asc()) if x.emoji is not None]

        emoji_ids = [x.emoji_id for x in emoji_usages]

        with database:
            for emoji in ctx.guild.emojis:
                if emoji.id is not None:
                    if emoji.id not in emoji_ids:
                        emoji_usages.append( EmojiUsage.create(guild_id = ctx.guild.id, emoji_id = emoji.id) )

            embed = discord.Embed(color = ctx.guild_color )
            embed.description = ""

            for usage in emoji_usages[-10:-1]:
                embed.description += f"{usage.emoji} = {usage.total_uses}\n"

            await ctx.send(embed = embed)


    @commands.is_owner()
    @commands.command()
    async def stop(self, ctx):
        quit()

    @commands.is_owner()
    @commands.group()
    async def translation(self, ctx):
        pass

    @translation.command(name = "add")
    async def add_translation(self, ctx, key, *, value):
        with database:
            try:
                Translation.create(message_key = key, value = value)
            except:
                await ctx.error()
            else:
                await ctx.success()

    @translation.command()
    async def spoonfeed(self, ctx, locale : Locale):
        missing_translations = self.bot.missing_translations.get(locale.name, [])

        for key in [x for x in missing_translations]:
            waiter = StrWaiter(ctx, prompt = f"Translate: {key}", max_words = None, skippable = True)
            try:
                value = await waiter.wait()
            except Skipped:
                return
            else:
                Translation.create(message_key = key, value = value, locale = locale)
                missing_translations.remove(key)

            await ctx.send("OK, created")

    @commands.command()
    @commands.has_guild_permissions(administrator = True)
    async def embed(self, ctx, name):
        with database:
            settings = Settings.get(guild_id = ctx.guild.id)

            if len(ctx.message.attachments) > 0:
                attachment = ctx.message.attachments[0]
                data = json.loads(await attachment.read())

                embed_data = data["embeds"][0]
                embed = discord.Embed.from_dict(embed_data)
                await ctx.send(embed = embed)

                named_embed, _ = NamedEmbed.get_or_create(name = name, settings = settings)
                named_embed.data = embed_data
                named_embed.save()
            else:
                try:
                    named_embed = NamedEmbed.get(name = name, settings = settings)
                except NamedEmbed.DoesNotExist:
                    await ctx.send("This embed does not exist")
                else:
                    await ctx.send(embed = named_embed.embed)

    @commands.command()
    @commands.has_guild_permissions(administrator = True)
    async def resetchannel(self, ctx, channel : discord.TextChannel = None):
        if channel is None:
            channel = ctx.channel

        await channel.clone()
        await channel.delete()

def setup(bot):
    bot.add_cog(Management(bot))