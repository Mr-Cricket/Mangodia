import discord
from discord.ext import commands
import pandas as pd
import numpy as np
from sklearn.decomposition import PCA
import matplotlib.pyplot as plt
import io
import json
import os
import asyncpg

def calculate_distance(coords1, coords2):
    return np.linalg.norm(np.array(coords1) - np.array(coords2))

def parse_g25_coords(coord_string: str):
    try:
        parts = coord_string.strip().split(',')
        name = parts[0]
        coords = [float(p) for p in parts[1:]]
        if len(coords) != 25:
            return None, None
        return name, coords
    except (ValueError, IndexError):
        return None, None

class G25Commands(commands.Cog, name="G25"):
    """Commands for Global 25 genetic ancestry analysis."""
    def __init__(self, bot):
        self.bot = bot
        self.db_pool = None

        try:
            self.g25_data = pd.read_csv('g25_scaled_data.csv', index_col=0)
            print("G25 scaled data loaded successfully.")
        except FileNotFoundError:
            print("ERROR: g25_scaled_data.csv not found. Please add it to your project repository.")
            self.g25_data = None

        self.bot.loop.create_task(self.connect_to_db())

    async def connect_to_db(self):
        try:
            database_url = os.getenv('DATABASE_URL')
            if not database_url:
                print("ERROR: G25 Cog - DATABASE_URL environment variable not set.")
                return

            self.db_pool = await asyncpg.create_pool(database_url)
            async with self.db_pool.acquire() as connection:
                await connection.execute('''
                    CREATE TABLE IF NOT EXISTS g25_user_coordinates (
                        user_id BIGINT PRIMARY KEY,
                        sample_name TEXT NOT NULL,
                        coordinates JSONB NOT NULL
                    );
                ''')
            print("G25 Cog: Successfully connected to PostgreSQL database.")
        except Exception as e:
            print(f"G25 Cog: Failed to connect to database: {e}")

    def cog_unload(self):
        if self.db_pool:
            self.bot.loop.create_task(self.db_pool.close())

    async def get_user_coords(self, user_id):
        if not self.db_pool: return None
        async with self.db_pool.acquire() as connection:
            record = await connection.fetchrow('SELECT sample_name, coordinates FROM g25_user_coordinates WHERE user_id = $1', user_id)
        return {'name': record['sample_name'], 'coords': json.loads(record['coordinates'])} if record else None

    g25 = discord.app_commands.Group(name="g25", description="Commands for G25 genetic analysis.")

    @g25.command(name='addcoords', description='Adds or updates your G25 coordinates.')
    async def add_coords(self, interaction: discord.Interaction, g25_string: str = None, attachment: discord.Attachment = None):
        await interaction.response.defer(ephemeral=True)
        if not self.db_pool:
            await interaction.followup.send("Database connection is not available. Please contact the administrator.")
            return

        if attachment and (attachment.filename.endswith('.csv') or attachment.filename.endswith('.txt')):
            try:
                g25_string = (await attachment.read()).decode('utf-8')
            except Exception as e:
                await interaction.followup.send(f"Error reading attachment: {e}")
                return
        
        if not g25_string:
            await interaction.followup.send("Please provide your G25 coordinates as a string or attach a .csv/.txt file.")
            return

        name, coords = parse_g25_coords(g25_string)
        if not name or not coords:
            await interaction.followup.send("Invalid G25 format. Please use: `YourName,coord1,coord2,...,coord25`")
            return

        async with self.db_pool.acquire() as connection:
            await connection.execute('''
                INSERT INTO g25_user_coordinates (user_id, sample_name, coordinates) VALUES ($1, $2, $3)
                ON CONFLICT (user_id) DO UPDATE SET sample_name = EXCLUDED.sample_name, coordinates = EXCLUDED.coordinates;
            ''', interaction.user.id, name, json.dumps(coords))
        
        await interaction.followup.send(f"Coordinates for '{name}' added successfully for user {interaction.user.mention}.")

    @g25.command(name='distance', description='Calculates genetic distance to a population.')
    async def distance(self, interaction: discord.Interaction, population_name: str):
        await interaction.response.defer()
        user_info = await self.get_user_coords(interaction.user.id)
        if not user_info:
            await interaction.followup.send("You need to add your coordinates first using `/g25 addcoords`.")
            return
        if self.g25_data is None:
            await interaction.followup.send("G25 population data is not loaded. Please contact the bot administrator.")
            return

        try:
            pop_coords = self.g25_data.loc[population_name].values
            dist = calculate_distance(user_info['coords'], pop_coords)
            await interaction.followup.send(f"Genetic distance between **{user_info['name']}** and **{population_name}**: `{dist:.4f}`")
        except KeyError:
            await interaction.followup.send(f"Population '{population_name}' not found.")

    @g25.command(name='pca', description='Generates a PCA plot of your coordinates.')
    async def pca(self, interaction: discord.Interaction):
        await interaction.response.defer()
        user_info = await self.get_user_coords(interaction.user.id)
        if not user_info:
            await interaction.followup.send("You need to add your coordinates first using `/g25 addcoords`.")
            return
        if self.g25_data is None:
            await interaction.followup.send("G25 population data is not loaded. Please contact the bot administrator.")
            return

        user_name, user_coords = user_info['name'], np.array(user_info['coords'])
        full_data = self.g25_data.append(pd.Series(user_coords, index=self.g25_data.columns, name=user_name))
        
        pca_model = PCA(n_components=2)
        principal_components = pca_model.fit_transform(full_data)
        pca_df = pd.DataFrame(data=principal_components, columns=['PC1', 'PC2'], index=full_data.index)

        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(12, 8))
        ax.scatter(pca_df['PC1'], pca_df['PC2'], color='gray', s=10, label='Global Populations')
        user_pc = pca_df.loc[user_name]
        ax.scatter(user_pc['PC1'], user_pc['PC2'], color='red', s=100, label=user_name, edgecolors='white')
        ax.set_xlabel(f"PC1 ({pca_model.explained_variance_ratio_[0]*100:.2f}%)")
        ax.set_ylabel(f"PC2 ({pca_model.explained_variance_ratio_[1]*100:.2f}%)")
        ax.set_title("G25 PCA Plot")
        ax.legend()
        ax.grid(True, linestyle='--', alpha=0.3)

        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        buf.seek(0)
        plt.close()

        await interaction.followup.send(file=discord.File(buf, 'pca_plot.png'))

    @g25.command(name='leaderboard', description='Shows who is most similar to a population.')
    async def g25_leaderboard(self, interaction: discord.Interaction, population_name: str):
        await interaction.response.defer()
        if self.g25_data is None or not self.db_pool:
            await interaction.followup.send("Bot is not ready. Data or database is unavailable.")
            return

        try:
            pop_coords = self.g25_data.loc[population_name].values
        except KeyError:
            await interaction.followup.send(f"Population '{population_name}' not found.")
            return

        async with self.db_pool.acquire() as connection:
            all_users = await connection.fetch('SELECT sample_name, coordinates FROM g25_user_coordinates')

        if not all_users:
            await interaction.followup.send("No user coordinates have been added yet.")
            return

        distances = sorted(
            [(r['sample_name'], calculate_distance(json.loads(r['coordinates']), pop_coords)) for r in all_users],
            key=lambda x: x[1]
        )

        embed = discord.Embed(title=f"G25 Leaderboard: Closest to {population_name}", color=discord.Color.gold())
        embed.description = "\n".join([f"{i+1}. **{name}** - Distance: `{dist:.4f}`" for i, (name, dist) in enumerate(distances[:10])])
        await interaction.followup.send(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(G25Commands(bot))
