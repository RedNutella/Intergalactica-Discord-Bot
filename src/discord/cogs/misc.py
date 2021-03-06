import random
import asyncio

import requests
import discord
from discord.ext import commands

import src.config as config
from src.discord.cogs.core import BaseCog

class MiscCog(BaseCog, name = "Misc"):

    def __init__(self, bot):
        super().__init__(bot)

    @commands.command()
    async def urban(self, ctx, *, query):
        url = f"https://api.urbandictionary.com/v0/define?term={query}"
        request = requests.get(url)
        # print(request.json())
        json = request.json()

        embed = discord.Embed(color = ctx.guild_color)
        for definition in json["list"]:
            embed.title = definition["word"]
            embed.description = definition["definition"]
            embed.description += f"\n\n{definition['example']}"

            asyncio.gather(ctx.send(embed = embed))
            break

    @commands.command()
    async def invite(self, ctx):
        """Gives an invite link so you can add the bot"""
        await ctx.send(f"https://discordapp.com/oauth2/authorize?client_id={ctx.bot.user.id}&scope=bot&permissions=0")

def setup(bot):
    bot.add_cog(MiscCog(bot))