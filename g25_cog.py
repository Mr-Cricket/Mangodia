import discord
from discord.ext import commands
import pandas as pd
import numpy as np
from sklearn.decomposition import PCA
import matplotlib.pyplot as plt
import plotly.graph_objects as go # Using Plotly for interactive plots
import io
import json
import os
import asyncpg
from discord import app_commands
from typing import Literal, Optional, List
import functools
import uuid
from itertools import combinations

# --- Helper Functions ---

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

    # --- Autocomplete Functions ---
    async def sample_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        if not self.db_pool:
            return []
        async with self.db_pool.acquire() as conn:
            records = await conn.fetch("SELECT sample_name FROM g25_user_coordinates WHERE user_id = $1 AND sample_name ILIKE $2", interaction.user.id, f'%{current}%')
        return [app_commands.Choice(name=r['sample_name'], value=r['sample_name']) for r in records][:25]

    async def model_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        if not self.db_pool:
            return []
        async with self.db_pool.acquire() as conn:
            records = await conn.fetch("SELECT model_name FROM g25_saved_models WHERE user_id = $1 AND model_name ILIKE $2", interaction.user.id, f'%{current}%')
        return [app_commands.Choice(name=r['model_name'], value=r['model_name']) for r in records][:25]

    g25 = app_commands.Group(name="g25", description="Commands for G25 genetic analysis.")

    @g25.command(name='addcoords', description='Save your G25 coordinates to the bot for easy use.')
    @app_commands.describe(
        sample_type="Choose 'Personal' for your main sample, or 'Sample' for tests.",
        g25_string="Paste your full G25 coordinate string here.",
        attachment="Or, upload a .txt or .csv file with your coordinates."
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
    @app_commands.autocomplete(sample_name=sample_autocomplete)
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

    @g25.command(name='mysamples', description='View a list of all your saved G25 coordinate samples.')
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
    @app_commands.autocomplete(sample_a=sample_autocomplete, sample_b=sample_autocomplete)
    async def compare(self, interaction: discord.Interaction, sample_a: str, sample_b: str):
        await interaction.response.defer()
        info_a = await self.get_user_coords(interaction.user.id, sample_a)
        info_b = await self.get_user_coords(interaction.user.id, sample_b)

        if not info_a or not info_b:
            await interaction.followup.send("Could not find one or both of the specified samples.")
            return
        
        dist = calculate_distance(info_a['coords'], info_b['coords'])
        await interaction.followup.send(f"Genetic distance between **{info_a['name']}** and **{info_b['name']}**: `{dist:.4f}`")

    @g25.command(name='distance', description='Calculates genetic distance from your sample to a population.')
    @app_commands.describe(
        sample_name="The name of your saved sample to use.",
        population_name="The exact name of the population from the main data file."
    )
    @app_commands.autocomplete(sample_name=sample_autocomplete)
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

    @g25.command(name='oracle', description='Models your sample against the closest populations in the main data.')
    @app_commands.describe(
        sample_name="The name of your saved sample to analyze.",
        mode="The type of Oracle model to run."
    )
    @app_commands.autocomplete(sample_name=sample_autocomplete)
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
                    field_title = f"{title} (cont.)"
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
                    
                    result[result < 0] = 0
                    total = np.sum(result)
                    if total > 0:
                        result = result / total

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

                    result[result < 0] = 0
                    total = np.sum(result)
                    if total > 0:
                        result = result / total

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

    @g25.command(name='biased', description='Compares two samples to see which populations are closer to each.')
    @app_commands.describe(
        sample_a="The name of your first saved sample.",
        sample_b="The name of the sample you want to compare against."
    )
    @app_commands.autocomplete(sample_a=sample_autocomplete, sample_b=sample_autocomplete)
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

    @g25.command(name='savemodel', description='Saves a list of populations as a reusable model.')
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

    @g25.command(name='findmodel', description='Finds the best-fit n-way models from a custom list of sources.')
    @app_commands.describe(
        target_sample="[Target] The name of your saved sample to model.",
        target_population_name="[Target] The name of a population from the main data file.",
        target_g25_string="[Target] The target sample as a G25 string.",
        target_attachment="[Target] The target sample as a .txt or .csv file.",
        source_model="[Source] The name of a saved model to use.",
        source_populations="[Source] A comma-separated list of populations from the main data file.",
        saved_source_names="[Source] A comma-separated list of your own saved samples.",
        custom_sources_string="[Source] Custom source populations as a block of text.",
        custom_sources_file="[Source] A .txt or .csv file with custom source populations."
    )
    @app_commands.autocomplete(target_sample=sample_autocomplete, source_model=model_autocomplete, saved_source_names=sample_autocomplete)
    async def find_model(self, interaction: discord.Interaction, 
                         target_sample: Optional[str] = None,
                         target_population_name: Optional[str] = None,
                         target_g25_string: Optional[str] = None,
                         target_attachment: Optional[discord.Attachment] = None,
                         source_model: Optional[str] = None, 
                         source_populations: Optional[str] = None,
                         saved_source_names: Optional[str] = None,
                         custom_sources_string: Optional[str] = None,
                         custom_sources_file: Optional[discord.Attachment] = None):
        await interaction.response.defer()

        # --- Get Target Sample ---
        target_info = None
        target_inputs = sum(p is not None for p in [target_sample, target_g25_string, target_attachment, target_population_name])
        if target_inputs != 1:
            await interaction.followup.send("Please provide exactly one target method: `target_sample`, `target_population_name`, `target_g25_string`, or `target_attachment`.")
            return

        if target_sample:
            target_info = await self.get_user_coords(interaction.user.id, target_sample)
            if not target_info:
                await interaction.followup.send(f"You don't have a saved sample named '{target_sample}'.")
                return
        elif target_population_name:
            if self.g25_data is None:
                await interaction.followup.send("G25 population data is still loading, please try again in a moment.")
                return
            try:
                coords = self.g25_data.loc[target_population_name].values
                target_info = {'name': target_population_name, 'coords': coords}
            except KeyError:
                await interaction.followup.send(f"Target population '{target_population_name}' not found in the main data file.")
                return
        elif target_g25_string:
            name, coords = parse_g25_coords(target_g25_string)
            if not name or not coords:
                await interaction.followup.send("Invalid format for `target_g25_string`.")
                return
            target_info = {'name': name, 'coords': coords}
        elif target_attachment:
            try:
                content = (await target_attachment.read()).decode('utf-8')
                name, coords = parse_g25_coords(content)
                if not name or not coords:
                    await interaction.followup.send("Invalid format for the target attachment file.")
                    return
                target_info = {'name': name, 'coords': coords}
            except Exception as e:
                await interaction.followup.send(f"Error reading target attachment: {e}")
                return
        
        if self.g25_data is None:
            await interaction.followup.send("G25 population data is still loading, please try again in a moment.")
            return

        target_coords = np.array(target_info['coords'])
        
        # --- Build the Source DataFrame from multiple inputs ---
        source_dfs = []
        pop_list = []

        if source_model:
            async with self.db_pool.acquire() as conn:
                model_pops = await conn.fetchval('SELECT populations FROM g25_saved_models WHERE user_id = $1 AND model_name = $2', interaction.user.id, source_model)
            if not model_pops:
                await interaction.followup.send(f"Could not find a saved model named '{source_model}'.")
                return
            pop_list.extend(model_pops)

        if source_populations:
            pop_list.extend([name.strip() for name in source_populations.split(',')])
        
        if pop_list:
            try:
                source_dfs.append(self.g25_data.loc[list(set(pop_list))])
            except KeyError as e:
                await interaction.followup.send(f"Population '{e.args[0]}' not found in main data.")
                return

        if saved_source_names:
            saved_names_list = [name.strip() for name in saved_source_names.split(',')]
            saved_samples_data = {}
            for name in saved_names_list:
                sample_info = await self.get_user_coords(interaction.user.id, name)
                if sample_info:
                    saved_samples_data[name] = sample_info['coords']
                else:
                    await interaction.followup.send(f"Could not find a saved sample of yours named '{name}'.")
                    return
            if saved_samples_data:
                source_dfs.append(pd.DataFrame.from_dict(saved_samples_data, orient='index', columns=self.g25_data.columns))

        custom_content = None
        if custom_sources_file:
            try:
                custom_content = (await custom_sources_file.read()).decode('utf-8')
            except Exception as e:
                await interaction.followup.send(f"Error reading custom source file: {e}")
                return
        elif custom_sources_string:
            custom_content = custom_sources_string
        
        if custom_content:
            custom_df = parse_g25_multi(custom_content)
            if not custom_df.empty:
                source_dfs.append(custom_df)

        if not source_dfs:
            await interaction.followup.send("You must provide at least one source: `source_model`, `source_populations`, `saved_source_names`, or custom sources.")
            return

        source_df = pd.concat(source_dfs)
        source_df = source_df[~source_df.index.duplicated(keep='first')]

        if len(source_df) < 6: # Need at least 6 sources for a 6-way model
            await interaction.followup.send(f"Please provide at least 6 unique source populations in total to run all models. You provided {len(source_df)}.")
            return
        
        await interaction.edit_original_response(content="Calculating models... this may take a moment.")
        
        # --- Refactored Model Calculation ---
        best_models = {i: {'distance': float('inf'), 'model': None, 'proportions': None} for i in range(2, 7)}

        # Loop through model types (2-way, 3-way, etc.)
        for n_way in range(2, 7):
            for combo in combinations(source_df.index, n_way):
                model_df = source_df.loc[list(combo)]
                source_matrix = model_df.values.T
                result, _, _, _ = np.linalg.lstsq(source_matrix, target_coords, rcond=None)
                
                result[result < 0] = 0
                total = np.sum(result)
                if total > 0:
                    result = result / total

                fitted_coords = np.dot(source_matrix, result)
                distance = calculate_distance(target_coords, fitted_coords)

                if distance < best_models[n_way]['distance']:
                    best_models[n_way] = {'distance': distance, 'model': combo, 'proportions': result}

        embed = discord.Embed(title=f"Best-Fit Models for {target_info['name']}", color=0x2B2D31)

        for n_way, model_data in best_models.items():
            if model_data['model']:
                props = model_data['proportions'] * 100
                # Dynamically build the model string
                model_str_parts = [f"`{props[i]:.2f}%` {name}" for i, name in enumerate(model_data['model'])]
                model_str = "\n".join(model_str_parts)
                embed.add_field(name=f"Best {n_way}-Way Model (Distance: {model_data['distance']:.4f})", value=model_str, inline=False)

        await interaction.edit_original_response(content=None, embed=embed)

    @g25.command(name='leaderboard', description='Ranks users by genetic distance to a target population.')
    @app_commands.describe(
        target_saved_sample="[Target] The name of one of your saved samples.",
        target_population_name="[Target] The name of a population from the main data file.",
        custom_target_string="[Target] A custom target sample as a G25 string.",
        custom_target_file="[Target] A custom target sample as a file."
    )
    @app_commands.autocomplete(target_saved_sample=sample_autocomplete)
    async def g25_leaderboard(self, interaction: discord.Interaction, 
                              target_saved_sample: Optional[str] = None,
                              target_population_name: Optional[str] = None, 
                              custom_target_string: Optional[str] = None, 
                              custom_target_file: Optional[discord.Attachment] = None):
        await interaction.response.defer()

        target_coords = None
        target_name = ""
        
        target_inputs = sum(p is not None for p in [target_saved_sample, target_population_name, custom_target_string, custom_target_file])
        if target_inputs != 1:
            await interaction.followup.send("Please provide exactly one target method: `target_saved_sample`, `target_population_name`, `custom_target_string`, or `custom_target_file`.")
            return

        if target_saved_sample:
            target_info = await self.get_user_coords(interaction.user.id, target_saved_sample)
            if not target_info:
                await interaction.followup.send(f"You don't have a saved sample named '{target_saved_sample}'.")
                return
            target_name = target_info['name']
            target_coords = target_info['coords']
        elif target_population_name:
            if self.g25_data is None:
                await interaction.followup.send("G25 population data is still loading, please try again in a moment.")
                return
            try:
                target_coords = self.g25_data.loc[target_population_name].values
                target_name = target_population_name
            except KeyError:
                await interaction.followup.send(f"Population '{target_population_name}' not found.")
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
            personal_samples = await connection.fetch("SELECT user_id, sample_name, coordinates FROM g25_user_coordinates WHERE sample_type = 'Personal'")

        if not personal_samples:
            await interaction.followup.send("No 'Personal' samples have been added for the leaderboard yet.")
            return

        distances = []
        for r in personal_samples:
            user = self.bot.get_user(r['user_id']) or await self.bot.fetch_user(r['user_id'])
            user_name = user.display_name if user else f"User ID: {r['user_id']}"
            dist = calculate_distance(json.loads(r['coordinates']), target_coords)
            distances.append({'user': user_name, 'sample': r['sample_name'], 'distance': dist})

        distances = sorted(distances, key=lambda x: x['distance'])

        embed = discord.Embed(title=f"G25 Leaderboard: Closest to {target_name}", color=discord.Color.gold())
        description = "\n".join([f"{i+1}. **{item['user']}** (`{item['sample']}`) - Distance: `{item['distance']:.4f}`" for i, item in enumerate(distances[:10])])
        embed.description = description
        await interaction.followup.send(embed=embed)

    # --- NEW COMMANDS ---
    
    @g25.command(name='plot', description='Generates a 2D PCA plot to visualize genetic distances.')
    @app_commands.describe(
        plot_type="Choose between a quick image or a detailed interactive link.",
        target_samples="[Optional] Your saved samples to highlight in red (comma-separated).",
        background_populations="[Optional] Populations from the main data to show as grey context (comma-separated).",
        custom_samples_string="[Optional] Custom samples as a block of text to plot in cyan.",
        custom_samples_file="[Optional] A .txt or .csv file with custom samples to plot in cyan."
    )
    @app_commands.autocomplete(target_samples=sample_autocomplete)
    async def plot(self, interaction: discord.Interaction, 
                   plot_type: Literal['Simple (Image)', 'Advanced (Interactive Link)'],
                   target_samples: Optional[str] = None, 
                   background_populations: Optional[str] = None,
                   custom_samples_string: Optional[str] = None,
                   custom_samples_file: Optional[discord.Attachment] = None):
        await interaction.response.defer()

        if self.g25_data is None:
            await interaction.followup.send("G25 population data is still loading, please try again in a moment.")
            return

        plot_data_list = []
        
        # 1. Add background populations
        if background_populations:
            pop_names = [name.strip() for name in background_populations.split(',')]
            try:
                for pop in pop_names:
                    plot_data_list.append({'name': pop, 'coords': self.g25_data.loc[pop], 'type': 'background'})
            except KeyError as e:
                await interaction.followup.send(f"Background population '{e.args[0]}' not found.")
                return

        # 2. Add user's target samples
        if target_samples:
            target_names = [name.strip() for name in target_samples.split(',')]
            for name in target_names:
                sample_info = await self.get_user_coords(interaction.user.id, name)
                if sample_info:
                    plot_data_list.append({'name': name, 'coords': sample_info['coords'], 'type': 'target'})
                else:
                    await interaction.followup.send(f"Could not find a saved sample of yours named '{name}'.")
                    return
        
        # 3. Add custom samples
        custom_content = None
        if custom_samples_file:
            try:
                custom_content = (await custom_samples_file.read()).decode('utf-8')
            except Exception as e:
                await interaction.followup.send(f"Error reading custom source file: {e}")
                return
        elif custom_samples_string:
            custom_content = custom_samples_string
        
        if custom_content:
            custom_df = parse_g25_multi(custom_content)
            for name, row in custom_df.iterrows():
                plot_data_list.append({'name': name, 'coords': row.values, 'type': 'custom'})

        if not plot_data_list:
            await interaction.followup.send("Please provide at least one sample or population to plot.")
            return

        # Prepare data for PCA
        all_coords = np.array([item['coords'] for item in plot_data_list])
        
        # Perform PCA
        pca = PCA(n_components=2)
        principal_components = pca.fit_transform(all_coords)
        
        if plot_type == 'Simple (Image)':
            # --- Create Matplotlib Image ---
            plt.style.use('dark_background')
            fig, ax = plt.subplots(figsize=(12, 8))

            for i, item in enumerate(plot_data_list):
                pc1, pc2 = principal_components[i]
                if item['type'] == 'background':
                    ax.scatter(pc1, pc2, c='gray', alpha=0.6)
                elif item['type'] == 'target':
                    ax.scatter(pc1, pc2, c='red', marker='*', s=150, edgecolors='white', label='Your Samples')
                    ax.text(pc1, pc2, f" {item['name']}", fontsize=9, color='white')
                elif item['type'] == 'custom':
                    ax.scatter(pc1, pc2, c='cyan', marker='o', s=80, edgecolors='white', label='Custom Samples')
                    ax.text(pc1, pc2, f" {item['name']}", fontsize=9, color='white')

            ax.set_xlabel(f'Principal Component 1 ({pca.explained_variance_ratio_[0]*100:.2f}%)')
            ax.set_ylabel(f'Principal Component 2 ({pca.explained_variance_ratio_[1]*100:.2f}%)')
            ax.set_title('G25 PCA Plot')
            ax.grid(True, which='both', linestyle='--', linewidth=0.5, alpha=0.5)
            
            handles, labels = ax.get_legend_handles_labels()
            by_label = dict(zip(labels, handles))
            ax.legend(by_label.values(), by_label.keys())

            buf = io.BytesIO()
            plt.savefig(buf, format='png', bbox_inches='tight')
            buf.seek(0)
            plt.close()
            
            file = discord.File(buf, filename="pca_plot.png")
            await interaction.followup.send(file=file)

        elif plot_type == 'Advanced (Interactive Link)':
            # --- Create Interactive Plotly Figure ---
            fig = go.Figure()

            for i, item in enumerate(plot_data_list):
                pc1, pc2 = principal_components[i]
                if item['type'] == 'background':
                    fig.add_trace(go.Scatter(x=[pc1], y=[pc2], mode='markers', marker=dict(color='gray', size=6, opacity=0.6), name='Background', text=item['name'], hoverinfo='text'))
                elif item['type'] == 'target':
                    fig.add_trace(go.Scatter(x=[pc1], y=[pc2], mode='markers+text', marker=dict(color='red', size=12, symbol='star'), text=item['name'], name='Your Samples', textposition="top center"))
                elif item['type'] == 'custom':
                    fig.add_trace(go.Scatter(x=[pc1], y=[pc2], mode='markers+text', marker=dict(color='cyan', size=10, symbol='circle'), text=item['name'], name='Custom Samples', textposition="top center"))

            fig.update_layout(
                title_text='G25 Interactive PCA Plot',
                xaxis_title=f'Principal Component 1 ({pca.explained_variance_ratio_[0]*100:.2f}%)',
                yaxis_title=f'Principal Component 2 ({pca.explained_variance_ratio_[1]*100:.2f}%)',
                template='plotly_dark',
                showlegend=True
            )
            
            plot_id = str(uuid.uuid4())
            self.bot.pca_plot_data[plot_id] = fig.to_json()

            base_url = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
            if base_url:
                plot_url = f"https://{base_url}/plot/{plot_id}"
            else: 
                plot_url = f"http://127.0.0.1:{os.environ.get('PORT', 8080)}/plot/{plot_id}"

            await interaction.followup.send(f"Your interactive PCA plot is ready! View it here: {plot_url}")


    @g25.command(name='search', description='Search for populations in the main data file.')
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
        if len(matches) > 25:
            response_text += f"\n...and {len(matches) - 25} more."
            
        if len(response_text) > 1990: response_text = response_text[:1980] + "\n..."
        await interaction.followup.send(f"```{response_text}```")

    @g25.command(name='listall', description='Get a file with all available population names.')
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
            print(f"Error creating population list file: {e}")
            await interaction.followup.send("Sorry, I couldn't generate the population list.")

    @g25.command(name="reload_data", description="[Owner Only] Reloads the G25 scaled data from the CSV file.")
    @commands.is_owner()
    async def reload_data(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.load_data_async()
        await interaction.followup.send("G25 data reload process has been initiated.")


async def setup(bot: commands.Bot):
    await bot.add_cog(G25Commands(bot))
