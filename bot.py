import os
import re
import random
import discord
from discord.ext import commands
from discord import app_commands
from urllib.parse import urlparse, parse_qs, urlencode, unquote_plus

# ── Config ────────────────────────────────────────────────────────────────────
TOKEN = os.environ.get("DISCORD_TOKEN")
LIMIT = 2000  # Discord's maximum message length

# ── Bot setup ─────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

WHEELDECIDE_PATTERN = re.compile(r'https?://wheeldecide\.com\S+')

# ── Helpers ───────────────────────────────────────────────────────────────────
def clip(text: str, n: int) -> str:
    """Trim text to n characters, adding an ellipsis if it was cut."""
    return text if len(text) <= n else text[: n - 1] + "…"

def link_message(label: str, link: str) -> str:
    """A message containing a link, or a note if the link can't fit in Discord."""
    text = f"{label} [[Link]]({link})"
    if len(text) <= LIMIT:
        return text
    return f"{label} (link too long to post; Discord caps messages at {LIMIT} characters)"

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
        params[f"c{i + 1}"] = option

    if title:
        params["t"] = title

    if weights:
        params["weights"] = ",".join(str(int(w) if w == int(w) else w) for w in weights)

    params["remove"] = "1"

    # urlencode turns spaces into + and encodes special characters correctly.
    return "https://wheeldecide.com/index.php?" + urlencode(params)

# ── Core spin logic ───────────────────────────────────────────────────────────
def do_spin(url: str, mention: str) -> list[str]:
    """Returns a list of messages to post (usually one, more if the wheel is huge)."""
    try:
        options, weights, title, remove = parse_wheel_url(url)
    except Exception:
        return ["❌ That doesn't look like a valid URL. Please double-check it."]

    if not options:
        return ["❌ No options found in that URL. Make sure it's a valid WheelDecide link with `c1=`, `c2=`, etc."]

    # Pick by index so duplicate option names can't remove the wrong one.
    winner_index = random.choices(range(len(options)), weights=weights, k=1)[0]
    result = options[winner_index]

    head = []
    if title:
        head.append(f"# {clip(title, 200)}")
    spin_line = f"🎡 {mention} spun the wheel!"
    result_block = [f"**Result: {clip(result, 300)}**", "", "**Options on the wheel:**"]

    option_lines = []
    for i, option in enumerate(options):
        w = weights[i] if weights else 1
        label = f" (weight: {w:g})" if w != 1.0 else ""
        option_lines.append(f"- {clip(option, 100)}{label}")

    # Remove mode: build the next wheel without the winner
    remove_line = None
    next_url = None
    if remove:
        remaining = [i for i in range(len(options)) if i != winner_index]
        if remaining:
            next_url = build_next_url(
                [options[i] for i in remaining],
                [weights[i] for i in remaining] if weights else None,
                title,
            )
            remove_line = (
                f"🔁 **Remove mode is on!** The option for **{clip(result, 100)}** "
                f"has been removed from the [next spin]({next_url})."
            )
        else:
            remove_line = "🏁 **Remove mode is on, and that was the last option!** The wheel is now empty."

    # Normal case: everything fits in one message
    full = "\n".join(
        head
        + [f"{spin_line} [[Link]]({url})"]
        + result_block
        + option_lines
        + (["", remove_line] if remove_line else [])
    )
    if len(full) <= LIMIT:
        return [full]

    # Too long for one message: result first (option list trimmed), then links separately
    first = head + [spin_line] + result_block
    budget = LIMIT - len("\n".join(first)) - 40
    shown = []
    for line in option_lines:
        if len(line) + 1 > budget:
            break
        shown.append(line)
        budget -= len(line) + 1
    hidden = len(option_lines) - len(shown)
    if hidden:
        shown.append(f"- …and {hidden} more")

    messages = ["\n".join(first + shown)]
    messages.append(link_message("🔗 Original wheel:", url))
    if next_url:
        messages.append(
            link_message(
                f"🔁 **Remove mode is on!** **{clip(result, 100)}** was removed. Next spin:",
                next_url,
            )
        )
    elif remove_line:
        messages.append(remove_line)
    return messages

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
    messages = do_spin(url, ctx.author.mention)

    # Post the result(s) first; only delete the original once posting has succeeded.
    try:
        for m in messages:
            await ctx.send(m, suppress_embeds=True)
    except discord.HTTPException as e:
        print(f"Failed to post spin result: {e}")
        await ctx.send("❌ Something went wrong posting that result. Your original message was left in place.")
        return

    # Don't delete the original on a parse error, so the URL isn't lost.
    if not messages[0].startswith("❌"):
        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass

# ── Slash command: /spin url:<url> ────────────────────────────────────────────
@bot.tree.command(name="spin", description="Spin a WheelDecide wheel and see the result")
@app_commands.describe(url="The full WheelDecide URL to spin")
async def spin_slash(interaction: discord.Interaction, url: str):
    messages = do_spin(url, interaction.user.mention)
    try:
        await interaction.response.send_message(messages[0], suppress_embeds=True)
        for m in messages[1:]:
            await interaction.followup.send(m, suppress_embeds=True)
    except discord.HTTPException as e:
        print(f"Failed to post spin result: {e}")

# ── Startup ───────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ Logged in as {bot.user} and slash commands synced.")

bot.run(TOKEN)
