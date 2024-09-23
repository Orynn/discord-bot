import os

import discord
from discord.ext import commands
from dotenv import load_dotenv


load_dotenv()

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}!")


@bot.command()
async def leg(
    ctx,
    actual_level: int = 7,
    target_level: int = 15,
    current_cards: int = 0,
):

    needed_cards = 0
    levelup_needed_cards = 2

    for i in range(actual_level, target_level):
        needed_cards += 2 * (1 + i - 7)
        levelup_needed_cards += 2

    needed_cards -= current_cards
    needed_bells = 0
    card_price = 30

    for i in range(0, needed_cards):
        needed_bells += card_price
        if card_price < 50:
            card_price += 10

    result = (
        f"You need {needed_bells} bells "
        f"for {needed_cards} cards "
        f"to level up from level {actual_level} to {target_level}"
    )
    await ctx.send(result)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send("https://giphy.com/gifs/buschbeer-beer-d1E1msx7Yw5Ne1Fe")


bot.run(os.getenv("TOKEN"))
