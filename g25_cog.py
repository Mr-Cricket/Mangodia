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
from discord import app_commands
from typing import Literal
import functools
import uuid

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

def parse_g25_multi(coord_block: str):
    """Parses a block of G25 coordinates into a DataFrame."""
    lines = coord_block.strip().split('\n')
    data = {}
    for line in lines:
        if not line.strip():
            continue
        name, coords = parse_g25_coords(line)
        if name and coords:
            data[name] = coords
    return pd.DataFrame.from_dict(data, orient='index', columns=[f'PC{i+1}' for i in range(25)])


class G25Commands(commands.Cog, name="G25"):
    """Commands for Global 25 genetic ancestry analysis."""
    def __init__(self, bot):
        self.bot = bot
        self.db_pool = None
        self.g25_data = None # Initialize as None
        self.bot.loop.create_task(self.load_data_async()) # Start loading data in the background
        self.bot.loop.create_task(self.connect_to_db())

    async def load_data_async(self):
        """Load the large CSV file in the background to avoid blocking."""
        print("Starting background load of g25_scaled_data.csv...")
        try:
            # Run the synchronous pandas read_csv in an executor
            blocking_task = functools.partial(pd.read_csv, 'g25_scaled_data.csv', index_col=0)
            self.g25_data = await self.bot.loop.run_in_executor(None, blocking_task)
            print("G25 scaled data loaded successfully in the background.")
        except FileNotFoundError:
            print("ERROR: g25_scaled_data.csv not found. Please add it to your project repository.")
        except Exception as e:
            print(f"An error occurred during async data loading: {e}")


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
                        user_id BIGINT NOT NULL,
                        sample_name TEXT NOT NULL,
                        sample_type TEXT NOT NULL,
                        coordinates JSONB NOT NULL,
                        PRIMARY KEY (user_id, sample_name)
                    );
                ''')
            print("G25 Cog: Successfully connected to PostgreSQL database.")
        except Exception as e:
            print(f"G25 Cog: Failed to connect to database: {e}")

    def cog_unload(self):
        if self.db_pool:
            self.bot.loop.create_task(self.db_pool.close())

    async def get_user_coords(self, user_id, sample_name):
        if not self.db_pool: return None
        async with self.db_pool.acquire() as connection:
            record = await connection.fetchrow('SELECT sample_name, coordinates FROM g25_user_coordinates WHERE user_id = $1 AND sample_name = $2', user_id, sample_name)
        return {'name': record['sample_name'], 'coords': json.loads(record['coordinates'])} if record else None

    g25 = app_commands.Group(name="g25", description="Commands for G25 genetic analysis.")

    @g25.command(name='addcoords', description='Adds or updates a G25 coordinate sample.')
    @app_commands.describe(
        sample_type="Is this your personal sample for the leaderboard, or just a test sample?",
        g25_string="Your coordinates as a comma-separated string.",
        attachment="Your coordinates as a .csv or .txt file."
    )
    async def add_coords(self, interaction: discord.Interaction, sample_type: Literal['Personal', 'Sample'], g25_string: str = None, attachment: discord.Attachment = None):
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
            await interaction.followup.send("Invalid G25 format. Please use: `SampleName,coord1,coord2,...,coord25`")
            return

        async with self.db_pool.acquire() as connection:
            # Check if the record already exists to provide better feedback
            existing_record = await connection.fetchval(
                'SELECT 1 FROM g25_user_coordinates WHERE user_id = $1 AND sample_name = $2',
                interaction.user.id, name
            )

            # Perform the upsert operation (insert or update)
            await connection.execute('''
                INSERT INTO g25_user_coordinates (user_id, sample_name, sample_type, coordinates) VALUES ($1, $2, $3, $4)
                ON CONFLICT (user_id, sample_name) DO UPDATE 
                SET sample_type = EXCLUDED.sample_type, coordinates = EXCLUDED.coordinates;
            ''', interaction.user.id, name, sample_type, json.dumps(coords))
        
        # Provide contextual feedback to the user
        if existing_record:
            await interaction.followup.send(f"A sample named '{name}' already existed and has been updated with the new coordinates.")
        else:
            await interaction.followup.send(f"Successfully saved new sample '{name}' as type '{sample_type}'.")

    @g25.command(name='removecoords', description='Removes one of your saved G25 samples.')
    @app_commands.describe(sample_name="The exact name of the sample you want to remove.")
    async def remove_coords(self, interaction: discord.Interaction, sample_name: str):
        await interaction.response.defer(ephemeral=True)
        if not self.db_pool:
            await interaction.followup.send("Database connection is not available.")
            return

        async with self.db_pool.acquire() as connection:
            result = await connection.execute(
                'DELETE FROM g25_user_coordinates WHERE user_id = $1 AND sample_name = $2',
                interaction.user.id,
                sample_name
            )

        if result == 'DELETE 1':
            await interaction.followup.send(f"Successfully removed the sample named '{sample_name}'.")
        else:
            await interaction.followup.send(f"Could not find a sample named '{sample_name}' saved under your user.")

    @g25.command(name='distance', description='Calculates genetic distance to a population.')
    @app_commands.describe(
        sample_name="The name of the saved sample you want to use.",
        population_name="The exact name of the population from the data file."
    )
    async def distance(self, interaction: discord.Interaction, sample_name: str, population_name: str):
        await interaction.response.defer()
        user_info = await self.get_user_coords(interaction.user.id, sample_name)
        if not user_info:
            await interaction.followup.send(f"You don't have a saved sample named '{sample_name}'.")
            return
        if self.g25_data is None:
            await interaction.followup.send("G25 population data is still loading, please try again in a moment.")
            return

        try:
            pop_coords = self.g25_data.loc[population_name].values
            dist = calculate_distance(user_info['coords'], pop_coords)
            await interaction.followup.send(f"Genetic distance between **{user_info['name']}** and **{population_name}**: `{dist:.4f}`")
        except KeyError:
            await interaction.followup.send(f"Population '{population_name}' not found. Use `/g25 search` or `/g25 listall` to find the correct name.")

    @g25.command(name='model', description='Model a sample using source populations and generate a pie chart.')
    @app_commands.describe(
        target_sample_name="The name of your saved sample to model.",
        source_populations="Comma-separated list of populations from the main data file.",
        custom_sources_string="Custom source populations as a block of text.",
        custom_sources_file="A .txt or .csv file with custom source populations."
    )
    async def model(self, interaction: discord.Interaction, target_sample_name: str, source_populations: str = None, custom_sources_string: str = None, custom_sources_file: discord.Attachment = None):
        await interaction.response.defer()

        target_info = await self.get_user_coords(interaction.user.id, target_sample_name)
        if not target_info:
            await interaction.followup.send(f"You don't have a saved sample named '{target_sample_name}'.")
            return

        target_coords = np.array(target_info['coords'])
        source_df = pd.DataFrame()

        if custom_sources_file:
            try:
                content = (await custom_sources_file.read()).decode('utf-8')
                source_df = parse_g25_multi(content)
            except Exception as e:
                await interaction.followup.send(f"Error reading custom source file: {e}")
                return
        elif custom_sources_string:
            source_df = parse_g25_multi(custom_sources_string)
        elif source_populations:
            if self.g25_data is None:
                await interaction.followup.send("G25 population data is still loading, please try again in a moment.")
                return
            pop_names = [name.strip() for name in source_populations.split(',')]
            try:
                source_df = self.g25_data.loc[pop_names]
            except KeyError as e:
                await interaction.followup.send(f"Population '{e.args[0]}' not found. Check spelling or use `/g25 search`.")
                return
        else:
            await interaction.followup.send("You must provide one source: `source_populations`, `custom_sources_string`, or `custom_sources_file`.")
            return

        if source_df.empty or len(source_df) < 2:
            await interaction.followup.send("Could not find at least 2 valid source populations to create a model.")
            return

        source_matrix = source_df.values.T
        result, _, _, _ = np.linalg.lstsq(source_matrix, target_coords, rcond=None)
        
        proportions = result
        proportions[proportions < 0] = 0
        if total := np.sum(proportions):
            proportions = (proportions / total) * 100

        fitted_coords = np.dot(source_matrix, result)
        distance = calculate_distance(target_coords, fitted_coords)

        embed = discord.Embed(title=f"Admixture Model for {target_info['name']}", color=discord.Color.blue())
        fit_message = "Good Fit (< 0.03)" if distance < 0.03 else "Okay Fit (< 0.05)" if distance < 0.05 else "Poor Fit (>= 0.05)"
        embed.description = f"**Distance (Fit):** `{distance:.4f}` ({fit_message})\n\n**Admixture Proportions:**"
        
        sorted_results = sorted(zip(source_df.index, proportions), key=lambda x: x[1], reverse=True)
        
        chart_labels = []
        chart_values = []
        other_total = 0.0

        for name, percent in sorted_results:
            if percent > 1.0: # Threshold for including in the main chart
                embed.add_field(name=name, value=f"{percent:.2f}%", inline=True)
                chart_labels.append(name)
                chart_values.append(percent)
            elif percent > 0.01:
                other_total += percent

        if other_total > 0:
             chart_labels.append("Other")
             chart_values.append(other_total)

        # Generate Pie Chart
        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(10, 7), subplot_kw=dict(aspect="equal"))
        wedges, texts, autotexts = ax.pie(chart_values, autopct='%1.1f%%', startangle=90, textprops={'color': 'white'})
        ax.legend(wedges, chart_labels, title="Populations", loc="center left", bbox_to_anchor=(1, 0, 0.5, 1))
        plt.setp(autotexts, size=10, weight="bold")
        ax.set_title(f"Admixture Composition for {target_info['name']}")

        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight')
        buf.seek(0)
        plt.close()
        
        file = discord.File(buf, filename="admixture_chart.png")
        embed.set_image(url="attachment://admixture_chart.png")

        await interaction.followup.send(embed=embed, file=file)


    @g25.command(name='leaderboard', description='Shows who is most similar to a population or custom sample.')
    @app_commands.describe(
        population_name="[EITHER] The name of the population from the data file.",
        custom_target_string="[OR] A custom target sample as a string.",
        custom_target_file="[OR] A custom target sample as a file."
    )
    async def g25_leaderboard(self, interaction: discord.Interaction, population_name: str = None, custom_target_string: str = None, custom_target_file: discord.Attachment = None):
        await interaction.response.defer()

        target_coords = None
        target_name = ""
        
        if sum(p is not None for p in [population_name, custom_target_string, custom_target_file]) != 1:
            await interaction.followup.send("Please provide exactly one target: `population_name`, `custom_target_string`, or `custom_target_file`.")
            return

        if population_name:
            if self.g25_data is None:
                await interaction.followup.send("G25 population data is still loading, please try again in a moment.")
                return
            try:
                target_coords = self.g25_data.loc[population_name].values
                target_name = population_name
            except KeyError:
                await interaction.followup.send(f"Population '{population_name}' not found.")
                return
        elif custom_target_string:
            target_name, target_coords = parse_g25_coords(custom_target_string)
            if not target_name:
                await interaction.followup.send("Invalid format for `custom_target_string`.")
                return
        elif custom_target_file:
            try:
                content = (await custom_target_file.read()).decode('utf-8')
                target_name, target_coords = parse_g25_coords(content)
                if not target_name:
                    await interaction.followup.send("Invalid format for the custom target file.")
                    return
            except Exception as e:
                await interaction.followup.send(f"Error reading custom target file: {e}")
                return

        async with self.db_pool.acquire() as connection:
            personal_samples = await connection.fetch("SELECT sample_name, coordinates FROM g25_user_coordinates WHERE sample_type = 'Personal'")

        if not personal_samples:
            await interaction.followup.send("No 'Personal' samples have been added for the leaderboard yet.")
            return

        distances = sorted(
            [(r['sample_name'], calculate_distance(json.loads(r['coordinates']), target_coords)) for r in personal_samples],
            key=lambda x: x[1]
        )

        embed = discord.Embed(title=f"G25 Leaderboard: Closest to {target_name}", color=discord.Color.gold())
        embed.description = "\n".join([f"{i+1}. **{name}** - Distance: `{dist:.4f}`" for i, (name, dist) in enumerate(distances[:10])])
        await interaction.followup.send(embed=embed)

    @g25.command(name='search', description='Search for available population names.')
    @app_commands.describe(query="The name (or part of the name) to search for.")
    async def search_population(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer(ephemeral=True)
        if self.g25_data is None:
            await interaction.followup.send("G25 population data is still loading, please try again in a moment.")
            return

        matches = [pop for pop in self.g25_data.index if query.lower() in pop.lower()]
        if not matches:
            await interaction.followup.send(f"No populations found matching '{query}'.")
            return

        response_text = "Found the following matches:\n" + "\n".join(matches[:25])
        if len(response_text) > 1990: response_text = response_text[:1980] + "\n..."
        await interaction.followup.send(f"```{response_text}```")

    @g25.command(name='listall', description='Sends you a private file with all available population names.')
    async def list_all_populations(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if self.g25_data is None:
            await interaction.followup.send("G25 population data is still loading, please try again in a moment.")
            return

        try:
            all_pops_string = "\n".join(self.g25_data.index)
            file_buffer = io.BytesIO(all_pops_string.encode('utf-8'))
            await interaction.followup.send("Here is the full list of available populations.", file=discord.File(file_buffer, "population_list.txt"))
        except Exception as e:
            logger.error(f"Error creating population list file: {e}")
            await interaction.followup.send("Sorry, I couldn't generate the population list.")


async def setup(bot: commands.Bot):
    await bot.add_cog(G25Commands(bot))
