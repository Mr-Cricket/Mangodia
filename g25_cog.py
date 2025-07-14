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
from typing import Literal, Optional
import functools
import uuid
from itertools import combinations

# --- Helper Functions ---

def calculate_distance(coords1, coords2):
    # This is kept for single calculations like in /compare
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
        self.g25_data = None
        self.bot.loop.create_task(self.load_data_async())
        self.bot.loop.create_task(self.connect_to_db())

    async def load_data_async(self):
        """Load the large CSV file in the background to avoid blocking."""
        print("Starting background load of g25_scaled_data.csv...")
        try:
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
                await connection.execute('''
                    CREATE TABLE IF NOT EXISTS g25_saved_models (
                        user_id BIGINT NOT NULL,
                        model_name TEXT NOT NULL,
                        populations TEXT[] NOT NULL,
                        PRIMARY KEY (user_id, model_name)
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
            await interaction.followup.send("Database connection is not available.")
            return

        if attachment:
            try:
                g25_string = (await attachment.read()).decode('utf-8')
            except Exception as e:
                await interaction.followup.send(f"Error reading attachment: {e}")
                return
        
        if not g25_string:
            await interaction.followup.send("Please provide your G25 coordinates as a string or attach a file.")
            return

        name, coords = parse_g25_coords(g25_string)
        if not name or not coords:
            await interaction.followup.send("Invalid G25 format. Please use: `SampleName,coord1,...`")
            return

        async with self.db_pool.acquire() as connection:
            existing_record = await connection.fetchval('SELECT 1 FROM g25_user_coordinates WHERE user_id = $1 AND sample_name = $2', interaction.user.id, name)
            await connection.execute('''
                INSERT INTO g25_user_coordinates (user_id, sample_name, sample_type, coordinates) VALUES ($1, $2, $3, $4)
                ON CONFLICT (user_id, sample_name) DO UPDATE SET sample_type = EXCLUDED.sample_type, coordinates = EXCLUDED.coordinates;
            ''', interaction.user.id, name, sample_type, json.dumps(coords))
        
        if existing_record:
            await interaction.followup.send(f"A sample named '{name}' already existed and has been updated.")
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
            result = await connection.execute('DELETE FROM g25_user_coordinates WHERE user_id = $1 AND sample_name = $2', interaction.user.id, sample_name)

        if result == 'DELETE 1':
            await interaction.followup.send(f"Successfully removed the sample named '{sample_name}'.")
        else:
            await interaction.followup.send(f"Could not find a sample named '{sample_name}' saved under your user.")

    @g25.command(name='mysamples', description='Lists all of your saved G25 coordinate samples.')
    async def my_samples(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not self.db_pool:
            await interaction.followup.send("Database is not available.")
            return

        async with self.db_pool.acquire() as connection:
            samples = await connection.fetch('SELECT sample_name, sample_type FROM g25_user_coordinates WHERE user_id = $1 ORDER BY sample_name', interaction.user.id)

        if not samples:
            await interaction.followup.send("You have no saved samples. Use `/g25 addcoords` to add one.")
            return
        
        description = "Here are your saved samples:\n\n"
        for sample in samples:
            type_icon = "👤" if sample['sample_type'] == 'Personal' else "🧪"
            description += f"{type_icon} `{sample['sample_name']}`\n"
            
        embed = discord.Embed(title="Your Saved G25 Samples", description=description, color=0x2B2D31)
        await interaction.followup.send(embed=embed)

    @g25.command(name='compare', description='Calculates the genetic distance between two of your saved samples.')
    @app_commands.describe(sample_a="The name of your first saved sample.", sample_b="The name of your second saved sample.")
    async def compare(self, interaction: discord.Interaction, sample_a: str, sample_b: str):
        await interaction.response.defer()
        info_a = await self.get_user_coords(interaction.user.id, sample_a)
        info_b = await self.get_user_coords(interaction.user.id, sample_b)

        if not info_a or not info_b:
            await interaction.followup.send("Could not find one or both of the specified samples.")
            return
        
        dist = calculate_distance(info_a['coords'], info_b['coords'])
        await interaction.followup.send(f"Genetic distance between **{info_a['name']}** and **{info_b['name']}**: `{dist:.4f}`")

    @g25.command(name='distance', description='Calculates genetic distance to a specific population.')
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

    @g25.command(name='oracle', description='Finds the closest populations to your sample.')
    @app_commands.describe(
        sample_name="The name of the saved sample you want to analyze.",
        mode="The type of Oracle model to run."
    )
    async def oracle(self, interaction: discord.Interaction, sample_name: str, mode: Literal['1-Way (Single Population)', '2-Way Population Mix', '4-Way Population Mix']):
        await interaction.response.defer()
        user_info = await self.get_user_coords(interaction.user.id, sample_name)
        if not user_info:
            await interaction.followup.send(f"You don't have a saved sample named '{sample_name}'.")
            return
        if self.g25_data is None:
            await interaction.followup.send("G25 population data is still loading, please try again in a moment.")
            return

        target_coords = np.array(user_info['coords'])
        
        embed = discord.Embed(title=f"Oracle Results for {user_info['name']}", color=0x2B2D31)
        
        all_coords = self.g25_data.values
        distances_np = np.linalg.norm(all_coords - target_coords, axis=1)
        distances = pd.Series(distances_np, index=self.g25_data.index)

        # Helper function to paginate long results into multiple embed fields
        def paginate_results(title: str, results_lines: list[str], embed_to_add: discord.Embed):
            field_value = "```\n"
            field_title = title
            for line in results_lines:
                if len(field_value) + len(line) + 4 > 1024:
                    field_value += "```"
                    embed_to_add.add_field(name=field_title, value=field_value, inline=False)
                    field_title = "..." # Use a continuation title
                    field_value = "```\n"
                field_value += line + "\n"
            field_value += "```"
            embed_to_add.add_field(name=field_title, value=field_value, inline=False)


        if '1-Way' in mode:
            closest_pops = distances.sort_values().head(20)
            lines = [f"{dist:<12.8f} {pop_name}" for pop_name, dist in closest_pops.items()]
            paginate_results("1-Way Results", lines, embed)

        if '2-Way' in mode or '4-Way' in mode:
            await interaction.edit_original_response(content="This is a complex calculation, please wait...")
            
            NUM_SOURCE_POPS = 25 
            
            source_pops = distances.sort_values().head(NUM_SOURCE_POPS).index
            source_df = self.g25_data.loc[source_pops]

            if '2-Way' in mode:
                results_2_way = []
                for combo in combinations(source_df.index, 2):
                    model_df = source_df.loc[list(combo)]
                    source_matrix = model_df.values.T
                    result, _, _, _ = np.linalg.lstsq(source_matrix, target_coords, rcond=None)
                    fitted_coords = np.dot(source_matrix, result)
                    distance = calculate_distance(target_coords, fitted_coords)
                    results_2_way.append({'distance': distance, 'model': combo, 'proportions': result})
                
                best_2_way = sorted(results_2_way, key=lambda x: x['distance'])[:15]
                lines = []
                for model in best_2_way:
                    props = model['proportions'] * 100
                    model_str = f"{props[0]:.1f}% {model['model'][0]} + {props[1]:.1f}% {model['model'][1]}"
                    lines.append(f"{model['distance']:<12.8f} {model_str}")
                paginate_results("2-Way Results", lines, embed)

            if '4-Way' in mode:
                results_4_way = []
                for combo in combinations(source_df.index, 4):
                    model_df = source_df.loc[list(combo)]
                    source_matrix = model_df.values.T
                    result, _, _, _ = np.linalg.lstsq(source_matrix, target_coords, rcond=None)
                    fitted_coords = np.dot(source_matrix, result)
                    distance = calculate_distance(target_coords, fitted_coords)
                    results_4_way.append({'distance': distance, 'model': combo, 'proportions': result})
                
                best_4_way = sorted(results_4_way, key=lambda x: x['distance'])[:15]
                lines = []
                for model in best_4_way:
                    props = model['proportions'] * 100
                    model_str = f"{props[0]:.1f}% {model['model'][0]} + {props[1]:.1f}% {model['model'][1]} + {props[2]:.1f}% {model['model'][2]} + {props[3]:.1f}% {model['model'][3]}"
                    lines.append(f"{model['distance']:<12.8f} {model_str}")
                paginate_results("4-Way Results", lines, embed)

        await interaction.edit_original_response(content=None, embed=embed)

    @g25.command(name='biased', description='Finds populations that one sample is closer to than another.')
    @app_commands.describe(
        sample_a="The name of your primary saved sample.",
        sample_b="The name of the sample you want to compare against."
    )
    async def biased(self, interaction: discord.Interaction, sample_a: str, sample_b: str):
        await interaction.response.defer()

        info_a = await self.get_user_coords(interaction.user.id, sample_a)
        info_b = await self.get_user_coords(interaction.user.id, sample_b)

        if not info_a or not info_b:
            await interaction.followup.send("Could not find one or both of the specified samples.")
            return
        if self.g25_data is None:
            await interaction.followup.send("G25 population data is still loading, please try again in a moment.")
            return

        coords_a = np.array(info_a['coords'])
        coords_b = np.array(info_b['coords'])
        
        all_coords = self.g25_data.values
        dist_a = np.linalg.norm(all_coords - coords_a, axis=1)
        dist_b = np.linalg.norm(all_coords - coords_b, axis=1)
        diffs_np = dist_a - dist_b
        diffs = pd.Series(diffs_np, index=self.g25_data.index)

        closer_to_a = diffs[diffs < 0].sort_values(ascending=True).head(15)
        closer_to_b = diffs[diffs > 0].sort_values(ascending=False).head(15)

        # Create the first embed
        desc_a = f"A: **{sample_a}**\nB: **{sample_b}**\nC: Populations closer to A\n"
        body_a = "```\n" + "\n".join([f"{diff:<12.8f} {pop}" for pop, diff in closer_to_a.items()]) + "```"
        embed_a = discord.Embed(description=desc_a + body_a, color=0x2B2D31)
        await interaction.edit_original_response(embed=embed_a)

        # Create the second embed and send as a new message
        desc_b = f"A: **{sample_a}**\nB: **{sample_b}**\nC: Populations closer to B\n"
        body_b = "```\n" + "\n".join([f"{diff:<12.8f} {pop}" for pop, diff in closer_to_b.items()]) + "```"
        embed_b = discord.Embed(description=desc_b + body_b, color=0x2B2D31)
        await interaction.followup.send(embed=embed_b)

    @g25.command(name='savemodel', description='Saves a list of source populations for easy reuse.')
    @app_commands.describe(model_name="A short name for your model (e.g., 'BronzeAge').", populations="A comma-separated list of source populations.")
    async def save_model(self, interaction: discord.Interaction, model_name: str, populations: str):
        await interaction.response.defer(ephemeral=True)
        if not self.db_pool:
            await interaction.followup.send("Database connection is not available.")
            return
        
        pop_list = [p.strip() for p in populations.split(',')]
        if len(pop_list) < 2:
            await interaction.followup.send("Please provide at least two populations.")
            return

        async with self.db_pool.acquire() as connection:
            await connection.execute('''
                INSERT INTO g25_saved_models (user_id, model_name, populations) VALUES ($1, $2, $3)
                ON CONFLICT (user_id, model_name) DO UPDATE SET populations = EXCLUDED.populations;
            ''', interaction.user.id, model_name, pop_list)
        
        await interaction.followup.send(f"Successfully saved model '{model_name}' with {len(pop_list)} populations.")

    @g25.command(name='findmodel', description='Finds the best 2 & 3-way models from a list of source populations.')
    @app_commands.describe(
        target_sample_name="The name of your saved sample to model.",
        source_model="[EITHER] The name of a saved model to use as sources.",
        source_populations="[OR] A comma-separated list of potential source populations (max 15)."
    )
    async def find_model(self, interaction: discord.Interaction, target_sample_name: str, source_model: Optional[str] = None, source_populations: Optional[str] = None):
        await interaction.response.defer()

        if not (source_model or source_populations):
            await interaction.followup.send("You must provide either a `source_model` or `source_populations`.")
            return

        target_info = await self.get_user_coords(interaction.user.id, target_sample_name)
        if not target_info:
            await interaction.followup.send(f"You don't have a saved sample named '{target_sample_name}'.")
            return
        
        if self.g25_data is None:
            await interaction.followup.send("G25 population data is still loading, please try again in a moment.")
            return

        target_coords = np.array(target_info['coords'])
        
        if source_model:
            async with self.db_pool.acquire() as conn:
                pop_list = await conn.fetchval('SELECT populations FROM g25_saved_models WHERE user_id = $1 AND model_name = $2', interaction.user.id, source_model)
            if not pop_list:
                await interaction.followup.send(f"Could not find a saved model named '{source_model}'.")
                return
        else:
            pop_list = [name.strip() for name in source_populations.split(',')]
        
        if len(pop_list) > 15:
            await interaction.followup.send("Please provide a maximum of 15 source populations.")
            return
        if len(pop_list) < 3:
            await interaction.followup.send("Please provide at least 3 source populations.")
            return

        try:
            source_df = self.g25_data.loc[pop_list]
        except KeyError as e:
            await interaction.followup.send(f"Population '{e.args[0]}' not found.")
            return
        
        best_2_way = {'distance': float('inf'), 'model': None, 'proportions': None}
        best_3_way = {'distance': float('inf'), 'model': None, 'proportions': None}

        for combo in combinations(source_df.index, 2):
            model_df = source_df.loc[list(combo)]
            source_matrix = model_df.values.T
            result, _, _, _ = np.linalg.lstsq(source_matrix, target_coords, rcond=None)
            fitted_coords = np.dot(source_matrix, result)
            distance = calculate_distance(target_coords, fitted_coords)
            if distance < best_2_way['distance']:
                best_2_way = {'distance': distance, 'model': combo, 'proportions': result}

        for combo in combinations(source_df.index, 3):
            model_df = source_df.loc[list(combo)]
            source_matrix = model_df.values.T
            result, _, _, _ = np.linalg.lstsq(source_matrix, target_coords, rcond=None)
            fitted_coords = np.dot(source_matrix, result)
            distance = calculate_distance(target_coords, fitted_coords)
            if distance < best_3_way['distance']:
                best_3_way = {'distance': distance, 'model': combo, 'proportions': result}

        embed = discord.Embed(title=f"Best-Fit Models for {target_info['name']}", color=0x2B2D31)

        if best_2_way['model']:
            props = best_2_way['proportions'] * 100
            model_str = "\n".join([f"`{props[i]:.2f}%` {name}" for i, name in enumerate(best_2_way['model'])])
            embed.add_field(name=f"Best 2-Way Model (Distance: {best_2_way['distance']:.4f})", value=model_str, inline=False)

        if best_3_way['model']:
            props = best_3_way['proportions'] * 100
            model_str = "\n".join([f"`{props[i]:.2f}%` {name}" for i, name in enumerate(best_3_way['model'])])
            embed.add_field(name=f"Best 3-Way Model (Distance: {best_3_way['distance']:.4f})", value=model_str, inline=False)

        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(G25Commands(bot))
