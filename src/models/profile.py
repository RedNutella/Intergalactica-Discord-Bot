import datetime
from dateutil.relativedelta import relativedelta 

import peewee
import discord
import emoji

from .base import BaseModel
from src.utils.timezone import Timezone
import src.config as config

emojize = lambda x : emoji.emojize(x, use_aliases=True)


class EmojiUsage(BaseModel):
    guild_id    = peewee.BigIntegerField  (null = False)
    emoji_id    = peewee.BigIntegerField  (null = False)
    total_uses  = peewee.IntegerField     (default = 0)

    @property
    def emoji(self):
        return self.bot.get_emoji(self.emoji_id)

class RankRole(BaseModel):
    role_id             = peewee.BigIntegerField  (null = False)
    guild_id            = peewee.BigIntegerField  (null = False)
    required_experience = peewee.BigIntegerField  (null = False)

    @property
    def role(self):
        return self.guild.get_role(self.role_id)


class Settings(BaseModel):
    guild_id                            = peewee.BigIntegerField  (null = False)
    min_rank_required_for_personal_role = peewee.ForeignKeyField  (RankRole, null = True)

class GlobalHuman(BaseModel):
    user_id               = peewee.BigIntegerField  (null = False)

class Human(BaseModel):
    user_id               = peewee.BigIntegerField  (null = False)
    guild_id              = peewee.BigIntegerField  (null = False)
    personal_role_id      = peewee.BigIntegerField  (null = True)
    experience            = peewee.BigIntegerField  (default = 0)
    last_experience_given = peewee.DateTimeField    (default = lambda : datetime.datetime.now())
    global_human          = peewee.ForeignKeyField  (GlobalHuman)
    timezone              = peewee.TextField        (null = True)
    date_of_birth         = peewee.DateField        (null = True)
    city                  = peewee.TextField        (null = True)
    last_active           = peewee.DateTimeField    (null = True)

    @property
    def inactive(self):
        last_active = self.last_active or self.member.join_date
        return (last_active + config.inactive_delta) < datetime.datetime.now()

    @property
    def rank_role_should_have(self):
        return RankRole\
            .select()\
            .where( (RankRole.guild_id == self.guild_id) & (RankRole.required_experience <= self.experience) )\
            .order_by(RankRole.required_experience.desc())\
            .limit(1)\
            .first()

    @property
    def rank_role(self):
        ranks = [
            748494880229163021,
            748494888844132442,
            748494890127851521,
            748494890169794621,
            748494891419697152,
            748494891751047183
        ]
        for role in self.member.roles:
            if role.id in ranks:
                return role


    @property
    def level(self):
        level = 0
        xp = int(self.experience)

        while xp >= self.get_experience_needed_for_level(level):
            xp -= self.get_experience_needed_for_level(level)
            level += 1

        return level + 1


    def get_experience_needed_for_level(self, level):
        return (5 * (level ** 2)) + (50 * level) + 100


    @property
    def experience_needed_for_next_level(self):
        return self.get_experience_needed_for_level(self.level + 1)


    @property
    def is_eligible_for_xp(self):
        difference_in_seconds = ( datetime.datetime.now() - self.last_experience_given).seconds
        return  difference_in_seconds >= config.xp_timeout


    @property
    def base_embed(self):
        member = self.member
        embed = discord.Embed(color = member.color or discord.Color.red() )
        embed.set_author(name = self.member.display_name, icon_url = self.member.icon_url)
        return embed

    def get_embed_field(self, show_all = False):

        name = self.member.display_name
        values = []

        values.append(f"Experience {self.experience} / {self.experience_needed_for_next_level}")
        values.append(f"Level {self.level}")

        if self.date_of_birth is not None:
            days_until_birthday = self.days_until_birthday
            age = self.age
            value = f"🎂 {self.age}"
            if days_until_birthday < 10:
                value += f" (days left: {days_until_birthday})"
            values.append(value)
        elif show_all:
            values.append("🎂 N/A")


        if self.timezone is not None:
            timezone = Timezone(self.timezone)
            time = str(timezone.current_time.strftime('%H:%M'))
            values.append(f"🕑 {time}")
            if timezone.country_code:
                flag = "".join([emojize(f":regional_indicator_symbol_letter_{x}:") for x in timezone.country_code.lower()])
                name += " "+flag

        elif show_all:
            values.append("🕑 N/A")

        if self.city is not None:
            city = self.bot.owm_api.by_q(self.city)
            values.append(f"{city.weather_infos[0].emoji} {city.temperature_info.temperature}{city.unit.symbol}")
        elif show_all:
            values.append("🌡️ N/A")

        if len(values) == 0:
            values.append("N/A")

        return {"name" : name, "value" : "\n".join(values), "inline" : True}

    @property
    def personal_role(self):
        return self.guild.get_role(self.personal_role_id)
    
    @personal_role.setter
    def personal_role(self, value):
        self.personal_role_id = value.id

    @property
    def current_time(self):
        if self.timezone is not None:
            return Timezone(self.timezone).current_time

    @property
    def age_delta(self):
        if self.date_of_birth is not None:
            return relativedelta(datetime.datetime.today(), self.date_of_birth)
    
    @property
    def age(self):
        if self.date_of_birth is not None:
            return self.age_delta.years

    @property
    def birthday(self):
        if self.date_of_birth is None:
            return False
        
        current_date = datetime.date.today()
        return self.date_of_birth.day == current_date.day and self.date_of_birth.month == current_date.month

    @property
    def next_birthday(self):
        if self.date_of_birth is None:
            return None

        current_date = datetime.date.today()

        if current_date.month >= self.date_of_birth.month and current_date.day >= self.date_of_birth.day:
            return datetime.datetime(current_date.year + 1, self.date_of_birth.month, self.date_of_birth.day)
        else:
            return datetime.datetime(current_date.year, self.date_of_birth.month, self.date_of_birth.day)

    @property
    def minutes_until_birthday(self):
        return abs((datetime.datetime.now() - self.next_birthday).minutes)

    @property
    def days_until_birthday(self):
        return abs((datetime.datetime.now() - self.next_birthday).days)

    @classmethod
    def get_or_create_for_member(cls, member):
        return Human.get_or_create(
            guild_id = member.guild.id,
            user_id = member.id,
            global_human = GlobalHuman.get_or_create(user_id = member.id)[0]
        )
