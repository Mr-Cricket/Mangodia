# main.py
# Mangodia Discord Bot - Enhanced Version with Invite Tracking

import discord
import os
import random
import logging
import json
import asyncio
from discord import app_commands
from discord.utils import get

# --- Configuration ---
BOT_TOKEN = os.environ.get('DISCORD_TOKEN')
DATABASE_FILE = 'database.json'

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Bot Initialization ---
# We need specific intents to track members joining and invites.
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.invites = True
intents.message_content = True # Required for message deletion
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# In-memory cache for invites, to check which one was used
invites_cache = {}

# Enhanced list of GIFs for the FAQ embed with direct URLs for faster loading
subway_surfers_gifs = [
    'https://media1.tenor.com/m/j2q3H61aU0cAAAAC/subway-surfers.gif',
    'https://media1.tenor.com/m/qiOmXhm9FnQAAAAC/brian-family-guy-tiktok-funny-clip-tasty-sand.gif',
    'https://media1.tenor.com/m/r_n5-n2cf2IAAAAC/subway-surfer.gif',
    'https://media0.giphy.com/media/dkUtjuBEdICST5zG7p/giphy.gif',
    'https://media1.giphy.com/media/Fr5LA2RCQbnVp74CxH/giphy.gif',
    'https://media2.giphy.com/media/UTemva5AkBntdGyAPM/giphy.gif',
    'https://media3.giphy.com/media/wc4gc2LmKZOU7bxFcQ/giphy.gif',
    'https://media1.tenor.com/m/G0yFMh7PL6QAAAAC/speech-bubble-cs-go-surf-surfing.gif',
    'https://media4.giphy.com/media/fYShjUkJAXW1YO6cNA/giphy.gif'
]

# --- Database Helper Functions ---

def load_database():
    """Loads the database from the JSON file, creating it if it doesn't exist."""
    if os.path.exists(DATABASE_FILE):
        try:
            with open(DATABASE_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError) as e:
            logger.warning(f"Error loading database, creating new one: {e}")
            return {}
    return {}

def save_database(data):
    """Saves the given data to the JSON file."""
    try:
        with open(DATABASE_FILE, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving database: {e}")

def ensure_guild_in_db(guild_id):
    """Ensures a guild exists in the database with proper structure."""
    guild_id_str = str(guild_id)
    if guild_id_str not in db:
        db[guild_id_str] = {"rewards": {}, "users": {}}
        save_database(db)

def ensure_user_in_db(guild_id, user_id):
    """Ensures a user exists in the guild's database with proper structure."""
    guild_id_str = str(guild_id)
    user_id_str = str(user_id)
    ensure_guild_in_db(guild_id)
    
    if user_id_str not in db[guild_id_str]["users"]:
        db[guild_id_str]["users"][user_id_str] = {"invites": 0, "leaves": 0}
        save_database(db)

db = load_database()

# --- Core Invite Logic ---

def find_invite_by_code(invite_list, code):
    """Finds a specific invite from a list of invites."""
    for inv in invite_list:
        if inv.code == code:
            return inv
    return None

async def check_rewards(member: discord.Member):
    """Checks if a member has earned any reward roles and applies them."""
    guild_id_str = str(member.guild.id)
    member_id_str = str(member.id)

    ensure_guild_in_db(member.guild.id)
    
    if member_id_str not in db[guild_id_str]["users"]:
        return

    user_data = db[guild_id_str]["users"][member_id_str]
    total_invites = user_data.get("invites", 0) - user_data.get("leaves", 0)

    for role_id, required_invites in db[guild_id_str]["rewards"].items():
        role = member.guild.get_role(int(role_id))
        if role and total_invites >= required_invites and role not in member.roles:
            try:
                await member.add_roles(role, reason="Invite Reward")
                logger.info(f"Gave role {role.name} to {member.name}")
            except discord.Forbidden:
                logger.warning(f"Could not give role {role.name} to {member.name} - permissions missing.")
            except Exception as e:
                logger.error(f"Error giving role {role.name} to {member.name}: {e}")

# --- Bot Events ---

@client.event
async def on_ready():
    """Fires when the bot has connected to Discord and is ready."""
    logger.info(f'🤖 Logged in as {client.user} (ID: {client.user.id})')

    # Cache invites for all guilds on startup
    for guild in client.guilds:
        try:
            invites_cache[guild.id] = await guild.invites()
            ensure_guild_in_db(guild.id)
        except discord.Forbidden:
            logger.warning(f"Don't have permissions to get invites for {guild.name}")
        except Exception as e:
            logger.error(f"Error caching invites for {guild.name}: {e}")

    try:
        synced = await tree.sync()
        logger.info(f'✅ Synced {len(synced)} command(s)')
    except Exception as e:
        logger.error(f'❌ Failed to sync commands: {e}')

@client.event
async def on_member_join(member: discord.Member):
    """Tracks when a new member joins and attributes the invite."""
    guild = member.guild
    logger.info(f"Member {member.name} joined {guild.name}")

    try:
        invites_before_join = invites_cache.get(guild.id, [])
        invites_after_join = await guild.invites()
        invites_cache[guild.id] = invites_after_join

        for invite in invites_before_join:
            used_invite = find_invite_by_code(invites_after_join, invite.code)
            if used_invite and invite.uses < used_invite.uses:
                inviter = invite.inviter
                if inviter:  # Check if inviter exists
                    logger.info(f"{member.name} was invited by {inviter.name}")

                    ensure_user_in_db(guild.id, inviter.id)
                    guild_id_str = str(guild.id)
                    inviter_id_str = str(inviter.id)

                    db[guild_id_str]["users"][inviter_id_str]["invites"] += 1
                    save_database(db)

                    # Check for role rewards
                    inviter_member = guild.get_member(inviter.id)
                    if inviter_member:
                        await check_rewards(inviter_member)
                return

    except discord.Forbidden:
        logger.warning(f"Cannot track invites in {guild.name} due to missing permissions.")
    except Exception as e:
        logger.error(f"Error in on_member_join: {e}")

@client.event
async def on_member_remove(member: discord.Member):
    """Tracks when a member leaves to adjust invite counts."""
    logger.info(f"Member {member.name} left {member.guild.name}")
    # Note: Advanced implementation would track who invited whom to adjust leave counts

@client.event
async def on_invite_create(invite: discord.Invite):
    """Updates the invite cache when a new invite is created."""
    try:
        invites_cache[invite.guild.id] = await invite.guild.invites()
    except Exception as e:
        logger.error(f"Error updating invite cache on create: {e}")

@client.event
async def on_invite_delete(invite: discord.Invite):
    """Updates the invite cache when an invite is deleted."""
    try:
        invites_cache[invite.guild.id] = await invite.guild.invites()
    except Exception as e:
        logger.error(f"Error updating invite cache on delete: {e}")

# --- COMMANDS ---

@tree.command(name="setup", description="Posts the server rules and FAQ embeds in the current channel.")
async def setup_command(interaction: discord.Interaction):
    """Handles the /setup slash command to post server info."""
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message("❌ You need 'Manage Messages' permission to use this command.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    
    try:
        # --- Rules Embed with Enhanced Design ---
        rules_embed = discord.Embed(
            title="📜 **MANGODIA RULES**",
            description="*Please read and adhere to these guidelines to maintain a positive community environment.*",
            color=0xFF6B6B  # Red color
        )
        
        rules_embed.add_field(
            name="🚫 **1. No Harassment or Bullying**",
            value="Treat all members with respect. No personal attacks, threats, or discriminatory language.",
            inline=False
        )
        
        rules_embed.add_field(
            name="🔞 **2. Keep Content Appropriate**",
            value="No NSFW content, excessive profanity, or inappropriate discussions. Keep it family-friendly.",
            inline=False
        )
        
        rules_embed.add_field(
            name="📢 **3. No Spam or Self-Promotion**",
            value="Avoid repetitive messages, excessive caps, or unauthorized advertising. Ask mods before sharing links.",
            inline=False
        )
        
        rules_embed.add_field(
            name="💬 **4. Use Appropriate Channels**",
            value="Post content in the relevant channels. Keep discussions on-topic and organized.",
            inline=False
        )
        
        rules_embed.add_field(
            name="🎭 **5. Respect Privacy**",
            value="Don't share personal information without consent. Respect others' boundaries and privacy.",
            inline=False
        )
        
        rules_embed.add_field(
            name="⚖️ **6. Follow Discord TOS**",
            value="All Discord Terms of Service and Community Guidelines apply here.",
            inline=False
        )
        
        rules_embed.set_footer(text="Violations may result in warnings, mutes, or bans • Stay awesome! 🌟")
        rules_embed.set_thumbnail(url="https://cdn.discordapp.com/emojis/1234567890123456789.png")  # Replace with your server icon

        # --- GIF Embed for FAQ Attention ---
        gif_embed = discord.Embed(
            title="🏃‍♂️ **ATTENTION SPAN BOOSTER**",
            description="*Since your attention span is probably shorter than a TikTok video, here's some Subway Surfers gameplay while you read the FAQ below!*",
            color=0x4ECDC4  # Teal color
        )
        
        # Randomly select a GIF with fallback
        try:
            selected_gif = random.choice(subway_surfers_gifs)
            gif_embed.set_image(url=selected_gif)
            logger.info(f"Selected GIF: {selected_gif}")
        except Exception as e:
            logger.warning(f"Failed to set GIF: {e}")
        
        gif_embed.set_footer(text="Now you can focus on reading the FAQ below! 🎮")

        # --- FAQ Embed with Enhanced Design ---
        faq_embed = discord.Embed(
            title="❓ **FREQUENTLY ASKED QUESTIONS**",
            description="*Here are answers to the most common questions about our server.*",
            color=0x45B7D1  # Blue color
        )
        
        faq_embed.add_field(
            name="🤖 **What is this server about?**",
            value="Mangodia is a community focused on gaming, chatting, and having a great time together!",
            inline=False
        )
        
        faq_embed.add_field(
            name="🎮 **What games do we play?**",
            value="We play a variety of games including Minecraft, Among Us, Valorant, and many more! Check the gaming channels.",
            inline=False
        )
        
        faq_embed.add_field(
            name="🏆 **How do I get roles?**",
            value="Many roles are earned through activity, inviting friends, or participating in events. Some can be self-assigned!",
            inline=False
        )
        
        faq_embed.add_field(
            name="📞 **Can I join voice channels?**",
            value="Absolutely! Feel free to hop into any voice channel and chat with other members.",
            inline=False
        )
        
        faq_embed.add_field(
            name="🎉 **Are there events?**",
            value="Yes! We regularly host gaming tournaments, movie nights, and other fun community events.",
            inline=False
        )
        
        faq_embed.add_field(
            name="🆘 **Who do I contact for help?**",
            value="Reach out to any moderator or admin (they have colored names) if you need assistance!",
            inline=False
        )
        
        faq_embed.set_footer(text="Still have questions? Don't hesitate to ask in the general chat! 💬")

        # Send all embeds
        await interaction.followup.send(embed=rules_embed)
        await interaction.followup.send(embed=gif_embed)
        await interaction.followup.send(embed=faq_embed)
        
        await interaction.followup.send("✅ **Setup Complete!** All embeds have been posted successfully.", ephemeral=True)
        
    except Exception as e:
        logger.error(f"Error in setup command: {e}")
        await interaction.followup.send("❌ An error occurred during setup. Please try again.", ephemeral=True)

# --- INVITE TRACKING COMMANDS ---

@tree.command(name="add-reward", description="Add a role to be given as an invite reward.")
@app_commands.describe(role="The role to be awarded.", invites="The number of invites required.")
async def add_reward(interaction: discord.Interaction, role: discord.Role, invites: int):
    """Command to set up a new invite reward."""
    if not interaction.user.guild_permissions.manage_roles:
        await interaction.response.send_message("❌ You need 'Manage Roles' permission to use this command.", ephemeral=True)
        return

    if invites < 1:
        await interaction.response.send_message("❌ Invite count must be at least 1.", ephemeral=True)
        return

    ensure_guild_in_db(interaction.guild.id)
    guild_id_str = str(interaction.guild.id)
    db[guild_id_str]["rewards"][str(role.id)] = invites
    save_database(db)

    embed = discord.Embed(
        title="✅ Reward Added",
        description=f"Users will now get the **{role.name}** role for **{invites}** invites!",
        color=0x50C878
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="remove-reward", description="Remove an invite reward role.")
@app_commands.describe(role="The reward role to remove.")
async def remove_reward(interaction: discord.Interaction, role: discord.Role):
    """Command to remove an invite reward."""
    if not interaction.user.guild_permissions.manage_roles:
        await interaction.response.send_message("❌ You need 'Manage Roles' permission to use this command.", ephemeral=True)
        return

    ensure_guild_in_db(interaction.guild.id)
    guild_id_str = str(interaction.guild.id)
    
    if str(role.id) in db[guild_id_str]["rewards"]:
        del db[guild_id_str]["rewards"][str(role.id)]
        save_database(db)
        
        embed = discord.Embed(
            title="✅ Reward Removed",
            description=f"Reward for role **{role.name}** has been removed.",
            color=0x50C878
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message("❌ That role is not currently set as a reward
