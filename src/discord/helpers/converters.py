import datetime
from discord.ext import commands

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
    text = argument

    if text.count("-") == 2:
        dates = [int(x) for x in text.split("-")]
    elif text.count("/") == 2:
        dates = [int(x) for x in text.split("/")]
    elif text == "today":
        return datetime.datetime.now().date().strftime("%Y-%m-%d")
    else:
        return None

    if dates[1] > 12:
        return None

    if len(str(dates[0])) == 4:
        year,month,day = dates
    else:
        day,month,year = dates

    return datetime.date(year, month, day)

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
