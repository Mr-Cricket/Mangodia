import discord
import os
import logging
import asyncpg
import asyncio
from discord.ext import commands
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
        # Initialize database and web server
        await self.init_database()
        self.loop.create_task(self.run_web_server())

        # Load all command cogs
        logger.info("Loading cogs...")
        await self.load_extension("g25_cog")
        await self.load_extension("rules_cog")
        await self.load_extension("invite_cog")
        logger.info("All cogs loaded.")

        # Sync all commands from all cogs
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

    # --- Database Helper Methods (now on the bot instance) ---
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
                used_invite = discord.utils.find(lambda i: i.code == invite.code, invites_after_join)
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
