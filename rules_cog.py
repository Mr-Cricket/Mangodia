import discord
import random
from discord.ext import commands
from discord import app_commands
import logging

logger = logging.getLogger(__name__)

# List of GIFs for the FAQ embed
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

class RulesCog(commands.Cog, name="Server Rules"):
    """Commands for displaying server rules and information."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="setup", description="Posts the server rules and FAQ embeds in the current channel.")
    @app_commands.default_permissions(manage_messages=True) # This line makes the command admin-only
    async def setup(self, interaction: discord.Interaction):
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            # --- Rules Embed ---
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
            
            # --- GIF Embed ---
            gif_embed = discord.Embed(title="🏃‍♂️ **ATTENTION SPAN BOOSTER**", description="*The average attention span in this server is approximately that of a goldfish so we expect to still be countlessly asked these questions. Here's some Subway Surfers gameplay to keep your attention while you read the FAQ below!*", color=0x4ECDC4)
            gif_embed.set_image(url=random.choice(subway_surfers_gifs))
            # The footer text was removed to improve rendering reliability of the GIF.
            
            # --- FAQ Embed ---
            faq_embed = discord.Embed(title="❓ **FREQUENTLY ASKED QUESTIONS**", description="We expect to still be asked these questions countlessly despite this FAQ existing.", color=0x45B7D1)
            faq_embed.add_field(name="🖼️ **How do I get pic perms?**", value="Members who want image perms need to invite five members to the server. Invitations are tracked, and image perms are automatically given when a member invites five members to the server. This helps with growth and helps not to pollute the server with unfunny shitposts.", inline=False)
            faq_embed.add_field(name="🛡️ **How do I become a mod?**", value="We do not accept mod applications. Members will be given mod if Mango or anyone else with role perms likes them. If you aren't annoying and are semi-active, there's a very decent chance you will get mod.", inline=False)
            faq_embed.add_field(name="📋 **How do I appeal?**", value="There is a ticket system where people can send tickets with what punishment they received and a short explanation as to why it was not justified. Mods that repeatedly issue unfair infractions will be reprimanded and could be removed from the mod team.", inline=False)
            faq_embed.set_footer(text="Still have questions? Don't hesitate to ask in the general chat! 💬")
            
            # Send each embed as a separate message and add the correct reaction
            rules_message = await interaction.channel.send(embed=rules_embed)
            await rules_message.add_reaction("📜")

            gif_message = await interaction.channel.send(embed=gif_embed)
            await gif_message.add_reaction("🏃‍♂️")

            faq_message = await interaction.channel.send(embed=faq_embed)
            await faq_message.add_reaction("✅")
            
            await interaction.followup.send("✅ **Setup Complete!**", ephemeral=True)
        except Exception as e:
            logger.error(f"Error in setup command: {e}")
            await interaction.followup.send("❌ An error occurred during setup. Please try again.", ephemeral=True)


# This function is called by the bot's load_extension()
async def setup(bot: commands.Bot):
    await bot.add_cog(RulesCog(bot))
