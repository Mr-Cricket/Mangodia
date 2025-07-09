# main.py
# Mangodia Discord Bot - Enhanced Version with Invite Tracking & Auto-Leave

import discord
import os
import random
import logging
import json
from discord import app_commands

# --- Configuration ---
BOT_TOKEN = os.environ.get('DISCORD_TOKEN')
DATABASE_FILE = 'database.json'
# --- SET THE SERVER ID YOU WANT THE BOT TO AUTOMATICALLY LEAVE ---
# --- Replace 0 with the actual Server ID. If you don't want it to leave any, keep it as 0. ---
TARGET_SERVER_ID_TO_LEAVE = 1386068110330822756

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Bot Initialization ---
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.invites = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# In-memory cache for invites
invites_cache = {}

# Your existing GIF list
subway_surfers_gifs = [
    'https://media1.tenor.com/m/j2q3H61aU0cAAAAC/subway-surfers.gif',
    'https://media1.tenor.com/m/qiOmXhm9FnQAAAAC/brian-family-guy-tiktok-funny-clip-tasty-sand.gif',
    # ... and the rest of your GIFs
]

# --- Database Helper Functions (Unchanged) ---
def load_database():
    if os.path.exists(DATABASE_FILE):
        with open(DATABASE_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_database(data):
    with open(DATABASE_FILE, 'w') as f:
        json.dump(data, f, indent=4)

db = load_database()

# --- Core Invite Logic & Events (Unchanged) ---
# All your existing on_member_join, etc. events are here.
# For brevity, they are not repeated. Assume all that code is present.

# --- Bot Events ---

@client.event
async def on_ready():
    """Fires when the bot has connected to Discord and is ready."""
    logger.info(f'🤖 Logged in as {client.user} (ID: {client.user.id})')

    # --- AUTO-LEAVE LOGIC ---
    if TARGET_SERVER_ID_TO_LEAVE != 0:
        try:
            guild_to_leave = client.get_guild(TARGET_SERVER_ID_TO_LEAVE)
            if guild_to_leave:
                logger.info(f"Found target server '{guild_to_leave.name}'. Leaving now.")
                await guild_to_leave.leave()
                logger.info(f"Successfully left server {guild_to_leave.name} (ID: {TARGET_SERVER_ID_TO_LEAVE}).")
            else:
                logger.warning(f"Could not find server with ID {TARGET_SERVER_ID_TO_LEAVE}. I may not be a member.")
        except Exception as e:
            logger.error(f"An error occurred while trying to leave server {TARGET_SERVER_ID_TO_LEAVE}: {e}")


    # Cache invites for all guilds on startup
    for guild in client.guilds:
        try:
            invites_cache[guild.id] = await guild.invites()
        except discord.Forbidden:
            logger.warning(f"Don't have permissions to get invites for {guild.name}")

    try:
        synced = await tree.sync()
        logger.info(f'✅ Synced {len(synced)} command(s)')
    except Exception as e:
        logger.error(f'❌ Failed to sync commands: {e}')


@client.event
async def on_member_join(member: discord.Member):
    # ... your on_member_join logic
    pass

# --- Existing Commands (Unchanged) ---
@tree.command(name="setup", description="Posts the server rules and FAQ embeds in the current channel.")
async def setup_command(interaction: discord.Interaction):
    # ... your full setup command logic
    pass

@tree.command(name="add-reward", description="Add a role to be given as an invite reward.")
async def add_reward(interaction: discord.Interaction, role: discord.Role, invites: int):
    # ... your add-reward command logic
    pass

# ... and all your other invite tracking commands


# --- Run Bot ---
if __name__ == "__main__":
    if not BOT_TOKEN:
        logger.error("❌ DISCORD_TOKEN not found in environment variables.")
    else:
        try:
            client.run(BOT_TOKEN)
        except discord.LoginFailure:
            logger.error("❌ Invalid bot token.")
        except Exception as e:
            logger.error(f"❌ Error starting bot: {e}")
