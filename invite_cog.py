import discord
from discord.ext import commands
from discord import app_commands
import logging

logger = logging.getLogger(__name__)

class InviteCog(commands.Cog, name="Invite Tracker"):
    """Commands for tracking invites, rewards, and user profiles."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="profile", description="Shows a combined profile for a user.")
    @app_commands.describe(user="The user to view the profile of (optional, defaults to you).")
    async def profile(self, interaction: discord.Interaction, user: discord.Member = None):
        target_user = user or interaction.user
        await interaction.response.defer()

        try:
            invites, leaves = await self.bot.get_user_invites(interaction.guild.id, target_user.id)
            net_invites = invites - leaves

            g25_samples = []
            if self.bot.db_pool:
                try:
                    async with self.bot.db_pool.acquire() as connection:
                        g25_samples = await connection.fetch('SELECT sample_name, sample_type FROM g25_user_coordinates WHERE user_id = $1 ORDER BY sample_name', target_user.id)
                except Exception as e:
                    logger.warning(f"Could not fetch G25 samples for profile: {e}")

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
            await self.bot.add_guild_reward(interaction.guild.id, role.id, invites)
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
            if await self.bot.remove_guild_reward(interaction.guild.id, role.id):
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
            rewards = await self.bot.get_guild_rewards(interaction.guild.id)
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
            invites, leaves = await self.bot.get_user_invites(interaction.guild.id, target_user.id)
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
            users = await self.bot.get_guild_users_leaderboard(interaction.guild.id)
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

# This function is called by the bot's load_extension()
async def setup(bot: commands.Bot):
    await bot.add_cog(InviteCog(bot))
