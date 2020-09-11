import re
import json

import discord
from discord.ext import commands

import src.config as config
from src.models import Rule, Settings, EmojiUsage, NamedEmbed, database as db

emoji_match = lambda x : [int(x) for x in re.findall(r'<a?:[a-zA-Z0-9\_]+:([0-9]+)>', x)]

def increment_emoji(guild, emoji):
    with db:
        usage, _ = EmojiUsage.get_or_create(guild_id = guild.id, emoji_id = emoji.id)
        usage.total_uses += 1
        usage.save()

class Management(discord.ext.commands.Cog):

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        if not config.production:
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
        if not config.production:
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
    async def leastemoji(self, ctx):
        emoji_usages = list(EmojiUsage.select().where(EmojiUsage.guild_id == ctx.guild.id).order_by(EmojiUsage.total_uses.desc()) )
        emoji_ids = [x.emoji_id for x in emoji_usages]

        with db:
            for emoji in ctx.guild.emojis:
                if emoji.id is not None:
                    if emoji.id not in emoji_ids:
                        emoji_usages.append( EmojiUsage.create(guild_id = ctx.guild.id, emoji_id = emoji.id) )

            embed = discord.Embed(color = discord.Color.purple())
            embed.description = ""

            for usage in emoji_usages[-10:-1]:
                embed.description += f"{usage.emoji} = {usage.total_uses}\n"

            await ctx.send(embed = embed)


    @commands.command()
    @commands.has_guild_permissions(administrator = True)
    async def addembed(self, ctx, name):
        attachment = ctx.message.attachments[0]
        data = json.loads(await attachment.read())

        embed_data = data["embeds"][0]
        embed = discord.Embed.from_dict(embed_data)
        await ctx.send(embed = embed)

        named_embed, _ = NamedEmbed.get_or_create(name = name)
        named_embed.data = embed_data
        named_embed.save()

    @commands.command()
    @commands.has_guild_permissions(administrator = True)
    async def showembed(self, ctx, name):
        named_embed = NamedEmbed.get(name = name)
        await ctx.send(embed = named_embed.embed)

    @commands.command()
    @commands.has_guild_permissions(administrator = True)
    async def resetchannel(self, ctx, channel : discord.TextChannel = None):
        if channel is None:
            channel = ctx.channel

        await channel.clone()
        await channel.delete()


    @commands.command()
    async def guidelines(self, ctx, numbers : commands.Greedy[int] = None):
        with db:
            rules_named_embed = NamedEmbed.get(name = "guidelines")
            data = rules_named_embed.data

        if numbers is not None:
            rules_named_embed.select_fields([x-1 for x in numbers])

        embed = discord.Embed.from_dict(data)
        await ctx.send(embed = embed)


    @commands.command()
    async def rules(self, ctx, numbers : commands.Greedy[int] = None):
        with db:
            rules_named_embed = NamedEmbed.get(name = "rules")
            data = rules_named_embed.data

        if numbers is not None:
            rules_named_embed.select_fields([x-1 for x in numbers])

        embed = discord.Embed.from_dict(data)
        await ctx.send(embed = embed)


def setup(bot):
    bot.add_cog(Management(bot))