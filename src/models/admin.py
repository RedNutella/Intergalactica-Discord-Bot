import datetime
import asyncio

import peewee
import discord

from .base import BaseModel, EmojiField

class SavedEmoji(BaseModel):
    name        = peewee.CharField        (null = False, unique = True)
    guild_id    = peewee.BigIntegerField  (null = False)
    emoji_id    = peewee.BigIntegerField  (null = False)

class BotIdea(BaseModel):
    user_id    = peewee.BigIntegerField (null = False)
    idea       = EmojiField             (null = False)

class Giveaway(BaseModel):
    guild_id        = peewee.BigIntegerField  (null = False)
    channel_id      = peewee.BigIntegerField  (null = False)
    user_id         = peewee.BigIntegerField  (null = False)
    message_id      = peewee.BigIntegerField  (null = False)
    due_date        = peewee.DateTimeField    (null = False, default = lambda : datetime.datetime.utcnow() + datetime.timedelta(days = 1))
    role_id_needed  = peewee.BigIntegerField  (null = True)
    anonymous       = peewee.BooleanField     (null = False, default = False)
    finished        = peewee.BooleanField     (null = False, default = False)
    title           = peewee.TextField        (null = False)
    key             = peewee.TextField        (null = True)
    amount          = peewee.IntegerField     (null = False, default = 1)

    @property
    def role_needed(self):
        return self.guild.get_role(self.role_id_needed)

    def get_embed(self):
        embed = discord.Embed(color = self.bot.get_dominant_color(self.guild))

        notes = []
        notes.append(f"**{self.title}**\n")
        if self.role_id_needed is not None:
            notes.append(f"`{self.role_needed.name}` role needed to participate")
        if self.amount > 1:
            notes.append(f"`{self.amount}` possible winners")

        embed.description = "\n".join(notes)

        footer = []
        footer.append("React with ✅ to join.")
        footer.append("Due at")

        embed.set_footer(text = "\n".join(footer))
        embed.timestamp = self.due_date

        if not self.anonymous:
            embed.set_author(icon_url = self.user.avatar_url, name = f"Giveaway {self.id} by {self.user}")

        return embed

class Location(BaseModel):
    latitude   = peewee.DecimalField  (null = False)
    longitude  = peewee.DecimalField  (null = False)
    created_on = peewee.DateTimeField (null = True, default = lambda : datetime.datetime.utcnow())
    name       = peewee.TextField     (null = False)

    @property
    def google_maps_url(self):
        return f"https://www.google.com/maps/place/{self.latitude}+{self.longitude}/@{self.latitude},{self.longitude},20z"

class DailyReminder(BaseModel):
    time          = peewee.TimeField       (null = False)
    text          = EmojiField             (null = False)
    weekend       = peewee.BooleanField    (null = True)
    weekday       = peewee.BooleanField    (null = True)
    user_id       = peewee.BigIntegerField (null = False)
    last_reminded = peewee.DateField       (null = True)

class PersonalQuestion(BaseModel):
    value = peewee.TextField    (null = False)
    asked = peewee.BooleanField (null = False, default = False)

    @classmethod
    def get_random(cls):
        return cls.select().where(cls.asked == False).order_by(peewee.fn.Rand()).first()

    @property
    def embed(self):
        return discord.Embed(title = f"Question {self.id}", color = discord.Color.gold(),description = self.value)

class Word(BaseModel):
    value = peewee.TextField(null = False)
    language = peewee.CharField(null = False, max_length = 2, default = "EN")