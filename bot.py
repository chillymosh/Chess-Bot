import os
import io
import random
import json
from json import JSONEncoder
from datetime import datetime
from dotenv import load_dotenv
from chess import WHITE, BLACK, Board, Move, parse_square, SQUARE_NAMES
from PIL import Image
import discord
from discord.ext import commands
from discord_slash import cog_ext
from discord_slash import SlashCommand
from discord_slash.utils.manage_commands import create_option

from generator import Generator


class Settings:
    """
    Contains all the high-level initialization and values that are needed elsewhere throughout the bot.
    """

    guild_ids = []
    bot_token = None
    storage_type = None
    database_url = None

    bot = commands.Bot(command_prefix="!",
                       case_insensitive=True,
                       intents=discord.Intents.all())
    SlashCommand(bot, sync_commands=True)

    @classmethod
    def load_env_settings(cls):
        load_dotenv()

        # TODO, there is undoubtedly a better way to handle slash command registration that setting server IDs in the
        # config and passing that list to the command registrations
        if os.getenv('GUILD_IDS'):
            if ',' in os.getenv('GUILD_IDS'):
                cls.guild_ids = [int(guild_id) for guild_id in os.getenv('GUILD_IDS').split(',')]
            else:
                cls.guild_ids = [int(os.getenv('GUILD_IDS'))]

        cls.bot_token = os.getenv("TOKEN")
        cls.storage_type = os.getenv("STORAGE_TYPE")
        cls.database_url = os.getenv("DATABASE_URL")

    @classmethod
    def init(cls):
        cls.load_env_settings()


class GameStorage:
    """
    Wrapper for potentially different DB interfaces, although Postgres is all that's currently supported.
    """

    db = None

    @classmethod
    def init(cls):
        if Settings.storage_type and Settings.storage_type.lower() == 'postgres':
            from storage import postgres
            cls.db = postgres.PostgresStorage(Settings.database_url)


class Game:
    """
    Wrapper around the Chess library Board to keep track of the white/black players
    and match_id reference for the DB
    """

    def __init__(self, white_id: int, black_id: int, match_id: int):
        self.white_id = white_id
        self.black_id = black_id
        self.match_id = match_id
        self.board = Board()


class GameEncoder(JSONEncoder):
    """
    We will be storing the entire Game object as JSON in the DB.  In order to
    convert to JSON we need some custom serialization to occur for the Discord
    related objects.
    """

    def default(self, o):
        if isinstance(o, discord.member.Member) or isinstance(o, discord.user.User):
            # Member doesn't support __dict__ and there's no point in storing the whole Member object
            # because we can get the actual Member object later using just the ID.
            return {
                "id": o.id
            }
        else:
            return o.__dict__


class Chess(commands.Cog):
    """
    The Discord interface to the game logic.

    Limitations
    ===========
    Only one game can be active in a channel at a time.  This is mainly to prevent confusion, but the
    database has been structured with that limitation in mind.

    Using a Forum channel type will make it easier
    to support multiple games running concurrently, where each post is a separate game, as each post is its
    own channel.

    Basic Flow
    ==========
    The basic flow is such that:

    * somebody will initiate a game in a channel, either open for anybody to accept, or to a specific person.
        * if it's a specific invite, only that person can /accept it, or /decline it
        * if it's an open invite, anybody can /accept, and if the requestor so wishes they can /cancel their open
          invite if they no long wish to have it open
    * after a match is accepted, the game board will be showin, with indicators for who is white/black and who's
      turn it is
    * players will take turns using /move to move their pieces until there is a winner, a stalemate, or one of the
      players uses the /surrender command
    * after a match is finishes the stats for both users are updated and a new match may be started if desired.
    """

    def __init__(self, bot):
        self.bot = bot

    @staticmethod
    async def send_error(ctx, title: str = "Error", description: str = "General internal error") -> None:
        """
        Helper function to send a consistently formatted Error embed message
        """
        title, description = f"**{title}:**", f"__{description}__"
        embed = discord.Embed(color=0xff0000)
        embed.add_field(name=title, value=description, inline=True)
        await ctx.send(embed=embed)

    def _get_member_by_id(self, user_id):
        """
        We only keep track of user ids in the JSON game data, so when we need to display their name, we need to
        look up the actual Discord User object
        :param user_id:
        :return: a Discord User object
        """
        return self.bot.get_user(user_id)

    async def convert_game_state_to_game(self, game_state):
        """
        Build a new Game instance from a JSON string.  Game instances are not kept around in memory, and
        every move persists the current game state in the DB to protect against bot restarts from causing
        matches to be disregarded.
        :param game_state: a JSON string defining a Game object
        :return: a fully populated Game instance
        """
        new_game = Game(white_id=0, black_id=0, match_id=0)
        game_dict = json.loads(game_state)
        for key in game_dict.keys():
            if key == 'white':
                # get actual discord member object so that we have the properties to @mention them in messages
                setattr(new_game, key, self._get_member_by_id(game_dict[key]['id']))
            elif key == 'black':
                # get actual discord member object so that we have the properties to @mention them in messages
                setattr(new_game, key, self._get_member_by_id(game_dict[key]['id']))
            elif key == 'board':
                # the board must be instantiated as an actual Board object
                setattr(new_game, key, Board())
                for board_key in game_dict[key]:
                    if board_key == 'move_stack':
                        # the move stack must contain actual Move objects for when we show the last move on the board
                        for move in game_dict[key][board_key]:
                            new_game.board.move_stack.append(Move(move['from_square'],
                                                                  move['to_square'],
                                                                  move['promotion'],
                                                                  move['drop']))
                    else:
                        setattr(new_game.board, board_key, game_dict[key][board_key])
            else:
                setattr(new_game, key, game_dict[key])
        return new_game

    @cog_ext.cog_slash(name="new",
                       description="Start a new match against a specific opponent, or the first to accept",
                       guild_ids=Settings.guild_ids,
                       options=[
                           create_option(
                               name="opponent",
                               description="opponent",
                               option_type=6,  # user
                               required=False
                           )
                       ])
    async def new(self, ctx, opponent=None):
        """
        Invite a specific user, or make an open invitation to any player to start a match.
        :param ctx:
        :param opponent:
        :return:
        """
        if ctx.author == opponent:
            return await self.send_error(ctx, description="You cannot challenge yourself")

        game_rec = GameStorage.db.get_current_game(ctx.channel_id)
        if game_rec:
            return await self.send_error(ctx, description="Another game is already active in this channel.")

        GameStorage.db.new_match(ctx.guild_id, ctx.channel_id, ctx.author_id, opponent.id if opponent else None)

        if opponent:
            message = f"Hey {opponent.mention}, {ctx.author.name} wants to play a chess match against you! "
        else:
            message = f"{ctx.author.name} is looking for any challenger for a chess match! "

        await ctx.send(f"{message} Use `/accept` or `/decline`")

    @cog_ext.cog_slash(name="decline",
                       description="decline an active invitation in this channel",
                       guild_ids=Settings.guild_ids)
    async def decline(self, ctx):
        invite = GameStorage.db.get_open_invites(ctx.channel_id)
        if invite and invite['opponent_id'] == ctx.author_id:
            user = self._get_member_by_id(invite['user_id'])
            GameStorage.db.decline_invite(invite['match_id'])
            await ctx.send(f"You have declined the invite from {user.mention}.")
            return

        return await self.send_error(ctx, "No invite was found to decline")

    @cog_ext.cog_slash(name="cancel",
                       description="Cancel a new match that you invited people to in this channel",
                       guild_ids=Settings.guild_ids)
    async def cancel(self, ctx):
        invite = GameStorage.db.get_open_invites(ctx.channel_id)
        if invite and invite['user_id'] == ctx.author_id:
            GameStorage.db.cancel_invite(invite['match_id'])
            await ctx.send(f"You have cancelled your invitation for a new match")
            return

        return await self.send_error(ctx, "You have no open invites exist, so there is nothing to cancel")

    @cog_ext.cog_slash(name="accept",
                       description="Accept an invite to play chess",
                       guild_ids=Settings.guild_ids)
    async def accept(self, ctx):
        invite = GameStorage.db.get_open_invites(ctx.channel_id)
        if invite is None:
            return await self.send_error(ctx, "There are no invites for anybody in this channel.")

        if invite['user_id'] == ctx.author_id:
            return await self.send_error(ctx, "You cannot accept your own invitation")

        if (invite['opponent_id'] is not None) and (invite['opponent_id'] != ctx.author_id):
            return await self.send_error(ctx, "Sorry, the invite in this channel is for a specific user")

        user = self._get_member_by_id(invite['user_id'])
        white_id, black_id = random.sample([user.id, ctx.author_id], 2)

        game = Game(white_id, black_id, invite['match_id'])

        game_state = json.dumps(game, cls=GameEncoder)
        GameStorage.db.accept_invite(invite['match_id'], ctx.author_id)
        GameStorage.db.save_game_state(invite['match_id'], game_state)

        await self.render_game_board(ctx, game)

    @cog_ext.cog_slash(name="move",
                       description="executes a move during a chess match",
                       guild_ids=Settings.guild_ids,
                       options=[
                           create_option(
                               name="start",
                               description="Starting position (ex. B1)",
                               option_type=3,
                               required=True
                           ),
                           create_option(
                               name="end",
                               description="End position (ex. C3)",
                               option_type=3,
                               required=True
                           )
                       ])
    async def move(self, ctx, start, end):
        """
        Handle a move from one of the players.
        :param ctx:
        :param start:
        :param end:
        :return:
        """
        game_rec = GameStorage.db.get_current_game(ctx.channel_id)
        if not game_rec:
            return await self.send_error(ctx, description="No game is currently in progress")

        try:
            start = parse_square(start.lower())
            end = parse_square(end.lower())
        except ValueError:
            return await self.send_error(ctx, description=f"Invalid move of {start} to {end}")

        current_game = await self.convert_game_state_to_game(game_rec['game_state'])

        if ctx.author_id not in [current_game.white_id, current_game.black_id]:
            await ctx.send("Only the players of the current match can make moves")
            return

        color = WHITE if self._get_member_by_id(current_game.white_id) == ctx.author else BLACK
        if color is not current_game.board.turn:
            return await self.send_error(ctx, "It is not your turn to make a move")

        move = Move(start, end)

        if move not in current_game.board.legal_moves:
            return await self.send_error(ctx, description="Illegal move for the selected piece")

        current_game.board.push(move)
        GameStorage.db.save_game_state(game_rec['match_id'], json.dumps(current_game, cls=GameEncoder))

        if current_game.board.is_stalemate():
            GameStorage.db.match_draw(game_rec['match_id'])
            GameStorage.db.add_user_stats_draw(ctx.guild_id, game_rec['user_id'])
            GameStorage.db.add_user_stats_draw(ctx.guild_id, game_rec['opponent_id'])

        if current_game.board.is_checkmate():
            winner_id = ctx.author_id
            loser_id = game_rec['opponent_id'] if game_rec['user_id'] == ctx.author_id else game_rec['user_id']

            GameStorage.db.match_won(game_rec['match_id'], winner_id, loser_id)
            GameStorage.db.add_user_stats_win(ctx.guild_id, winner_id)
            GameStorage.db.add_user_stats_loss(ctx.guild_id, loser_id)

        await self.render_game_board(ctx, current_game)

    @cog_ext.cog_slash(name="show",
                       description="Shows the current match chessboard",
                       guild_ids=Settings.guild_ids)
    async def show(self, ctx):
        """
        Re-shows the current board in cases where the message that contained the board has been deleted.
        """
        game_rec = GameStorage.db.get_current_game(ctx.channel_id)
        if not game_rec:
            return await self.send_error(ctx, description="No game is currently in progress")

        current_game = await self.convert_game_state_to_game(game_rec['game_state'])

        await self.render_game_board(ctx, current_game)

    @cog_ext.cog_slash(name="surrender",
                       description="Surrender the current match",
                       guild_ids=Settings.guild_ids)
    async def surrender(self, ctx):
        """
        Surrenders the current game, marking is as surrendered and recording a win/loss for the appropriate players.
        :param ctx:
        :return:
        """
        current_game = GameStorage.db.get_current_game(ctx.channel_id)
        if not current_game:
            await self.send_error(ctx, "No active games were found.  Use `/new` to start a new match.")
            return

        if ctx.author_id not in [current_game['user_id'], current_game['opponent_id']]:
            await self.send_error(ctx, "You are not a participant in the current game, so you can't surrender")
            return

        loser_id = ctx.author_id
        if current_game['user_id'] == ctx.author_id:
            winner_id = current_game['opponent_id']
        else:
            winner_id = current_game['user_id']

        GameStorage.db.surrender_game(current_game['match_id'], winner_id, loser_id)
        GameStorage.db.add_user_stats_win(ctx.guild_id, winner_id)
        GameStorage.db.add_user_stats_loss(ctx.guild_id, loser_id)
        await ctx.send(f"{ctx.author.mention} has surrendered!")

    @cog_ext.cog_slash(name="leaderboard",
                       description="Top 10 ChessBot Players",
                       guild_ids=Settings.guild_ids)
    async def leaderboard(self, ctx):
        leaders = GameStorage.db.get_leaderboard(ctx.guild_id)

        embed = discord.Embed(title="ChessBot Leaderboard")
        for idx, leader in enumerate(leaders):
            user = self._get_member_by_id(leader['user_id'])
            if user:
                embed.add_field(name=f"#{idx+1} - {user.name}",
                                value=f"> Ratio:  {(leader['win_ratio']*100):.2f}%\n"
                                      f"> Wins:   {leader['wins']}\n"
                                      f"> Losses: {leader['losses']}",
                                inline=False)

        return await ctx.send(embed=embed)

    @cog_ext.cog_slash(name="stats",
                       description="Shows the statistics for yourself or another user",
                       guild_ids=Settings.guild_ids,
                       options=[
                           create_option(
                               name="user",
                               description="Other user",
                               option_type=6,  # user
                               required=False
                           )
                       ])
    async def statistics(self, ctx, user=None):
        if user is None:
            user = ctx.author

        stats = GameStorage.db.get_user_stats(ctx.guild_id, user.id)
        if stats is None:
            stats = {
                "wins": 0,
                "losses": 0,
                "win_ratio": 0
            }

        embed = discord.Embed(color=0x0000ff, title=f"Chess Stats for {str(user)}")
        embed.add_field(name="Ratio ", value=f"{stats['win_ratio']*100:.2f}%", inline=False)
        embed.add_field(name="Wins  ", value=f"{stats['wins']}", inline=False)
        embed.add_field(name="Losses", value=f"{stats['losses']}", inline=False)
        await ctx.send(embed=embed)

    async def render_game_board(self, ctx, current_game):
        """
        Constructs the Embed object for the game board.  Indicates the players, their colors, who's turn it is
        and the most recent move.
        :param ctx:
        :param current_game:
        :return:
        """
        white_user = self._get_member_by_id(current_game.white_id)
        black_user = self._get_member_by_id(current_game.black_id)

        embed = discord.Embed()
        embed.add_field(name='',
                        value=f"**White**: {white_user.name} {('', '*(your turn)*')[current_game.board.turn]}",
                        inline=False)
        embed.add_field(name='',
                        value=f"**Black**: {black_user.name} {('*(your turn)*', '')[current_game.board.turn]}",
                        inline=False)

        if len(current_game.board.move_stack) > 0:
            last_move = current_game.board.move_stack[-1]
            if last_move:
                embed.add_field(name='',
                                value=f"**Last move**: *{SQUARE_NAMES[last_move.from_square]} "
                                      f"to {SQUARE_NAMES[last_move.to_square]}*",
                                inline=False)

        if current_game.board.is_stalemate():
            embed.add_field(name='',
                            value="**Stalemate! The game is a draw!**", inline=False)

        if current_game.board.is_check() and not current_game.board.is_checkmate():
            embed.add_field(name='',
                            value="**Check!**",
                            inline=False)

        if current_game.board.is_checkmate():
            embed.add_field(name='',
                            value=f"**Checkmate! "
                                  f"{(white_user.mention, black_user.mention)[current_game.board.turn]} "
                                  f"Has Won!**")

        board_image = Chess.get_binary_board(current_game.board)

        embed.set_image(url="attachment://board.jpg")
        await ctx.send(embed=embed, file=board_image)

    @staticmethod
    def get_binary_board(board) -> discord.File:
        """
        Generate the image of the board's current state, with all the pieces
        :param board:
        :return:
        """
        size = (500, 500)

        with io.BytesIO() as binary:
            board = Generator.generate(board).resize(size, Image.Resampling.BICUBIC)
            board.save(binary, "JPEG", quality=95, subsampling=0)
            binary.seek(0)
            return discord.File(fp=binary, filename="board.jpg")


@Settings.bot.event
async def on_ready() -> None:
    """
    Occurs when the Bot connects to Discord.  Outputs startup messages to the console.
    :return:
    """
    print("The BOT is currently online, connect to a Discord Server which contains it to start playing!")
    print("The name of the BOT is:", Settings.bot.user.name)
    print("The ID of the BOT is:", Settings.bot.user.id)
    print("Running for the following servers: ")
    for guild in Settings.guild_ids:
        print(" -", Settings.bot.get_guild(guild))

    print(datetime.now().strftime("%d-%m-%Y %H:%M"))


if __name__ == '__main__':
    Settings.init()
    GameStorage.init()
    Settings.bot.add_cog(Chess(Settings.bot))
    Settings.bot.run(Settings.bot_token)
