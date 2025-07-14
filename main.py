import discord
import os
import random
import logging
import asyncpg
import asyncio
from discord.ext import commands
from discord import app_commands
import uvicorn
from fastapi import FastAPI, Response
import json

# --- Configuration ---
BOT_TOKEN = os.environ.get('DISCORD_TOKEN')
DATABASE_URL = os.environ.get('DATABASE_URL')
PORT = int(os.environ.get('PORT', 8080))

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Web Server Setup ---
api = FastAPI()
@api.get("/")
def root():
    return {"status": "Mangodia Bot is alive"}

@api.head("/")
def head_root():
    return Response(status_code=200)

# This endpoint will serve the interactive plot HTML
@api.get("/plot/{plot_id}", response_class=Response)
async def get_plot(plot_id: str):
    # This line assumes 'bot' is a globally accessible instance of your MangodiaBot class
    plot_data = bot.pca_plot_data.get(plot_id)
    if not plot_data:
        return Response(content="Plot not found or has expired.", status_code=404)
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>G25 PCA Plot</title>
        <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
        <style>
            body {{ font-family: sans-serif; background-color: #1e1f22; color: #dcddde; margin: 0; }}
            #plotdiv {{ width: 100vw; height: 100vh; }}
        </style>
    </head>
    <body>
        <div id="plotdiv"></div>
        <script>
            var plotData = {json.dumps(plot_data['data'])};
            var layout = {json.dumps(plot_data['layout'])};
            Plotly.newPlot('plotdiv', plotData, layout);
        </script>
    </body>
    </html>
    """
    return Response(content=html_content, media_type="text/html")

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

class MangodiaBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True
        intents.invites = True
        
        super().__init__(command_prefix='!', intents=intents)
        
        self.invites_cache = {}
        self.db_pool = None
        self.pca_plot_data = {}

    async def setup_hook(self):
        await self.init_database()
        await self.load_extension("g25_cog")
        self.loop.create_task(self.run_web_server())

        # Commands must be added to the tree before syncing
        self.tree.add_command(self.setup)
        self.tree.add_command(self.profile)
        self.tree.add_command(self.add_reward)
        self.tree.add_command(self.remove_reward)
        self.tree.add_command(self.rewards)
        self.tree.add_command(self.invites)
        self.tree.add_command(self.leaderboard)

        # Sync should be one of the last things you do in setup_hook
        synced = await self.tree.sync()
        logger.info(f'✅ Synced {len(synced)} command(s)')

    async def run_web_server(self):
        config = uvicorn.Config(api, host="0.0.0.0", port=PORT, log_level="warning")
        server = uvicorn.Server(config)
        await server.serve()

    async def close(self):
        if self.db_pool:
            await self.db_pool.close()
        await super().close()

    async def init_database(self):
        try:
            self.db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
            async with self.db_pool.acquire() as conn:
                await conn.execute("CREATE TABLE IF NOT EXISTS guilds (guild_id BIGINT PRIMARY KEY, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS invite_rewards (
                        guild_id BIGINT REFERENCES guilds(guild_id) ON DELETE CASCADE,
                        role_id BIGINT,
                        required_invites INTEGER,
                        PRIMARY KEY (guild_id, role_id)
                    )
                """)
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS invite_users (
                        guild_id BIGINT REFERENCES guilds(guild_id) ON DELETE CASCADE,
                        user_id BIGINT,
                        invites INTEGER DEFAULT 0,
                        leaves INTEGER DEFAULT 0,
                        PRIMARY KEY (guild_id, user_id)
                    )
                """)
            logger.info("Database initialized successfully")
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
            if self.db_pool:
                await self.db_pool.close()

    # --- Database Helper Methods ---
    async def ensure_guild_in_db(self, guild_id):
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("INSERT INTO guilds (guild_id) VALUES ($1) ON CONFLICT (guild_id) DO NOTHING", guild_id)
        except Exception as e:
            logger.error(f"Error ensuring guild in database: {e}")

    async def ensure_user_in_db(self, guild_id, user_id):
        await self.ensure_guild_in_db(guild_id)
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO invite_users (guild_id, user_id, invites, leaves) VALUES ($1, $2, 0, 0)
                    ON CONFLICT (guild_id, user_id) DO NOTHING
                """, guild_id, user_id)
        except Exception as e:
            logger.error(f"Error ensuring user in database: {e}")

    async def get_user_invites(self, guild_id, user_id):
        try:
            async with self.db_pool.acquire() as conn:
                result = await conn.fetchrow("SELECT invites, leaves FROM invite_users WHERE guild_id = $1 AND user_id = $2", guild_id, user_id)
                return (result['invites'], result['leaves']) if result else (0, 0)
        except Exception as e:
            logger.error(f"Error getting user invites: {e}")
            return (0, 0)

    async def update_user_invites(self, guild_id, user_id, invite_change=0, leave_change=0):
        await self.ensure_user_in_db(guild_id, user_id)
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    UPDATE invite_users SET invites = invites + $1, leaves = leaves + $2
                    WHERE guild_id = $3 AND user_id = $4
                """, invite_change, leave_change, guild_id, user_id)
        except Exception as e:
            logger.error(f"Error updating user invites: {e}")

    async def get_guild_rewards(self, guild_id):
        try:
            async with self.db_pool.acquire() as conn:
                result = await conn.fetch("SELECT role_id, required_invites FROM invite_rewards WHERE guild_id = $1", guild_id)
                return {str(row['role_id']): row['required_invites'] for row in result}
        except Exception as e:
            logger.error(f"Error getting guild rewards: {e}")
            return {}

    async def add_guild_reward(self, guild_id, role_id, required_invites):
        await self.ensure_guild_in_db(guild_id)
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO invite_rewards (guild_id, role_id, required_invites) VALUES ($1, $2, $3)
                    ON CONFLICT (guild_id, role_id) DO UPDATE SET required_invites = $3
                """, guild_id, role_id, required_invites)
        except Exception as e:
            logger.error(f"Error adding guild reward: {e}")

    async def remove_guild_reward(self, guild_id, role_id):
        try:
            async with self.db_pool.acquire() as conn:
                result = await conn.execute("DELETE FROM invite_rewards WHERE guild_id = $1 AND role_id = $2", guild_id, role_id)
                return result != "DELETE 0"
        except Exception as e:
            logger.error(f"Error removing guild reward: {e}")
            return False

    async def get_guild_users_leaderboard(self, guild_id, limit=10):
        try:
            async with self.db_pool.acquire() as conn:
                result = await conn.fetch("""
                    SELECT user_id, invites, leaves, (invites - leaves) as net_invites FROM invite_users
                    WHERE guild_id = $1 AND (invites - leaves) > 0
                    ORDER BY net_invites DESC LIMIT $2
                """, guild_id, limit)
                return [(row['user_id'], row['invites'], row['leaves'], row['net_invites']) for row in result]
        except Exception as e:
            logger.error(f"Error getting guild leaderboard: {e}")
            return []

    # --- Utility Method ---
    def find_invite_by_code(self, invite_list, code):
        return discord.utils.find(lambda i: i.code == code, invite_list)

    async def check_rewards(self, member: discord.Member):
        rewards = await self.get_guild_rewards(member.guild.id)
        invites, leaves = await self.get_user_invites(member.guild.id, member.id)
        total_invites = invites - leaves

        for role_id, required_invites in rewards.items():
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
    async def on_ready(self):
        logger.info(f'🤖 Logged in as {self.user} (ID: {self.user.id})')
        for guild in self.guilds:
            try:
                self.invites_cache[guild.id] = await guild.invites()
                await self.ensure_guild_in_db(guild.id)
            except discord.Forbidden:
                logger.warning(f"Don't have permissions to get invites for {guild.name}")
            except Exception as e:
                logger.error(f"Error caching invites for {guild.name}: {e}")

    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        logger.info(f"Member {member.name} joined {guild.name}")
        try:
            invites_before_join = self.invites_cache.get(guild.id, [])
            invites_after_join = await guild.invites()
            self.invites_cache[guild.id] = invites_after_join

            for invite in invites_before_join:
                used_invite = self.find_invite_by_code(invites_after_join, invite.code)
                if used_invite and invite.uses < used_invite.uses and invite.inviter:
                    logger.info(f"{member.name} was invited by {invite.inviter.name}")
                    await self.update_user_invites(guild.id, invite.inviter.id, invite_change=1)
                    
                    inviter_member = guild.get_member(invite.inviter.id)
                    if inviter_member:
                        await self.check_rewards(inviter_member)
                    return
        except discord.Forbidden:
            logger.warning(f"Cannot track invites in {guild.name} due to missing permissions.")
        except Exception as e:
            logger.error(f"Error in on_member_join: {e}")

    async def on_member_remove(self, member: discord.Member):
        logger.info(f"Member {member.name} left {member.guild.name}")

    async def on_invite_create(self, invite: discord.Invite):
        try:
            self.invites_cache[invite.guild.id] = await invite.guild.invites()
        except Exception as e:
            logger.error(f"Error updating invite cache on create: {e}")

    async def on_invite_delete(self, invite: discord.Invite):
        try:
            self.invites_cache[invite.guild.id] = await invite.guild.invites()
        except Exception as e:
            logger.error(f"Error updating invite cache on delete: {e}")

    # --- COMMANDS ---
    @app_commands.command(name="setup", description="Posts the server rules and FAQ embeds in the current channel.")
    async def setup(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("❌ You need 'Manage Messages' permission.", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            rules_embed = discord.Embed(title="📜 **MANGODIA RULES**", description="Please read and adhere to the following rules. Failure to do so will result in disciplinary action.", color=0xFF6B6B)
            rules_embed.add_field(name="💬 **1. Keep the Discussion Cordial**", value="Discrimination is not tolerated. This includes racism, sexism, homophobia, transphobia, ableism, etc. There's a fine line between edgy humour and actual discrimination. Keep it just witty banter, but nothing more. Millions must love.", inline=False)
            rules_embed.add_field(name="🚫 **2. NO EXTREMIST SYMBOLISM OR IDEOLOGY**", value="Discord does not bloody tolerate overt extremism of any kind, and they do not care if it's an edgy joke. Nazi or fascist adjacent symbolism will be immediately removed and you will be muted. This is not brain surgery; it's very simple.", inline=False)
            rules_embed.add_field(name="🔴 **3. NO PAEDOPHILIA**", value="Permaban.", inline=False)
            rules_embed.add_field(name="📢 **4. No raiding or spamming**", value="Raiding or spamming is grounds for a permaban at the discretion of a staff member. It's just Discord, it's not that serious. Don't ruin the server for other people.", inline=False)
            rules_embed.add_field(name="🔒 **5. No ban or mute evasion**", value="Staff will review ban and mute appeals with a degree of frequency. There is no reason to evade, this is grounds for a permaban. Staff members that abuse their permission will be reprimanded.", inline=False)
            rules_embed.add_field(name="🏷️ **6. Do not tag staff unless it is an emergency**", value="You aren't funny, you are just a bellend.", inline=False)
            rules_embed.add_field(name="🔞 **7. No NSFW/NSFL content**", value="All content must be Safe For Work. No explicit or NSFW material should be shared on this server. It's disturbing, and you should seek help instead of posting on Discord.", inline=False)
            rules_embed.add_field(name="🎭 **8. No Impersonation**", value="Do not impersonate other users, staff, or public figures. This includes using similar usernames, profile pictures, or pretending to be someone else in chat. Your impersonation slop account is not hilarious. Staff will not be laughing when you get kicked.", inline=False)
            rules_embed.add_field(name="📺 **9. No Self-Promotion or Advertising**", value="Don't advertise or promote your content, Discord servers, or other platforms without permission from mods. If you want to partner, do it through the appropriate avenues.", inline=False)
            rules_embed.add_field(name="🇬🇧 **10. ENGLISH ONLY**", value="There are ESL channels for non-English speakers. Otherwise, you must speak the King's English to keep discussion in general channels readable.", inline=False)
            rules_embed.add_field(name="📍 **11. Try to use the appropriate channel**", value="Try to keep content in the relevant channel to avoid cluttering channels.", inline=False)
            rules_embed.add_field(name="🔐 **12. Do not dox, threaten to dox, or share personal details**", value="Any malicious actors who threaten to dox any member of the server. You will be lucky if you only get banned. Discord should never be this serious, and we take the well-being of members of Mangodia seriously.", inline=False)
            rules_embed.add_field(name="⚖️ **13. Follow Discord TOS**", value="I know that none of you have read it, but everyone must comply with the Discord TOS regardless. If you do not comply with Discord TOS in any way then you will be banned.", inline=False)
            rules_embed.set_footer(text="Thank you for your cooperation. • Mangodia Staff Team")
            
            gif_embed = discord.Embed(title="🏃‍♂️ **ATTENTION SPAN BOOSTER**", description="*The average attention span in this server is approximately that of a goldfish so we expect to still be countlessly asked these questions. Here's some Subway Surfers gameplay to keep your attention while you read the FAQ below!*", color=0x4ECDC4)
            gif_embed.set_image(url=random.choice(subway_surfers_gifs))
            gif_embed.set_footer(text="Now you can focus on reading the FAQ below, you tiktok brained zoomers.")
            
            faq_embed = discord.Embed(title="❓ **FREQUENTLY ASKED QUESTIONS**", description="We expect to still be asked these questions countlessly despite this FAQ existing.", color=0x45B7D1)
            faq_embed.add_field(name="🖼️ **How do I get pic perms?**", value="Members who want image perms need to invite five members to the server. Invitations are tracked, and image perms are automatically given when a member invites five members to the server. This helps with growth and helps not to pollute the server with unfunny shitposts.", inline=False)
            faq_embed.add_field(name="🛡️ **How do I become a mod?**", value="We do not accept mod applications. Members will be given mod if Mango or anyone else with role perms likes them. If you aren't annoying and are semi-active, there's a very decent chance you will get mod.", inline=False)
            faq_embed.add_field(name="📋 **How do I appeal?**", value="There is a ticket system where people can send tickets with what punishment they received and a short explanation as to why it was not justified. Mods that repeatedly issue unfair infractions will be reprimanded and could be removed from the mod team.", inline=False)
            faq_embed.set_footer(text="Still have questions? Don't hesitate to ask in the general chat! 💬")
            
            main_message = await interaction.channel.send(embeds=[rules_embed, gif_embed, faq_embed])
            await main_message.add_reaction("📜")
            await main_message.add_reaction("🏃‍♂️")
            await main_message.add_reaction("✅")
            
            await interaction.followup.send("✅ **Setup Complete!**", ephemeral=True)
        except Exception as e:
            logger.error(f"Error in setup command: {e}")
            await interaction.followup.send("❌ An error occurred during setup. Please try again.", ephemeral=True)

    @app_commands.command(name="profile", description="Shows a combined profile for a user.")
    @app_commands.describe(user="The user to view the profile of (optional, defaults to you).")
    async def profile(self, interaction: discord.Interaction, user: discord.Member = None):
        target_user = user or interaction.user
        await interaction.response.defer()

        try:
            invites, leaves = await self.get_user_invites(interaction.guild.id, target_user.id)
            net_invites = invites - leaves

            async with self.db_pool.acquire() as connection:
                g25_samples = await connection.fetch('SELECT sample_name, sample_type FROM g25_user_coordinates WHERE user_id = $1 ORDER BY sample_name', target_user.id)

            embed = discord.Embed(title=f"Profile for {target_user.display_name}", color=target_user.color)
            embed.set_thumbnail(url=target_user.display_avatar.url)
            
            invite_info = f"**Net Invites:** {net_invites} (`{invites}` joined, `{leaves}` left)"
            embed.add_field(name="✉️ Invite Stats", value=invite_info, inline=False)

            if g25_samples:
                g25_info = "\n".join([f"{'👤' if s['sample_type'] == 'Personal' else '🧪'} `{s['sample_name']}`" for s in g25_samples])
                embed.add_field(name="🧬 Saved G25 Samples", value=g25_info, inline=False)
            else:
                embed.add_field(name="🧬 Saved G25 Samples", value="No samples saved yet.", inline=False)

            user_info = f"**Joined Server:** {discord.utils.format_dt(target_user.joined_at, 'R')}\n"
            user_info += f"**Account Created:** {discord.utils.format_dt(target_user.created_at, 'R')}"
            embed.add_field(name="👤 User Information", value=user_info, inline=False)

            await interaction.followup.send(embed=embed)
        except Exception as e:
            logger.error(f"Error in profile command: {e}")
            await interaction.followup.send("❌ An error occurred while fetching the profile.", ephemeral=True)

    @app_commands.command(name="add_reward", description="Add a role to be given as an invite reward.")
    @app_commands.describe(role="The role to be awarded.", invites="The number of invites required.")
    async def add_reward(self, interaction: discord.Interaction, role: discord.Role, invites: int):
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.response.send_message("❌ You need 'Manage Roles' permission.", ephemeral=True)
            return
        if invites < 1:
            await interaction.response.send_message("❌ Invite count must be at least 1.", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            await self.add_guild_reward(interaction.guild.id, role.id, invites)
            embed = discord.Embed(title="✅ Reward Added", description=f"Users will now get the **{role.name}** role for **{invites}** invites!", color=0x50C878)
            await interaction.followup.send(embed=embed)
        except Exception as e:
            logger.error(f"Error in add_reward command: {e}")
            await interaction.followup.send("❌ An error occurred while adding the reward.", ephemeral=True)

    @app_commands.command(name="remove_reward", description="Remove an invite reward role.")
    @app_commands.describe(role="The reward role to remove.")
    async def remove_reward(self, interaction: discord.Interaction, role: discord.Role):
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.response.send_message("❌ You need 'Manage Roles' permission.", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            if await self.remove_guild_reward(interaction.guild.id, role.id):
                embed = discord.Embed(title="✅ Reward Removed", description=f"Reward for role **{role.name}** has been removed.", color=0x50C878)
                await interaction.followup.send(embed=embed)
            else:
                await interaction.followup.send("❌ That role is not currently set as a reward.", ephemeral=True)
        except Exception as e:
            logger.error(f"Error in remove_reward command: {e}")
            await interaction.followup.send("❌ An error occurred while removing the reward.", ephemeral=True)

    @app_commands.command(name="rewards", description="View all current invite rewards.")
    async def rewards(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        try:
            rewards = await self.get_guild_rewards(interaction.guild.id)
            if not rewards:
                await interaction.followup.send("❌ No invite rewards are currently set up.", ephemeral=True)
                return
            
            embed = discord.Embed(title="🏆 Invite Rewards", description="Here are all the current invite rewards:", color=0xFFD700)
            for role_id, required_invites in sorted(rewards.items(), key=lambda x: x[1]):
                role = interaction.guild.get_role(int(role_id))
                if role:
                    embed.add_field(name=f"**{role.name}**", value=f"{required_invites} invites", inline=True)
            
            await interaction.followup.send(embed=embed)
        except Exception as e:
            logger.error(f"Error in rewards command: {e}")
            await interaction.followup.send("❌ An error occurred while fetching rewards.", ephemeral=True)

    @app_commands.command(name="invites", description="Check how many invites a user has.")
    @app_commands.describe(user="The user to check (optional, defaults to you).")
    async def invites(self, interaction: discord.Interaction, user: discord.Member = None):
        await interaction.response.defer()
        
        target_user = user or interaction.user
        
        try:
            invites, leaves = await self.get_user_invites(interaction.guild.id, target_user.id)
            net_invites = invites - leaves
            
            embed = discord.Embed(title=f"📊 Invite Stats for {target_user.display_name}", description=f"**Total Invites:** {net_invites}", color=target_user.color or 0x2F3136)
            embed.set_thumbnail(url=target_user.display_avatar.url)
            embed.add_field(name="✅ Successful Invites", value=invites, inline=True)
            embed.add_field(name="❌ Left Members", value=leaves, inline=True)
            embed.add_field(name="📈 Net Invites", value=net_invites, inline=True)
            
            await interaction.followup.send(embed=embed)
        except Exception as e:
            logger.error(f"Error in invites command: {e}")
            await interaction.followup.send("❌ An error occurred while fetching invite stats.", ephemeral=True)

    @app_commands.command(name="leaderboard", description="View the top inviters in the server.")
    async def leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        try:
            users = await self.get_guild_users_leaderboard(interaction.guild.id)
            if not users:
                await interaction.followup.send("❌ No invite data available yet.", ephemeral=True)
                return
            
            embed = discord.Embed(title="🏆 Invite Leaderboard", description="Top inviters in the server:", color=0xFFD700)
            for i, (user_id, invites, leaves, net_invites) in enumerate(users, 1):
                member = interaction.guild.get_member(user_id)
                if member:
                    embed.add_field(name=f"{i}. {member.display_name}", value=f"{net_invites} invites", inline=False)
            
            if not embed.fields:
                embed.description = "No one has any invites yet!"
            
            await interaction.followup.send(embed=embed)
        except Exception as e:
            logger.error(f"Error in leaderboard command: {e}")
            await interaction.followup.send("❌ An error occurred while fetching the leaderboard.", ephemeral=True)

# --- Create Bot Instance ---
bot = MangodiaBot()

# --- Run Bot ---
if __name__ == "__main__":
    if not BOT_TOKEN:
        logger.error("❌ DISCORD_TOKEN not found in environment variables.")
        exit(1)
    if not DATABASE_URL:
        logger.error("❌ DATABASE_URL not found in environment variables.")
        exit(1)
    
    try:
        bot.run(BOT_TOKEN)
    except discord.LoginFailure:
        logger.error("❌ Invalid bot token. Please check your DISCORD_TOKEN environment variable.")
    except Exception as e:
        logger.error(f"❌ Error starting bot: {e}")
