import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
from datetime import datetime, timezone
import secrets
import string
import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
DATABASE = os.getenv("DB_PATH")

if not TOKEN:
    raise ValueError("DISCORD_TOKEN not found in .env file")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


# Database setup
def init_db():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    # Guild settings table
    c.execute('''CREATE TABLE IF NOT EXISTS guild_settings
                 (
                     guild_id INTEGER PRIMARY KEY,
                     suggestion_channel_id INTEGER,
                     reviewer_role_id INTEGER,
                     blocked_role_id INTEGER
                 )''')

    # Suggestions table
    c.execute('''CREATE TABLE IF NOT EXISTS suggestions
                 (
                     suggestion_id TEXT PRIMARY KEY,
                     guild_id INTEGER,
                     user_id INTEGER,
                     message_id INTEGER,
                     thread_id INTEGER,
                     title TEXT,
                     description TEXT,
                     pros TEXT,
                     cons TEXT,
                     image_url TEXT,
                     status TEXT DEFAULT 'pending',
                     created_at TEXT,
                     decision_reason TEXT,
                     decided_anonymously INTEGER DEFAULT 0
                 )''')

    # Votes table
    c.execute('''CREATE TABLE IF NOT EXISTS votes
                 (
                     suggestion_id TEXT,
                     user_id INTEGER,
                     vote_type TEXT,
                     PRIMARY KEY (suggestion_id, user_id)
                 )''')

    # Migrate existing tables
    try:
        # Check if blocked_role_id column exists in guild_settings
        c.execute("PRAGMA table_info(guild_settings)")
        columns = [column[1] for column in c.fetchall()]
        if 'blocked_role_id' not in columns:
            c.execute('ALTER TABLE guild_settings ADD COLUMN blocked_role_id INTEGER')
    except Exception:
        pass

    try:
        # Check if thread_id column exists in suggestions
        c.execute("PRAGMA table_info(suggestions)")
        columns = [column[1] for column in c.fetchall()]
        if 'thread_id' not in columns:
            c.execute('ALTER TABLE suggestions ADD COLUMN thread_id INTEGER')
        if 'decided_anonymously' not in columns:
            c.execute('ALTER TABLE suggestions ADD COLUMN decided_anonymously INTEGER DEFAULT 0')
    except Exception:
        pass

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
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute(
        'SELECT suggestion_channel_id, reviewer_role_id, blocked_role_id FROM guild_settings WHERE guild_id = ?',
        (guild_id,))
    result = c.fetchone()
    conn.close()
    return result


def set_suggestion_channel(guild_id, channel_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute(
        '''INSERT INTO guild_settings (guild_id, suggestion_channel_id, reviewer_role_id, blocked_role_id) 
           VALUES (?, ?, NULL, NULL)
           ON CONFLICT(guild_id) DO UPDATE SET suggestion_channel_id = ?''',
        (guild_id, channel_id, channel_id))
    conn.commit()
    conn.close()


def set_reviewer_role(guild_id, role_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute(
        '''INSERT INTO guild_settings (guild_id, suggestion_channel_id, reviewer_role_id, blocked_role_id) 
           VALUES (?, NULL, ?, NULL)
           ON CONFLICT(guild_id) DO UPDATE SET reviewer_role_id = ?''',
        (guild_id, role_id, role_id))
    conn.commit()
    conn.close()


def set_blocked_role(guild_id, role_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute(
        '''INSERT INTO guild_settings (guild_id, suggestion_channel_id, reviewer_role_id, blocked_role_id) 
           VALUES (?, NULL, NULL, ?)
           ON CONFLICT(guild_id) DO UPDATE SET blocked_role_id = ?''',
        (guild_id, role_id, role_id))
    conn.commit()
    conn.close()


def save_suggestion(suggestion_id, guild_id, user_id, message_id, thread_id,
                    title,
                    description, pros, cons, image_url):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    created_at = datetime.now(timezone.utc).isoformat()
    c.execute(
        'INSERT INTO suggestions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (suggestion_id, guild_id, user_id, message_id, thread_id, title,
         description, pros,
         cons, image_url, 'pending', created_at, None, 0))
    conn.commit()
    conn.close()


def get_suggestion(suggestion_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('SELECT * FROM suggestions WHERE suggestion_id = ?',
              (suggestion_id,))
    result = c.fetchone()
    conn.close()
    return result


def update_suggestion_status(suggestion_id, status, reason=None,
                             anonymous=False):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute(
        'UPDATE suggestions SET status = ?, decision_reason = ?, decided_anonymously = ? WHERE suggestion_id = ?',
        (status, reason, 1 if anonymous else 0, suggestion_id))
    conn.commit()
    conn.close()


def add_vote(suggestion_id, user_id, vote_type):
    conn = sqlite3.connect(DATABASE)
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
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('DELETE FROM votes WHERE suggestion_id = ? AND user_id = ?',
              (suggestion_id, user_id))
    conn.commit()
    conn.close()


def get_votes(suggestion_id):
    conn = sqlite3.connect(DATABASE)
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
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute(
        'SELECT vote_type FROM votes WHERE suggestion_id = ? AND user_id = ?',
        (suggestion_id, user_id))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None


def check_missing_permissions(channel, required_perms):
    """Check which required permissions are missing"""
    bot_perms = channel.permissions_for(channel.guild.me)
    missing = []

    for perm_name in required_perms:
        if not getattr(bot_perms, perm_name, False):
            missing.append(perm_name.replace('_', ' ').title())

    return missing


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

        # Check for required permissions
        required_perms = ['send_messages', 'embed_links',
                          'create_public_threads', 'send_messages_in_threads']
        missing_perms = check_missing_permissions(channel, required_perms)

        if missing_perms:
            await interaction.response.send_message(
                f'❌ Bot is missing required permissions in {channel.mention}:\n' +
                '\n'.join(f'• {perm}' for perm in missing_perms),
                ephemeral=True)
            return

        suggestion_id = generate_suggestion_id()

        # Create embed
        embed = discord.Embed(
            title=self.title_input.value,
            color=discord.Color.blue(),
            timestamp=datetime.now(timezone.utc)
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

        try:
            message = await channel.send(embed=embed, view=view)

            # Create thread
            thread = await message.create_thread(
                name=f"{self.title_input.value[:80]}" if len(
                    self.title_input.value) > 80 else f"{self.title_input.value}",
                auto_archive_duration=10080  # 7 days
            )

            save_suggestion(
                suggestion_id,
                interaction.guild_id,
                interaction.user.id,
                message.id,
                thread.id,
                self.title_input.value,
                self.description_input.value,
                self.pros_input.value or '',
                self.cons_input.value or '',
                self.image_url
            )

            await interaction.response.send_message(
                '✅ Suggestion submitted!', ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(
                '❌ Bot lacks permissions to send messages or create threads.',
                ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(
                f'❌ Error creating suggestion: {str(e)}',
                ephemeral=True)


# Persistent view for voting
class SuggestionView(discord.ui.View):
    def __init__(self, suggestion_id):
        super().__init__(timeout=None)
        self.suggestion_id = suggestion_id

        up_btn = discord.ui.Button(emoji='✅', style=discord.ButtonStyle.grey,
                                   custom_id=f'upvote:{suggestion_id}')
        down_btn = discord.ui.Button(emoji='❌', style=discord.ButtonStyle.grey,
                                     custom_id=f'downvote:{suggestion_id}')

        up_btn.callback = self._handle_upvote
        down_btn.callback = self._handle_downvote

        self.add_item(up_btn)
        self.add_item(down_btn)

    async def update_embed(self, interaction: discord.Interaction):
        suggestion = get_suggestion(self.suggestion_id)
        if not suggestion:
            return

        votes = get_votes(self.suggestion_id)

        embed = interaction.message.embeds[0]

        # Determine label based on status
        status = suggestion[10]  # status column
        label = 'Results:' if status in ['approved',
                                         'rejected'] else 'Results so far:'

        for i, field in enumerate(embed.fields):
            if field.name in ['Results so far:', 'Results:']:
                embed.set_field_at(
                    i,
                    name=label,
                    value=f'Upvotes: {votes["upvote"]} ✅\nDownvotes: {votes["downvote"]} ❌',
                    inline=False
                )
                break

        if status == 'approved':
            embed.color = discord.Color.green()
        elif status == 'rejected':
            embed.color = discord.Color.red()

        try:
            await interaction.message.edit(embed=embed)
        except discord.Forbidden:
            pass

    async def _handle_upvote(self, interaction: discord.Interaction):
        # Fetch fresh suggestion data from database
        suggestion = get_suggestion(self.suggestion_id)
        if not suggestion:
            await interaction.response.send_message('❌ Suggestion not found.',
                                                    ephemeral=True)
            return

        # Check if suggestion belongs to this guild
        if suggestion[1] != interaction.guild_id:
            await interaction.response.send_message(
                '❌ Suggestion not found.',
                ephemeral=True)
            return

        if suggestion[10] != 'pending':
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

    async def _handle_downvote(self, interaction: discord.Interaction):
        suggestion = get_suggestion(self.suggestion_id)
        if not suggestion:
            await interaction.response.send_message('❌ Suggestion not found.',
                                                    ephemeral=True)
            return

        # Check if suggestion belongs to this guild
        if suggestion[1] != interaction.guild_id:
            await interaction.response.send_message(
                '❌ Suggestion not found.',
                ephemeral=True)
            return

        if suggestion[10] != 'pending':
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
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT suggestion_id FROM suggestions WHERE status = 'pending'")
    rows = c.fetchall()
    conn.close()

    for (suggestion_id,) in rows:
        try:
            bot.add_view(SuggestionView(suggestion_id))
        except Exception:
            pass

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
    settings = get_guild_settings(interaction.guild_id)

    # Check if user has blocked role
    if settings and settings[2]:
        blocked_role = interaction.guild.get_role(settings[2])
        if blocked_role and blocked_role in interaction.user.roles:
            await interaction.response.send_message(
                '❌ You are not allowed to submit suggestions.',
                ephemeral=True)
            return

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


@bot.tree.command(name='setblockedrole',
                  description='Set a role that cannot submit suggestions (Admin only)')
@app_commands.describe(role='The role to block from suggesting')
@app_commands.default_permissions(administrator=True)
async def setblockedrole(interaction: discord.Interaction, role: discord.Role):
    set_blocked_role(interaction.guild_id, role.id)
    await interaction.response.send_message(
        f'✅ Users with {role.mention} can no longer submit suggestions.',
        ephemeral=True)


@bot.tree.command(name='approve',
                  description='Approve a suggestion (Reviewer only)')
@app_commands.describe(
    suggestion_id='The ID of the suggestion',
    reason='Optional reason',
    anonymous='Approve anonymously (hides your name)')
async def approve(interaction: discord.Interaction, suggestion_id: str,
                  reason: str = None, anonymous: bool = False):
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

    # Check if suggestion belongs to this guild
    if suggestion[1] != interaction.guild_id:
        await interaction.response.send_message(
            '❌ Suggestion not found.',
            ephemeral=True)
        return

    update_suggestion_status(suggestion_id, 'approved', reason, anonymous)

    channel = interaction.guild.get_channel(settings[0])
    if channel:
        try:
            message = await channel.fetch_message(suggestion[3])
            embed = message.embeds[0]
            embed.color = discord.Color.green()

            # Update Results label
            for i, field in enumerate(embed.fields):
                if field.name == 'Results so far:':
                    votes = get_votes(suggestion_id)
                    embed.set_field_at(
                        i,
                        name='Results:',
                        value=f'Upvotes: {votes["upvote"]} ✅\nDownvotes: {votes["downvote"]} ❌',
                        inline=False
                    )
                    break

            approval_text = f'Approved by: {"Anonymous Reviewer" if anonymous else interaction.user.mention}'
            if reason:
                approval_text += f'\nReason: {reason}'

            embed.add_field(name='✅ Approved', value=approval_text,
                            inline=False)

            await message.edit(embed=embed)

            # Lock thread
            if suggestion[4]:  # thread_id
                try:
                    thread = await channel.guild.fetch_channel(suggestion[4])
                    if thread and isinstance(thread, discord.Thread):
                        await thread.edit(locked=True, archived=True)
                except (discord.NotFound, discord.Forbidden):
                    pass
        except Exception:
            pass

    await interaction.response.send_message(
        f'✅ Suggestion `{suggestion_id}` approved!', ephemeral=True)


@bot.tree.command(name='reject',
                  description='Reject a suggestion (Reviewer only)')
@app_commands.describe(
    suggestion_id='The ID of the suggestion',
    reason='Optional reason',
    anonymous='Reject anonymously (hides your name)')
async def reject(interaction: discord.Interaction, suggestion_id: str,
                 reason: str = None, anonymous: bool = False):
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

    # Check if suggestion belongs to this guild
    if suggestion[1] != interaction.guild_id:
        await interaction.response.send_message(
            '❌ Suggestion not found.',
            ephemeral=True)
        return

    update_suggestion_status(suggestion_id, 'rejected', reason, anonymous)

    channel = interaction.guild.get_channel(settings[0])
    if channel:
        try:
            message = await channel.fetch_message(suggestion[3])
            embed = message.embeds[0]
            embed.color = discord.Color.red()

            # Update Results label
            for i, field in enumerate(embed.fields):
                if field.name == 'Results so far:':
                    votes = get_votes(suggestion_id)
                    embed.set_field_at(
                        i,
                        name='Results:',
                        value=f'Upvotes: {votes["upvote"]} ✅\nDownvotes: {votes["downvote"]} ❌',
                        inline=False
                    )
                    break

            rejection_text = f'Rejected by: {"Anonymous Reviewer" if anonymous else interaction.user.mention}'
            if reason:
                rejection_text += f'\nReason: {reason}'

            embed.add_field(name='❌ Rejected', value=rejection_text,
                            inline=False)

            await message.edit(embed=embed)

            # Lock thread
            if suggestion[4]:  # thread_id
                try:
                    thread = await channel.guild.fetch_channel(suggestion[4])
                    if thread and isinstance(thread, discord.Thread):
                        await thread.edit(locked=True, archived=True)
                except (discord.NotFound, discord.Forbidden):
                    pass
        except Exception:
            pass

    await interaction.response.send_message(
        f'❌ Suggestion `{suggestion_id}` rejected!', ephemeral=True)


# Run bot
bot.run(TOKEN)
