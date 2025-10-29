import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
import asyncio
from datetime import datetime
import secrets
import string
import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    raise ValueError("DISCORD_TOKEN not found in .env file")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


# Database setup
def init_db():
    conn = sqlite3.connect('suggestions.db')
    c = conn.cursor()

    # Guild settings table
    c.execute('''CREATE TABLE IF NOT EXISTS guild_settings
                 (
                     guild_id
                     INTEGER
                     PRIMARY
                     KEY,
                     suggestion_channel_id
                     INTEGER,
                     reviewer_role_id
                     INTEGER
                 )''')

    # Suggestions table
    c.execute('''CREATE TABLE IF NOT EXISTS suggestions
                 (
                     suggestion_id
                     TEXT
                     PRIMARY
                     KEY,
                     guild_id
                     INTEGER,
                     user_id
                     INTEGER,
                     message_id
                     INTEGER,
                     title
                     TEXT,
                     description
                     TEXT,
                     pros
                     TEXT,
                     cons
                     TEXT,
                     image_url
                     TEXT,
                     status
                     TEXT
                     DEFAULT
                     'pending',
                     created_at
                     TEXT,
                     decision_reason
                     TEXT
                 )''')

    # Votes table
    c.execute('''CREATE TABLE IF NOT EXISTS votes
    (
        suggestion_id
        TEXT,
        user_id
        INTEGER,
        vote_type
        TEXT,
        PRIMARY
        KEY
                 (
        suggestion_id,
        user_id
                 ))''')

    conn.commit()
    conn.close()


init_db()


# Generate random suggestion ID
def generate_suggestion_id():
    return ''.join(
        secrets.choice(string.ascii_lowercase + string.digits) for _ in
        range(8))


# Database helpers
def get_guild_settings(guild_id):
    conn = sqlite3.connect('suggestions.db')
    c = conn.cursor()
    c.execute(
        'SELECT suggestion_channel_id, reviewer_role_id FROM guild_settings WHERE guild_id = ?',
        (guild_id,))
    result = c.fetchone()
    conn.close()
    return result


def set_suggestion_channel(guild_id, channel_id):
    conn = sqlite3.connect('suggestions.db')
    c = conn.cursor()
    c.execute(
        'INSERT OR REPLACE INTO guild_settings (guild_id, suggestion_channel_id, reviewer_role_id) VALUES (?, ?, (SELECT reviewer_role_id FROM guild_settings WHERE guild_id = ?))',
        (guild_id, channel_id, guild_id))
    conn.commit()
    conn.close()


def set_reviewer_role(guild_id, role_id):
    conn = sqlite3.connect('suggestions.db')
    c = conn.cursor()
    c.execute(
        'INSERT OR REPLACE INTO guild_settings (guild_id, suggestion_channel_id, reviewer_role_id) VALUES (?, (SELECT suggestion_channel_id FROM guild_settings WHERE guild_id = ?), ?)',
        (guild_id, guild_id, role_id))
    conn.commit()
    conn.close()


def save_suggestion(suggestion_id, guild_id, user_id, message_id, title,
                    description, pros, cons, image_url):
    conn = sqlite3.connect('suggestions.db')
    c = conn.cursor()
    created_at = datetime.utcnow().isoformat()
    c.execute(
        'INSERT INTO suggestions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (suggestion_id, guild_id, user_id, message_id, title, description, pros,
         cons, image_url, 'pending', created_at, None))
    conn.commit()
    conn.close()


def get_suggestion(suggestion_id):
    conn = sqlite3.connect('suggestions.db')
    c = conn.cursor()
    c.execute('SELECT * FROM suggestions WHERE suggestion_id = ?',
              (suggestion_id,))
    result = c.fetchone()
    conn.close()
    return result


def update_suggestion_status(suggestion_id, status, reason=None):
    conn = sqlite3.connect('suggestions.db')
    c = conn.cursor()
    c.execute(
        'UPDATE suggestions SET status = ?, decision_reason = ? WHERE suggestion_id = ?',
        (status, reason, suggestion_id))
    conn.commit()
    conn.close()


def add_vote(suggestion_id, user_id, vote_type):
    conn = sqlite3.connect('suggestions.db')
    c = conn.cursor()
    try:
        c.execute('INSERT INTO votes VALUES (?, ?, ?)',
                  (suggestion_id, user_id, vote_type))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False


def remove_vote(suggestion_id, user_id):
    conn = sqlite3.connect('suggestions.db')
    c = conn.cursor()
    c.execute('DELETE FROM votes WHERE suggestion_id = ? AND user_id = ?',
              (suggestion_id, user_id))
    conn.commit()
    conn.close()


def get_votes(suggestion_id):
    conn = sqlite3.connect('suggestions.db')
    c = conn.cursor()
    c.execute(
        'SELECT vote_type, COUNT(*) FROM votes WHERE suggestion_id = ? GROUP BY vote_type',
        (suggestion_id,))
    results = c.fetchall()
    conn.close()

    votes = {'upvote': 0, 'downvote': 0}
    for vote_type, count in results:
        votes[vote_type] = count
    return votes


def get_user_vote(suggestion_id, user_id):
    conn = sqlite3.connect('suggestions.db')
    c = conn.cursor()
    c.execute(
        'SELECT vote_type FROM votes WHERE suggestion_id = ? AND user_id = ?',
        (suggestion_id, user_id))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None


# Modal for suggestion form
class SuggestionModal(discord.ui.Modal, title='Submit a Suggestion'):
    title_input = discord.ui.TextInput(
        label='Title',
        placeholder='Enter suggestion title...',
        max_length=256,
        required=True
    )

    description_input = discord.ui.TextInput(
        label='Description',
        placeholder='Describe your suggestion...',
        style=discord.TextStyle.paragraph,
        max_length=4000,
        required=True
    )

    pros_input = discord.ui.TextInput(
        label='Pros',
        placeholder='What are the benefits?',
        style=discord.TextStyle.paragraph,
        max_length=1024,
        required=True
    )

    cons_input = discord.ui.TextInput(
        label='Cons',
        placeholder='What are the drawbacks?',
        style=discord.TextStyle.paragraph,
        max_length=1024,
        required=True
    )

    def __init__(self, image_url=None):
        super().__init__()
        self.image_url = image_url

    async def on_submit(self, interaction: discord.Interaction):
        settings = get_guild_settings(interaction.guild_id)

        if not settings or not settings[0]:
            await interaction.response.send_message(
                '❌ Suggestion channel not set up. Contact an admin.',
                ephemeral=True)
            return

        channel = interaction.guild.get_channel(settings[0])
        if not channel:
            await interaction.response.send_message(
                '❌ Suggestion channel not found. Contact an admin.',
                ephemeral=True)
            return

        suggestion_id = generate_suggestion_id()

        # Create embed
        embed = discord.Embed(
            title=self.title_input.value,
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )

        embed.set_author(
            name=interaction.user.display_name,
            icon_url=interaction.user.display_avatar.url
        )

        embed.add_field(name='Description', value=self.description_input.value,
                        inline=False)

        if self.pros_input.value:
            embed.add_field(name='Pros', value=self.pros_input.value,
                            inline=False)

        if self.cons_input.value:
            embed.add_field(name='Cons', value=self.cons_input.value,
                            inline=False)

        embed.add_field(name='Results so far:',
                        value='Upvotes: 0 ✅\nDownvotes: 0 ❌', inline=False)

        embed.set_footer(
            text=f'User ID: {interaction.user.id} | Suggestion ID: {suggestion_id}')

        if self.image_url:
            embed.set_image(url=self.image_url)

        view = SuggestionView(suggestion_id)
        message = await channel.send(embed=embed, view=view)

        save_suggestion(
            suggestion_id,
            interaction.guild_id,
            interaction.user.id,
            message.id,
            self.title_input.value,
            self.description_input.value,
            self.pros_input.value or '',
            self.cons_input.value or '',
            self.image_url
        )

        await interaction.response.send_message(
            f'✅ Suggestion submitted! ID: `{suggestion_id}`', ephemeral=True)


# Persistent view for voting
class SuggestionView(discord.ui.View):
    def __init__(self, suggestion_id):
        super().__init__(timeout=None)
        self.suggestion_id = suggestion_id

    async def update_embed(self, interaction: discord.Interaction):
        suggestion = get_suggestion(self.suggestion_id)
        if not suggestion:
            return

        votes = get_votes(self.suggestion_id)

        embed = interaction.message.embeds[0]

        # Update votes field
        for i, field in enumerate(embed.fields):
            if field.name == 'Results so far:':
                embed.set_field_at(i, name='Results so far:',
                                   value=f'Upvotes: {votes["upvote"]} ✅\nDownvotes: {votes["downvote"]} ❌',
                                   inline=False)
                break

        # Update color based on status
        status = suggestion[9]
        if status == 'approved':
            embed.color = discord.Color.green()
        elif status == 'rejected':
            embed.color = discord.Color.red()

        await interaction.message.edit(embed=embed)

    @discord.ui.button(emoji='✅', style=discord.ButtonStyle.grey,
                       custom_id='upvote')
    async def upvote_button(self, interaction: discord.Interaction,
                            button: discord.ui.Button):
        suggestion = get_suggestion(self.suggestion_id)
        if not suggestion or suggestion[9] != 'pending':
            await interaction.response.send_message(
                '❌ Voting is closed for this suggestion.', ephemeral=True)
            return

        current_vote = get_user_vote(self.suggestion_id, interaction.user.id)

        if current_vote == 'upvote':
            remove_vote(self.suggestion_id, interaction.user.id)
            await interaction.response.send_message('🔄 Upvote removed.',
                                                    ephemeral=True)
        elif current_vote == 'downvote':
            remove_vote(self.suggestion_id, interaction.user.id)
            add_vote(self.suggestion_id, interaction.user.id, 'upvote')
            await interaction.response.send_message('✅ Changed to upvote.',
                                                    ephemeral=True)
        else:
            add_vote(self.suggestion_id, interaction.user.id, 'upvote')
            await interaction.response.send_message('✅ Upvoted!',
                                                    ephemeral=True)

        await self.update_embed(interaction)

    @discord.ui.button(emoji='❌', style=discord.ButtonStyle.grey,
                       custom_id='downvote')
    async def downvote_button(self, interaction: discord.Interaction,
                              button: discord.ui.Button):
        suggestion = get_suggestion(self.suggestion_id)
        if not suggestion or suggestion[9] != 'pending':
            await interaction.response.send_message(
                '❌ Voting is closed for this suggestion.', ephemeral=True)
            return

        current_vote = get_user_vote(self.suggestion_id, interaction.user.id)

        if current_vote == 'downvote':
            remove_vote(self.suggestion_id, interaction.user.id)
            await interaction.response.send_message('🔄 Downvote removed.',
                                                    ephemeral=True)
        elif current_vote == 'upvote':
            remove_vote(self.suggestion_id, interaction.user.id)
            add_vote(self.suggestion_id, interaction.user.id, 'downvote')
            await interaction.response.send_message('❌ Changed to downvote.',
                                                    ephemeral=True)
        else:
            add_vote(self.suggestion_id, interaction.user.id, 'downvote')
            await interaction.response.send_message('❌ Downvoted!',
                                                    ephemeral=True)

        await self.update_embed(interaction)


@bot.event
async def on_ready():
    # Re-register persistent views
    bot.add_view(SuggestionView(suggestion_id=''))

    try:
        synced = await bot.tree.sync()
        print(f'Logged in as {bot.user} (ID: {bot.user.id})')
        print(f'Synced {len(synced)} command(s)')
    except Exception as e:
        print(f'Error syncing commands: {e}')


# Commands
@bot.tree.command(name='suggest', description='Submit a suggestion')
@app_commands.describe(image='Optional image attachment')
async def suggest(interaction: discord.Interaction,
                  image: discord.Attachment = None):
    image_url = None
    if image:
        if not image.content_type.startswith('image/'):
            await interaction.response.send_message(
                '❌ Please attach a valid image file.', ephemeral=True)
            return
        image_url = image.url

    modal = SuggestionModal(image_url=image_url)
    await interaction.response.send_modal(modal)


@bot.tree.command(name='setchannel',
                  description='Set the suggestions channel (Admin only)')
@app_commands.describe(channel='The channel for suggestions')
@app_commands.default_permissions(administrator=True)
async def setchannel(interaction: discord.Interaction,
                     channel: discord.TextChannel):
    set_suggestion_channel(interaction.guild_id, channel.id)
    await interaction.response.send_message(
        f'✅ Suggestion channel set to {channel.mention}', ephemeral=True)


@bot.tree.command(name='setreviewerrole',
                  description='Set the role that can approve/reject suggestions (Admin only)')
@app_commands.describe(role='The reviewer role')
@app_commands.default_permissions(administrator=True)
async def setreviewerrole(interaction: discord.Interaction, role: discord.Role):
    set_reviewer_role(interaction.guild_id, role.id)
    await interaction.response.send_message(
        f'✅ Reviewer role set to {role.mention}', ephemeral=True)


@bot.tree.command(name='approve',
                  description='Approve a suggestion (Reviewer only)')
@app_commands.describe(suggestion_id='The ID of the suggestion',
                       reason='Optional reason')
async def approve(interaction: discord.Interaction, suggestion_id: str,
                  reason: str = None):
    settings = get_guild_settings(interaction.guild_id)

    if not settings or not settings[1]:
        await interaction.response.send_message('❌ Reviewer role not set up.',
                                                ephemeral=True)
        return

    reviewer_role = interaction.guild.get_role(settings[1])
    if not reviewer_role or reviewer_role not in interaction.user.roles:
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                '❌ You need the reviewer role to use this command.',
                ephemeral=True)
            return

    suggestion = get_suggestion(suggestion_id)
    if not suggestion:
        await interaction.response.send_message('❌ Suggestion not found.',
                                                ephemeral=True)
        return

    update_suggestion_status(suggestion_id, 'approved', reason)

    channel = interaction.guild.get_channel(settings[0])
    if channel:
        try:
            message = await channel.fetch_message(suggestion[3])
            embed = message.embeds[0]
            embed.color = discord.Color.green()

            if reason:
                embed.add_field(name='✅ Approved', value=f'Reason: {reason}',
                                inline=False)
            else:
                embed.add_field(name='✅ Approved',
                                value='This suggestion has been approved.',
                                inline=False)

            await message.edit(embed=embed)
        except:
            pass

    await interaction.response.send_message(
        f'✅ Suggestion `{suggestion_id}` approved!', ephemeral=True)


@bot.tree.command(name='reject',
                  description='Reject a suggestion (Reviewer only)')
@app_commands.describe(suggestion_id='The ID of the suggestion',
                       reason='Optional reason')
async def reject(interaction: discord.Interaction, suggestion_id: str,
                 reason: str = None):
    settings = get_guild_settings(interaction.guild_id)

    if not settings or not settings[1]:
        await interaction.response.send_message('❌ Reviewer role not set up.',
                                                ephemeral=True)
        return

    reviewer_role = interaction.guild.get_role(settings[1])
    if not reviewer_role or reviewer_role not in interaction.user.roles:
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                '❌ You need the reviewer role to use this command.',
                ephemeral=True)
            return

    suggestion = get_suggestion(suggestion_id)
    if not suggestion:
        await interaction.response.send_message('❌ Suggestion not found.',
                                                ephemeral=True)
        return

    update_suggestion_status(suggestion_id, 'rejected', reason)

    channel = interaction.guild.get_channel(settings[0])
    if channel:
        try:
            message = await channel.fetch_message(suggestion[3])
            embed = message.embeds[0]
            embed.color = discord.Color.red()

            if reason:
                embed.add_field(name='❌ Rejected', value=f'Reason: {reason}',
                                inline=False)
            else:
                embed.add_field(name='❌ Rejected',
                                value='This suggestion has been rejected.',
                                inline=False)

            await message.edit(embed=embed)
        except:
            pass

    await interaction.response.send_message(
        f'❌ Suggestion `{suggestion_id}` rejected!', ephemeral=True)


# Run bot
bot.run(TOKEN)
