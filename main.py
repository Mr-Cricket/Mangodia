import discord
import os
import random
import logging
import asyncpg
from discord import app_commands

# --- Configuration ---
BOT_TOKEN = os.environ.get('DISCORD_TOKEN')
DATABASE_URL = os.environ.get('DATABASE_URL')

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Bot Initialization ---
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.invites = True

class MangodiaBot(discord.Client):
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.invites_cache = {}
        self.db_pool = None

    async def setup_hook(self):
        # This is the recommended place for async setup
        await self.connect_to_db()
        await self.load_cogs()
        synced = await self.tree.sync()
        logger.info(f'Synced {len(synced)} command(s)')

    async def connect_to_db(self):
        try:
            if not DATABASE_URL:
                logger.error("DATABASE_URL environment variable not set.")
                return
            self.db_pool = await asyncpg.create_pool(DATABASE_URL)
            logger.info("Successfully connected to PostgreSQL database.")
            await self.initialize_database_tables()
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")

    async def initialize_database_tables(self):
        if not self.db_pool: return
        async with self.db_pool.acquire() as connection:
            await connection.execute('''
                CREATE TABLE IF NOT EXISTS invite_rewards (
                    guild_id BIGINT,
                    role_id BIGINT,
                    required_invites INT,
                    PRIMARY KEY (guild_id, role_id)
                );
            ''')
            await connection.execute('''
                CREATE TABLE IF NOT EXISTS invite_users (
                    guild_id BIGINT,
                    user_id BIGINT,
                    invites INT DEFAULT 0,
                    leaves INT DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id)
                );
            ''')
        logger.info("Invite tracker database tables initialized.")

    async def load_cogs(self):
        try:
            await self.load_extension("g25_cog")
            logger.info("✅ Successfully loaded the G25 Cog.")
        except Exception as e:
            logger.error(f"❌ Failed to load G25 Cog: {e}")

client = MangodiaBot(intents=intents)

# --- GIF List ---
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

# --- Core Invite Logic ---
async def check_rewards(member: discord.Member):
    if not client.db_pool: return
    
    async with client.db_pool.acquire() as connection:
        user_data = await connection.fetchrow('SELECT invites, leaves FROM invite_users WHERE guild_id = $1 AND user_id = $2', member.guild.id, member.id)
        if not user_data: return

        net_invites = user_data['invites'] - user_data['leaves']
        rewards = await connection.fetch('SELECT role_id, required_invites FROM invite_rewards WHERE guild_id = $1', member.guild.id)

        for reward in rewards:
            role = member.guild.get_role(reward['role_id'])
            if role and net_invites >= reward['required_invites'] and role not in member.roles:
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
    logger.info(f'🤖 Logged in as {client.user} (ID: {client.user.id})')
    for guild in client.guilds:
        try:
            client.invites_cache[guild.id] = await guild.invites()
        except discord.Forbidden:
            logger.warning(f"Don't have permissions to get invites for {guild.name}")

@client.event
async def on_member_join(member: discord.Member):
    guild = member.guild
    logger.info(f"Member {member.name} joined {guild.name}")
    if not client.db_pool: return

    try:
        invites_before = client.invites_cache.get(guild.id, [])
        invites_after = await guild.invites()
        client.invites_cache[guild.id] = invites_after

        for invite in invites_before:
            used_invite = discord.utils.find(lambda i: i.code == invite.code, invites_after)
            if used_invite and invite.uses < used_invite.uses and invite.inviter:
                inviter = invite.inviter
                logger.info(f"{member.name} was invited by {inviter.name}")
                async with client.db_pool.acquire() as connection:
                    await connection.execute('''
                        INSERT INTO invite_users (guild_id, user_id, invites) VALUES ($1, $2, 1)
                        ON CONFLICT (guild_id, user_id) DO UPDATE SET invites = invite_users.invites + 1;
                    ''', guild.id, inviter.id)
                
                inviter_member = guild.get_member(inviter.id)
                if inviter_member:
                    await check_rewards(inviter_member)
                return
    except discord.Forbidden:
        logger.warning(f"Cannot track invites in {guild.name} due to missing permissions.")
    except Exception as e:
        logger.error(f"Error in on_member_join: {e}")

# --- COMMANDS ---
@client.tree.command(name="setup", description="Posts the server rules and FAQ embeds in the current channel.")
async def setup_command(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message("❌ You need 'Manage Messages' permission.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    
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
    
    rules_embed.set_footer(text="Violations may result in warnings, mutes, or bans • Stay awesome! �")
    rules_embed.set_thumbnail(url="https://cdn.discordapp.com/emojis/1234567890123456789.png")  # Replace with your server icon

    # --- GIF Embed for FAQ Attention ---
    gif_embed = discord.Embed(
        title="🏃‍♂️ **ATTENTION SPAN BOOSTER**",
        description="*Since your attention span is probably shorter than a TikTok video, here's some Subway Surfers gameplay while you read the FAQ below!*",
        color=0x4ECDC4  # Teal color
    )
    
    gif_embed.set_image(url=random.choice(subway_surfers_gifs))
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

    await interaction.channel.send(embeds=[rules_embed, gif_embed, faq_embed])
    await interaction.followup.send("✅ **Setup Complete!**", ephemeral=True)

# --- INVITE TRACKING COMMANDS (DB Version) ---
@client.tree.command(name="add-reward", description="Add a role to be given as an invite reward.")
@app_commands.describe(role="The role to be awarded.", invites="The number of invites required.")
async def add_reward(interaction: discord.Interaction, role: discord.Role, invites: int):
    if not interaction.user.guild_permissions.manage_roles:
        await interaction.response.send_message("❌ You need 'Manage Roles' permission.", ephemeral=True)
        return
    if invites < 1:
        await interaction.response.send_message("❌ Invite count must be at least 1.", ephemeral=True)
        return
    if not client.db_pool: return

    async with client.db_pool.acquire() as connection:
        await connection.execute('''
            INSERT INTO invite_rewards (guild_id, role_id, required_invites) VALUES ($1, $2, $3)
            ON CONFLICT (guild_id, role_id) DO UPDATE SET required_invites = EXCLUDED.required_invites;
        ''', interaction.guild.id, role.id, invites)
    
    await interaction.response.send_message(f"✅ Reward set: **{role.name}** for **{invites}** invites.", ephemeral=True)

@client.tree.command(name="invites", description="Check how many invites a user has.")
@app_commands.describe(user="The user to check (optional, defaults to you).")
async def invites_command(interaction: discord.Interaction, user: discord.Member = None):
    target_user = user or interaction.user
    if not client.db_pool: return
    
    async with client.db_pool.acquire() as connection:
        record = await connection.fetchrow('SELECT invites, leaves FROM invite_users WHERE guild_id = $1 AND user_id = $2', interaction.guild.id, target_user.id)

    invites = record['invites'] if record else 0
    leaves = record['leaves'] if record else 0
    net_invites = invites - leaves

    embed = discord.Embed(title=f"📊 Invite Stats for {target_user.display_name}", color=target_user.color)
    embed.set_thumbnail(url=target_user.display_avatar.url)
    embed.add_field(name="✅ Successful", value=invites, inline=True)
    embed.add_field(name="❌ Left", value=leaves, inline=True)
    embed.add_field(name="📈 Net", value=net_invites, inline=True)
    await interaction.response.send_message(embed=embed)

@client.tree.command(name="leaderboard", description="View the top inviters in the server.")
async def leaderboard_command(interaction: discord.Interaction):
    if not client.db_pool: return
    
    async with client.db_pool.acquire() as connection:
        records = await connection.fetch('''
            SELECT user_id, invites, leaves FROM invite_users
            WHERE guild_id = $1 AND (invites - leaves) > 0
            ORDER BY (invites - leaves) DESC
            LIMIT 10;
        ''', interaction.guild.id)

    embed = discord.Embed(title="🏆 Invite Leaderboard", description="Top inviters in the server:", color=0xFFD700)

    if not records:
        embed.description = "No one has any invites yet!"
    else:
        leaderboard_text = []
        for i, record in enumerate(records, 1):
            member = interaction.guild.get_member(record['user_id'])
            if member:
                net_invites = record['invites'] - record['leaves']
                leaderboard_text.append(f"{i}. **{member.display_name}** - {net_invites} invites")
        embed.description = "\n".join(leaderboard_text)

    await interaction.response.send_message(embed=embed)

# --- Run Bot ---
if __name__ == "__main__":
    if BOT_TOKEN:
        client.run(BOT_TOKEN)
    else:
        logger.error("❌ DISCORD_TOKEN not found in environment variables.")
