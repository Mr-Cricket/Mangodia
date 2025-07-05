# main.py
# Mangodia Discord Bot - Enhanced Version

import discord
import os
import random
import logging
from discord import app_commands

# --- Configuration ---
# The bot token is retrieved from environment variables for security.
BOT_TOKEN = os.environ.get('DISCORD_TOKEN')

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Bot Initialization ---
intents = discord.Intents.default()
intents.message_content = True  # Enable message content intent if needed
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

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

# --- Bot Events ---

@client.event
async def on_ready():
    """Fires when the bot has connected to Discord and is ready."""
    logger.info(f'🤖 Logged in as {client.user} (ID: {client.user.id})')
    try:
        synced = await tree.sync()
        logger.info(f'✅ Synced {len(synced)} command(s)')
    except Exception as e:
        logger.error(f'❌ Failed to sync commands: {e}')

@client.event
async def on_command_error(ctx, error):
    """Handle command errors gracefully."""
    logger.error(f'Command error: {error}')

# --- Bot Commands ---

@tree.command(name="setup", description="Posts the server rules and FAQ embeds in the current channel.")
async def setup_command(interaction: discord.Interaction):
    """Handles the /setup slash command to post server info."""
    # Check if user has manage messages permission
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message("❌ You need 'Manage Messages' permission to use this command.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    try:
        # --- Rules Embed with Enhanced Design ---
        rules_embed = discord.Embed(
            title="📜 **MANGODIA RULES**",
            description="*Please read and adhere to the following rules. Failure to do so will result in disciplinary action.*\n\n",
            color=0xFF6B6B  # Modern coral red
        )

        # Add a nice thumbnail
        rules_embed.set_thumbnail(url="https://cdn.discordapp.com/emojis/853658439068229642.png")

        # Enhanced rule formatting with emojis
        rules_list = [
            ("🤝 **Keep the Discussion Cordial**", "Discrimination is not tolerated. This includes racism, sexism, homophobia, transphobia, ableism, etc. There's a fine line between edgy humour and actual discrimination. Keep it just witty banter, but nothing more. Millions must love."),
            ("🚫 **NO EXTREMIST SYMBOLISM OR IDEOLOGY**", "Discord does not tolerate overt extremism of any kind, and they do not care if it's an edgy joke. Nazi or fascist adjacent symbolism will be immediately removed and you will be muted. This is not brain surgery; it's very simple."),
            ("⛔ **NO PAEDOPHILIA**", "Permaban."),
            ("📵 **No Raiding or Spamming**", "Raiding or spamming is grounds for a permaban at the discretion of a staff member. It's just Discord, it's not that serious. Don't ruin the server for other people."),
            ("🔒 **No Ban or Mute Evasion**", "Staff will review ban and mute appeals with a degree of frequency. There is no reason to evade, this is grounds for a permaban. Staff members that abuse their permission will be reprimanded."),
            ("🏷️ **Do Not Tag Staff Unless It Is an Emergency**", "You aren't funny, you are just a bellend."),
            ("🔞 **No NSFW/NSFL Content**", "All content must be Safe For Work. No explicit or NSFW material should be shared on this server. It's disturbing, and you should seek help instead of posting on Discord."),
            ("👤 **No Impersonation**", "Do not impersonate other users, staff, or public figures. This includes using similar usernames, profile pictures, or pretending to be someone else in chat. Your impersonation slop account is not hilarious."),
            ("📢 **No Self-Promotion or Advertising**", "Don't advertise or promote your content, Discord servers, or other platforms without permission from mods. If you want to partner, do it through the appropriate avenues."),
            ("🇬🇧 **ENGLISH ONLY**", "There are ESL channels for non-English speakers. Otherwise, you must speak the King's English to keep discussion in general channels readable."),
            ("📝 **Try to Use the Appropriate Channel**", "Try to keep content in the relevant channel to avoid cluttering channels."),
            ("🔐 **Do Not Dox, Threaten to Dox, or Share Personal Details**", "Any malicious actors who threaten to dox any member of the server. You will be lucky if you only get banned. Discord should never be this serious, and we take the well-being of members of Mangodia seriously."),
            ("📋 **Follow Discord TOS**", "I know that none of you have read it, but everyone must comply with the Discord TOS regardless. If you do not comply with Discord TOS in any way then you will be banned.")
        ]

        # Add rules with better formatting
        for i, (title, description) in enumerate(rules_list, 1):
            rules_embed.add_field(
                name=f"{i}. {title}", 
                value=f"> {description}", 
                inline=False
            )

        rules_embed.set_footer(
            text="Thank you for your cooperation. • Mangodia Staff Team",
            icon_url="https://cdn.discordapp.com/emojis/853658439068229642.png"
        )

        # --- Subway Surfers GIF Embed (Standalone) ---
        gif_embed = discord.Embed(
            title="🏃‍♂️ **ATTENTION SPAN BOOSTER**",
            description="*We expect to still be countlessly asked these questions despite clearly having a FAQ. Since the average attention span of members in this server is that of a goldfish. Here’s some gameplay to keep you attention*",
            color=0x4ECDC4  # Teal color
        )

        # Randomly select a GIF
        try:
            selected_gif = random.choice(subway_surfers_gifs)
            gif_embed.set_image(url=selected_gif)
            logger.info(f"Selected GIF: {selected_gif}")
        except Exception as e:
            logger.warning(f"Failed to set GIF: {e}")

        # --- FAQ Embed with Enhanced Design ---
        faq_embed = discord.Embed(
            title="❓ **FREQUENTLY ASKED QUESTIONS**",
            description="*We expect to still be countlessly asked these questions despite this FAQ existing.*\n\n",
            color=0x45B7D1  # Professional blue
        )

        faq_embed.set_thumbnail(url="https://cdn.discordapp.com/emojis/853658439068229642.png")

        # Enhanced FAQ formatting
        faq_items = [
            ("🖼️ **How do I get pic perms?**", "Members who want image perms need to **invite five members** to the server. Invitations are tracked, and image perms are automatically given when a member invites five members to the server. This helps with growth and prevents unfunny shitpost pollution."),
            ("🛡️ **How do I become a mod?**", "We **do not accept mod applications**. Members will be given mod if Mango or anyone else with role perms likes them. If you aren't annoying and are semi-active, there's a very decent chance you will get mod."),
            ("📞 **How do I appeal?**", "There is a **ticket system** where people can send tickets with what punishment they received and a short explanation as to why it was not justified. Mods that repeatedly issue unfair infractions will be reprimanded and could be removed from the mod team.")
        ]

        for question, answer in faq_items:
            faq_embed.add_field(
                name=question,
                value=f"> {answer}",
                inline=False
            )

        faq_embed.set_footer(
            text="Still have questions? Open a ticket! • Mangodia FAQ",
            icon_url="https://cdn.discordapp.com/emojis/853658439068229642.png"
        )

        # Send embeds in sequence with small delays for better visual impact
        await interaction.followup.send("🚀 **Setting up server information...**", ephemeral=True)

        # Send the rules embed
        rules_message = await interaction.channel.send(embed=rules_embed)

        # Send the Subway Surfers GIF embed
        gif_message = await interaction.channel.send(embed=gif_embed)

        # Send the FAQ embed
        faq_message = await interaction.channel.send(embed=faq_embed)

        # Add reactions to the rules message for engagement
        try:
            await rules_message.add_reaction("📜")
            await gif_message.add_reaction("🏃‍♂️")
            await faq_message.add_reaction("❓")
        except discord.Forbidden:
            logger.warning("Could not add reactions - missing permissions")

        # Send enhanced confirmation message
        success_embed = discord.Embed(
            title="✅ **Setup Complete!**",
            description="The rules, attention booster, and FAQ have been successfully posted!",
            color=0x96CEB4  # Success green
        )
        await interaction.followup.send(embed=success_embed, ephemeral=True)

    except discord.Forbidden:
        error_embed = discord.Embed(
            title="❌ **Permission Error**",
            description="I don't have permission to send messages in this channel.",
            color=0xFF4757  # Error red
        )
        await interaction.followup.send(embed=error_embed, ephemeral=True)

    except discord.HTTPException as e:
        logger.error(f"HTTP Exception: {e}")
        error_embed = discord.Embed(
            title="❌ **Network Error**",
            description="There was a problem sending the embeds. Please try again.",
            color=0xFF4757
        )
        await interaction.followup.send(embed=error_embed, ephemeral=True)

    except Exception as e:
        logger.error(f"Unexpected error in setup command: {e}")
        error_embed = discord.Embed(
            title="❌ **Unexpected Error**",
            description=f"An unexpected error occurred: {str(e)[:100]}...",
            color=0xFF4757
        )
        await interaction.followup.send(embed=error_embed, ephemeral=True)

# --- Run Bot ---
if __name__ == "__main__":
    if BOT_TOKEN:
        try:
            client.run(BOT_TOKEN)
        except discord.LoginFailure:
            logger.error("❌ Invalid bot token. Please check your DISCORD_TOKEN environment variable.")
        except Exception as e:
            logger.error(f"❌ Failed to start bot: {e}")
    else:
        logger.error("❌ DISCORD_TOKEN not found in environment variables.")
        print("Please set the DISCORD_TOKEN environment variable with your bot's token.")
