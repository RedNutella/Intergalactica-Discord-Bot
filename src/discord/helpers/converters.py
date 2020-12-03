import datetime
from discord.ext import commands

from src.utils.country import Country, CountryNotFound
from src.discord.errors.base import SendableException

def convert_to_time(argument):
    argument = argument.lower()

    pm = "pm" in argument
    argument = argument.replace("pm","").replace("am", "")

    if ":" in argument:
        try:
            hour, minute = argument.split(":")
        except:
            return None
    elif argument.isdigit():
        hour = argument
        minute = 0
    else:
        return None

    hour = int(hour)
    minute = int(minute)
    if pm:
        hour += 12
        if hour >= 24:
            hour = 0

    return datetime.time(hour = hour, minute = minute)

def convert_to_date(argument):
    if argument.count("-") == 2:
        year, month, day = [int(x) for x in argument.split("-")]
    elif argument.count("/") == 2:
        year, month, day = [int(x) for x in argument.split("/")]
    elif argument == "today":
        return datetime.datetime.utcnow().date()
    else:
        return None

    date = datetime.date(year, month, day)

    return date

class ArgumentNotInEnum(commands.errors.BadArgument): pass

class EnumConverter(commands.Converter):
    def __init__(self, enum):
        self.enum = enum

    async def convert(self, ctx, argument):
        if hasattr(self.enum, argument):
            return self.enum[argument]
        else:
            lines = "`, `".join(x.name for x in self.enum)
            raise ArgumentNotInEnum(f"**{argument}** is not a valid argument. Valid arguments are:\n`{lines}`") from None

class CountryConverter(commands.Converter):
    @classmethod
    async def convert(cls, ctx, argument):
        if len(argument) == 2:
            country = Country.from_alpha_2(argument.upper())
        elif len(argument) == 3:
            country = Country.from_alpha_3(argument.upper())
        else:
            country = Country.from_name(argument.title())

        if country is None:
            raise ConversionFailed("Country not found.")

        return country
