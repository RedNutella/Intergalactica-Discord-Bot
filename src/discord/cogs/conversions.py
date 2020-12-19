import re
import asyncio
import datetime
import pytz

import discord
from currency_converter import CurrencyConverter
import pycountry
from measurement.utils import guess
from measurement.measures import Distance, Temperature, Volume, Weight

import src.config as config
from src.discord.helpers.currency_converter_mappings import mapping
from src.discord.helpers.converters import convert_to_time
from src.models import Human, Earthling, database

currency_converter = CurrencyConverter()

class Conversion:
    pass
class CurrencyConversion(Conversion):
    pass
class TimezoneConversion(Conversion):
    pass
class MeasurementConversion(Conversion):
    pass

measurements = [
    ("c", "f"),
    ("kg", "lb"),
    ("g", "oz"),
    ("cm", "inch", "ft"),
    ("ml", "us_cup"),
    ("km", "mi"),
    ("m", "yd", "ft"),
]

other_measurements = {}

for equivalents in measurements:
    for unit in equivalents:
        for other_unit in equivalents:
            if other_unit != unit:
                if unit not in other_measurements:
                    other_measurements[unit] = [other_unit]
                else:
                    other_measurements[unit].append(other_unit)

currency_symbols = {}
for alpha_3, symbol in mapping.items():
    if symbol == "$":
        continue
    if alpha_3 in currency_converter.currencies:
        currency_symbols[alpha_3.lower()] = symbol

units = {
    "f"      : "°F",
    "c"      : "°C",
    "inch"   : '"',
    "us_cup" : "cup",
}
for alpha_3, symbol in currency_symbols.items():
    units[alpha_3] = symbol

def clean_value(value):
    return int(value) if value % 1 == 0 else round(value, 2)

def clean_measurement(value, unit = None):
    if unit is None:
        unit = value.unit
        value = value.value

    value = clean_value(value)

    return str(value) + units.get(unit, unit)

all_units = list(other_measurements.keys())
all_units.append("°f")
all_units.append("°c")
all_units.append('"')
all_units.append('cup')

class ConversionCog(discord.ext.commands.Cog, name = "Conversion"):
    measures = (Weight, Temperature, Distance, Volume)
    time_format = "%H:%M (%I%p)"

    def __init__(self, bot):
        super().__init__()

        _units = all_units
        currency_regex_symbols = []
        for symbol in currency_symbols.values():
            if symbol == "$":
                currency_regex_symbols.append("\$")
            else:
                currency_regex_symbols.append(symbol)

        for currency in currency_converter.currencies:
            _units.append(currency.lower())
        _units += currency_regex_symbols

        self.global_pattern = "([+-]?\d+(\.\d+)*)({})(?!\w)".format("|".join(_units))
        self.currency_pattern = "({})(\d+(\.\d+)*)(?!\w)".format("|".join(currency_regex_symbols))

        self.bot = bot
        self.currency_converter = currency_converter

    async def convert(self, message, currencies, measurements):
        color = self.bot.get_dominant_color(None)
        embed = discord.Embed(color = color)

        for measurement in measurements:
            values = []
            for other in other_measurements[measurement.unit]:
                value = getattr(measurement, other)
                values.append(clean_measurement(value, other))
            embed.add_field(name = clean_measurement(measurement), value = "\n".join(values))

        if len(currencies) > 0:
            for currency in currencies:
                values = []
                all_currencies = await self.get_all_currencies(message)
                for other in (x for x in all_currencies if x.alpha_3 != currency.alpha_3):
                    try:
                        converted = clean_value(self.currency_converter.convert(currencies[currency], currency.alpha_3, other.alpha_3))
                    except ValueError:
                        continue
                    values.append(f"{other.name} {converted}")
                if len(values) > 0:
                    embed.add_field(name = f"{currency.name} ({clean_value(currencies[currency])})", value = "\n".join(values))
        if len(embed.fields) > 0:
            return embed

    def _get_matches(self, content):
        cleaned_matches = []

        matches = re.findall(self.global_pattern, content)
        if matches:
            for match in matches:
                value = float(match[0])
                unit = match[-1]
                aliases_found = False
                for _unit, alias in units.items():
                    if alias.lower() == unit:
                        aliases_found = True
                        cleaned_matches.append({"value" : value, "unit" : _unit})
                if not aliases_found:
                    cleaned_matches.append({"value" : value, "unit" : unit})

        matches = re.findall(self.currency_pattern, content)
        if matches:
            for match in matches:
                symbol = match[0]
                value = match[1]
                for alpha_2, _symbol in currency_symbols.items():
                    if symbol == _symbol:
                        cleaned_matches.append({"value" : value, "unit" : alpha_2.lower()})

        return cleaned_matches

    @discord.ext.commands.Cog.listener()
    async def on_message(self, message):
        # if message.author.bot or not self.bot.production:
        #     return

        if "http" in message.content:
            return

        matches = self._get_matches(message.content.lower())
        if len(matches):
            measurements = []
            currencies   = {}
            for match in matches:
                unit, value = match["unit"], match["value"]
                if unit.upper() in self.currency_converter.currencies:
                    currencies[(pycountry.currencies.get(alpha_3 = unit.upper()))] = value
                else:
                    measurements.append(guess(value, unit, measures = self.measures))

            embed = await self.convert(message, currencies, measurements)
            if embed is not None:
                asyncio.gather(message.channel.send(embed = embed))

        elif "utc" in message.content.lower() or "gmt" in message.content.lower():
            times = {}
            for word in message.content.lower().split():
                if word.startswith("utc") or word.startswith("gmt"):
                    timezone = word[:3]
                    remaining = word.replace(timezone, "")
                    now = datetime.datetime.now(pytz.timezone(timezone))
                    if remaining == "":
                        symbol = "+"
                        numbers = 0
                    else:
                        symbol = remaining[0]
                        numbers = int("".join(x for x in remaining[1:] if x.isdigit()))
                    if symbol == "+":
                        times[f"{timezone}{symbol}{numbers}"] = now + datetime.timedelta(hours = numbers)
                    elif symbol == "-":
                        times[f"{timezone}{symbol}{numbers}"] = now - datetime.timedelta(hours = numbers)

                    embed = discord.Embed(color = self.bot.get_dominant_color(message.guild))
                    for timezone, time in times.items():
                        embed.add_field(name = timezone.upper(), value = time.strftime(self.time_format))
                    asyncio.gather(message.channel.send(embed = embed))

    async def get_all_currencies(self, message):
        query = Human.select()
        query = query.join(Earthling, on=(Human.id == Earthling.human))
        query = query.where((Human.country != None) | (Human.currencies != None))
        ids = set()
        ids.add(message.author.id)

        if message.guild is not None:
            async for msg in message.channel.history(limit=20):
                if not msg.author.bot:
                    ids.add(msg.author.id)

        currencies = set()
        query = query.where(Human.user_id.in_(ids))
        for human in query:
            for currency in human.all_currencies:
                if currency is not None:
                    currencies.add(currency)

        return currencies

def setup(bot):
    bot.add_cog(ConversionCog(bot))