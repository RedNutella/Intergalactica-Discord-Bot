import asyncio
import datetime
import random

import discord
from discord.ext import commands

import src.config as config
import src.discord.helpers.pretty as pretty
from src.models import Conversant, Conversation, database
from src.discord.errors.base import SendableException
from src.discord.cogs.core import BaseCog

def is_command(message):
    bot = config.bot
    prefix = bot.command_prefix
    prefixes = []
    if isinstance(prefix, str):
        prefixes.append(prefix)
    elif isinstance(prefix, list):
        prefixes = prefix

    for prefix in prefixes:
        if message.content.startswith(prefix):
            return True
    return False

class ConversationsCog(BaseCog, name = "Conversations"):
    def __init__(self, bot):
        super().__init__(bot)

    @commands.Cog.listener()
    async def on_ready(self):
        pass

    @commands.Cog.listener()
    async def on_message(self, message):
        if self.bot.production:
            return
        if not isinstance(message.channel, discord.DMChannel):
            return
        if is_command(message):
            return

        conversant, created = Conversant.get_or_create(user_id = message.author.id)
        if created:
            return

        conversation = Conversation.select_for(conversant, finished = False).first()

        if conversation is not None:
            other = conversation.conversant2 if conversation.conversant1 == conversant else conversation.conversant1
            await other.user.send(message.content)

    @commands.group()
    async def conversation(self, ctx):
        pass

    @conversation.command(name = "toggle", aliases = ["enable", "disable"])
    async def conversation_toggle(self, ctx):
        conversant, _ = Conversant.get_or_create(user_id = ctx.author.id)
        values = {"enable": True, "disable": False, "toggle": not conversant.enabled}
        conversant.enabled = values[ctx.invoked_with]
        conversant.save()
        await ctx.success(ctx.translate("conversations_toggled_" + ("on" if conversant.enabled else "off")))

    @conversation.command(name = "start")
    async def conversation_start(self, ctx):
        conversant, _ = Conversant.get_or_create(user_id = ctx.author.id)

        conversation = Conversation.select_for(conversant, finished = False).first()
        if conversation is not None:
            raise SendableException(ctx.translate("already_running_conversation"))

        conversant.enabled = True
        conversant.save()
        query = Conversant.select(Conversant.user_id)
        #TODO: any conversant currently not already in a conversation
        query = query.where(Conversant.enabled == True)
        query = query.where(Conversant.id != conversant.id)
        user_ids = [x.user_id for x in query]
        if len(user_ids) == 0:
            raise SendableException(ctx.translate("no_conversants_found"))

        random.shuffle(user_ids)

        user_to_speak_to = None

        for user_id in user_ids:
            user = self.bot.get_user(user_id)

            def check(message):
                if message.author.id != user.id:
                    return False
                if not isinstance(message.channel, discord.DMChannel):
                    return False
                if message.content.lower() in ("no", "n"):
                    return False
                if message.content.lower() in ("yes", "y"):
                    return True
                return True

            await user.send("Are you available to talk? (yes | no)")
            try:
                await self.bot.wait_for("message", check = check, timeout = 60)
            except asyncio.TimeoutError:
                await user.send("You are clearly not available to talk.")
                continue
            user_to_speak_to = user
            break

        if user_to_speak_to is None:
            return

        conversation = Conversation()
        conversation.conversant1 = conversant
        conversation.conversant2 = Conversant.get(user_id = user_to_speak_to.id)
        conversation.save()

        embed = discord.Embed()
        lines = []
        lines.append("Conversation has been started with an anonymous person.")
        lines.append("Chat by chatting in DMs (commands will not work)")
        lines.append("To end call use ......")

        embed.description = "\n".join(lines)

        i = 1
        for user in (user_to_speak_to, self.bot.get_user(conversant.user_id)):
            id = getattr(conversation, f"conversant{i}_key")
            embed.set_footer(text = f"Speaking to conversant with id '{id}'")
            await user.send(embed = embed)
            i += 1

def setup(bot):
    bot.add_cog(ConversationsCog(bot))