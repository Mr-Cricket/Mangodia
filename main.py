# main.py
# Mangodia Discord Bot - Enhanced Version with Invite Tracking & Owner Commands

import discord
import os
import random
import logging
import json
from discord import app_commands

# --- Configuration ---
BOT_TOKEN = os.environ.get('DISCORD_TOKEN')
OWNER_ID = os.environ.get('OWNER_ID') # Your Discord User ID
DATABASE_FILE = 'database.json'

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
# All your existing on_ready, on_member_join, etc. events are here.
# For brevity, they are not repeated. Assume all that code is present.
@client.event
async def on_ready():
    logger.info(f'🤖 Logged in as {client.user} (ID: {client.user.id})')
    # ... rest of your on_ready code

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

# --- OWNER-ONLY COMMANDS ---

def is_owner():
    """A check to see if the user running the command is the bot owner."""
    def predicate(interaction: discord.Interaction) -> bool:
        if OWNER_ID is None:
            logger.warning("OWNER_ID is not set in environment variables. Owner commands are disabled.")
            return False
        return interaction.user.id == int(OWNER_ID)
    return app_commands.check(predicate)

@tree.command(name="cleanup", description="[Owner Only] Deletes the bot's last messages in this channel.")
@is_owner()
@app_commands.describe(limit="How many messages to check (max 100). Defaults to 50.")
async def cleanup(interaction: discord.Interaction, limit: int = 50):
    """Deletes the bot's own messages in the current channel."""
    await interaction.response.defer(ephemeral=True)
    
    if not interaction.channel.permissions_for(interaction.guild.me).manage_messages:
        await interaction.followup.send("❌ I don't have the `Manage Messages` permission to do that.", ephemeral=True)
        return

    deleted_count = 0
    messages_to_delete = []
    async for message in interaction.channel.history(limit=limit):
        if message.author == client.user:
            messages_to_delete.append(message)
    
    if messages_to_delete:
        await interaction.channel.delete_messages(messages_to_delete)
        deleted_count = len(messages_to_delete)

    await interaction.followup.send(f"✅ Cleanup complete. Deleted {deleted_count} of my message(s).", ephemeral=True)

@tree.command(name="list-servers", description="[Owner Only] Lists all servers the bot is in.")
@is_owner()
async def list_servers(interaction: discord.Interaction):
    """Lists all guilds the bot is a member of."""
    await interaction.response.defer(ephemeral=True)
    description = "Here are all the servers I'm currently in:\n\n"
    for guild in client.guilds:
        description += f"**{guild.name}**\nID: `{guild.id}`\n\n"
    
    embed = discord.Embed(title="🌐 Server List", description=description, color=0x7289DA)
    await interaction.followup.send(embed=embed, ephemeral=True)


@tree.command(name="leave-server", description="[Owner Only] Makes the bot leave a specified server.")
@is_owner()
@app_commands.describe(server_id="The ID of the server to leave.")
async def leave_server(interaction: discord.Interaction, server_id: str):
    """Makes the bot leave a guild by its ID."""
    try:
        guild_id = int(server_id)
        guild_to_leave = client.get_guild(guild_id)

        if guild_to_leave:
            await interaction.response.send_message(f"✅ Attempting to leave **{guild_to_leave.name}**...", ephemeral=True)
            logger.info(f"Leaving server {guild_to_leave.name} (ID: {guild_id}) by command of the owner.")
            await guild_to_leave.leave()
        else:
            await interaction.response.send_message("❌ Server not found. I might not be in a server with that ID.", ephemeral=True)
    except ValueError:
        await interaction.response.send_message("❌ Invalid Server ID. Please provide a valid number.", ephemeral=True)
    except Exception as e:
        logger.error(f"Error in leave_server command: {e}")
        await interaction.response.send_message(f"An unexpected error occurred: {e}", ephemeral=True)


@cleanup.error
@leave_server.error
@list_servers.error
async def owner_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    """Handles errors for owner-only commands."""
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message("❌ This command can only be run by the bot owner.", ephemeral=True)
    else:
        await interaction.response.send_message(f"An unexpected error occurred: {error}", ephemeral=True)


# --- Run Bot ---
if __name__ == "__main__":
    if not BOT_TOKEN:
        logger.error("❌ DISCORD_TOKEN not found in environment variables.")
    elif not OWNER_ID:
        logger.error("❌ OWNER_ID not found in environment variables. Owner commands will not work.")
    else:
        try:
            client.run(BOT_TOKEN)
        except discord.LoginFailure:
            logger.error("❌ Invalid bot token.")
        except Exception as e:
            logger.error(f"❌ Error starting bot: {e}")
