import discord
from discord.ext import commands
from discord import app_commands
import random
import re
from urllib.parse import urlparse, parse_qs, urlencode, unquote_plus

# ── Config ────────────────────────────────────────────────────────────────────
import os
TOKEN = os.environ.get("DISCORD_TOKEN")

# ── Bot setup ─────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

WHEELDECIDE_PATTERN = re.compile(r'https?://wheeldecide\.com\S+')

# ── URL parsing ───────────────────────────────────────────────────────────────
def parse_wheel_url(url: str):
    params = parse_qs(urlparse(url).query)

    options = []
    i = 1
    while f"c{i}" in params:
        options.append(unquote_plus(params[f"c{i}"][0]))
        i += 1

    weights = None
    if "weights" in params:
        raw_weights = params["weights"][0].split(",")
        weights = []
        for j in range(len(options)):
            try:
                weights.append(float(raw_weights[j]))
            except (IndexError, ValueError):
                weights.append(1.0)

    title = unquote_plus(params["t"][0]) if "t" in params else None
    remove = params.get("remove", ["0"])[0] == "1"

    return options, weights, title, remove

# ── Reconstruct a clean URL after removing the winner ─────────────────────────
def build_next_url(options: list, weights: list | None, title: str | None) -> str | None:
    if not options:
        return None

    params = {}
    for i, option in enumerate(options):
        params[f"c{i + 1}"] = option.replace(" ", "+")

    if title:
        params["t"] = title.replace(" ", "+")

    if weights:
        params["weights"] = ",".join(str(int(w) if w == int(w) else w) for w in weights)

    params["remove"] = "1"

    return "https://wheeldecide.com/index.php?" + urlencode(params)

# ── Core spin logic ───────────────────────────────────────────────────────────
def do_spin(url: str, mention: str) -> str:
    try:
        options, weights, title, remove = parse_wheel_url(url)
    except Exception:
        return "❌ That doesn't look like a valid URL. Please double-check it."

    if not options:
        return "❌ No options found in that URL. Make sure it's a valid WheelDecide link with `c1=`, `c2=`, etc."

    result = random.choices(options, weights=weights, k=1)[0]
    winner_index = options.index(result)

    lines = []
    if title:
        lines.append(f"# {title}")

    lines.append(f"🎡 {mention} spun the wheel! [[Link]]({url})")
    lines.append(f"**Result: {result}**")
    lines.append("")
    lines.append("**Options on the wheel:**")
    for idx, option in enumerate(options):
        w = weights[idx] if weights else 1
        label = f" (weight: {w})" if w != 1.0 else ""
        lines.append(f"- {option}{label}")

    if remove:
        remaining_options = [o for i, o in enumerate(options) if i != winner_index]
        remaining_weights = (
            [w for i, w in enumerate(weights) if i != winner_index] if weights else None
        )

        if remaining_options:
            next_url = build_next_url(remaining_options, remaining_weights, title)
            lines.append("")
            lines.append(f"🔁 **Remove mode is on!** The option for **{result}** has been removed from the [next spin]({next_url}).")
        else:
            lines.append("")
            lines.append("🏁 **Remove mode is on, and that was the last option!** The wheel is now empty.")

    return "\n".join(lines)

# ── Message listener: hint + URL detection ────────────────────────────────────
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if WHEELDECIDE_PATTERN.search(message.content):
        if not message.content.strip().startswith(("!spin", "/spin")):
            hint = await message.reply(
                "💡 **Hint:** You can type `/spin` or `!spin` followed by that URL to show the results on Discord!",
                suppress_embeds=True
            )
            await hint.delete(delay=20)

    await bot.process_commands(message)

# ── Prefix command: !spin <url> ───────────────────────────────────────────────
@bot.command(name="spin")
async def spin_prefix(ctx: commands.Context, url: str):
    result = do_spin(url, ctx.author.mention)
    await ctx.message.delete()
    await ctx.send(result, suppress_embeds=True)

# ── Slash command: /spin url:<url> ────────────────────────────────────────────
@bot.tree.command(name="spin", description="Spin a WheelDecide wheel and see the result")
@app_commands.describe(url="The full WheelDecide URL to spin")
async def spin_slash(interaction: discord.Interaction, url: str):
    result = do_spin(url, interaction.user.mention)
    await interaction.response.send_message(result, suppress_embeds=True)

# ── Startup ───────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ Logged in as {bot.user} and slash commands synced.")

bot.run(TOKEN)