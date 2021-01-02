import asyncio
from enum import Enum
import math

import discord
import requests

from .ui import UI

class DiscordUI(UI):
    def __init__(self, ctx):
        self.message = None
        self.mention_message = None
        self.ctx = ctx
        self.invalid_messages = 0
        self.timeout = 60

    def __check(self, word, letters_used, player):
        def __check2(message):
            if self.ctx.channel.id != message.channel.id:
                return False
            if player.identity.member.id != message.author.id:
                self.invalid_messages += 1
                return False
            if len(message.content) == 1 and " " not in message.content:
                letter = message.content.lower()
                asyncio.gather(message.delete(), return_exceptions = False)
                if letter not in letters_used:
                    return True
                else:
                    self.send_error(f"Letter '{letter}' has already been used")
            elif len(message.content) == len(word):
                asyncio.gather(message.delete(), return_exceptions = False)
                return True
            else:
                self.invalid_messages += 1
                return False

            return False
        return __check2

    def send_error(self, text, delete_after = 10):
        asyncio.gather(self.ctx.error(text, delete_after = delete_after))

    async def get_guess(self, word, player, letters_used):
        try:
            guess = await self.ctx.bot.wait_for("message", check = self.__check(word, letters_used, player), timeout = self.timeout)
        except asyncio.TimeoutError:
            guess = None

        if self.mention_message is not None:
            asyncio.gather(self.mention_message.delete())

        return guess.content.lower() if guess is not None else None

    async def refresh_board(self, game, current_player = None):
        embed = discord.Embed(color = self.ctx.guild_color, title=" ".join(game.board))

        for player in game.players:
            if player.dead:
                continue

            length = len(str(player))

            embed.add_field(
                name = str(player),
                value = f">>> ```\n{self.game_states[player.incorrect_guesses]}```")

        guess_info = []
        guess_info.append("letters used: " + ", ".join([f"**{x}**" for x in game.letters_used]))

        if len(game.words_used) > 0:
            guess_info.append("words tried: " + ", ".join(game.words_used))

        content = None
        if current_player is not None:
            content = f"{current_player.identity.member.mention}, your turn! {self.timeout}s"

        embed.add_field(name = "\uFEFF", value = "\n".join(guess_info), inline = False)
        if self.message is None or self.invalid_messages > 3:
            if self.message is not None:
                asyncio.gather(self.message.delete())
            self.message = await self.ctx.send(content = content, embed = embed)
            self.invalid_messages = 0
        else:
            asyncio.gather(self.message.edit(content = content, embed = embed))

        if current_player is not None:
            self.mention_message = await self.ctx.send(content, delete_after = self.timeout)

    async def stop(self, reason, game):
        embed = discord.Embed(title = f"Game has ended: {reason.value}", color = self.ctx.guild_color)
        lines = []

        bet_pool = sum([x.bet for x in game.players])
        bet_pool *= 1.25
        bet_pool += (15 * len(game.players))
        bet_pool = int(bet_pool)

        for player in game.players:
            if player.dead:
                player.identity.remove_points(player.bet)
                lines.append(f"{player.identity.member.mention} lost **{player.bet}** gold")
            else:
                percentage_guessed = player.get_percentage_guessed(game.word)
                won = math.ceil(percentage_guessed / 100 * bet_pool)
                player.identity.add_points(won)
                lines.append(f"{player.identity.member.mention} won **{won}** gold ({int(percentage_guessed)}%)")

        lines.append("\n")
        lines.append(f"**{game.word}**")
        definition = get_word_definition(game.word)
        if definition is not None:
            lines.append(f"*{definition}*")

        embed.description = "\n".join(lines)

        await self.ctx.send(embed = embed)


def get_word_definition(word):
    from bs4 import BeautifulSoup

    url = "https://www.thefreedictionary.com/" + word
    request = requests.get(url)
    soup = BeautifulSoup(request.text, features = "html5lib")

    definition = soup.find(id = "Definition")
    if definition is None:
        return

    ds = definition.find(class_ = "ds-single") or definition.find(class_ = "ds-list")
    if ds is not None:
        return ds.text.strip()
