import psycopg


class DBGameStates:

    INVITE = "invite"
    IN_PROGRESS = "in-progress"
    DECLINED = "declined"
    CANCELLED = "cancelled"
    DONE = "done"
    STALEMATE = "stalemate"
    SURRENDERED = "surrendered"
    WON = "won"


class PostgresStorage:

    def __init__(self, connection_string):
        self.connection_string = connection_string
        self._connection: psycopg.Connection = self._connect()
        self._check_tables()

    def _connect(self):
        connection = psycopg.connect(self.connection_string)
        connection.autocommit = True
        return connection

    def _create_matches_table(self):
        cursor = self._connection.cursor()
        cursor.execute("create table matches ( "
                       " match_id serial primary key, "
                       " guild_id bigint, "
                       " channel_id bigint, "
                       " game_state text, "
                       " user_id bigint, "
                       " opponent_id bigint, "
                       " winner_id bigint, "
                       " loser_id bigint, "
                       " status varchar(20),"
                       " created_at timestamptz default now() "
                       ");")

        cursor.execute("create index idx_channel_status on matches (channel_id, status)")

    def _create_stats_table(self):
        cursor = self._connection.cursor()
        cursor.execute("create table user_stats ( "
                       " user_stat_id serial primary key, "
                       " guild_id bigint, "
                       " user_id bigint, "
                       " wins int default 0, "
                       " losses int default 0, "
                       " draws int default 0, "
                       " win_ratio numeric(5, 3) default 0, "
                       " unique(guild_id, user_id)"
                       ");")

        cursor.execute("create unique index idx_user_guild on user_stats (user_id, guild_id)")

    def _check_tables(self):
        """
        Check for missing tables and create them if necessary
        :return:
        """
        cursor = self._connection.cursor()
        cursor.execute("select table_name "
                       "from information_schema.tables "
                       "where table_schema='public' "
                       "and table_type='BASE TABLE' ")
        table_names = []
        tables = cursor.fetchall()
        for table in tables:
            table_names.append(table[0])
        if 'matches' not in table_names:
            self._create_matches_table()
        if 'user_stats' not in table_names:
            self._create_stats_table()

    def new_match(self, guild_id, channel_id, user_id, opponent_id):
        cursor = self._connection.cursor()
        cursor.execute("insert into matches "
                       "  (guild_id, channel_id, user_id, opponent_id, status) "
                       " values "
                       "  (%s, %s, %s, %s, %s) ",
                       (guild_id, channel_id, user_id, opponent_id, DBGameStates.INVITE))

    def get_open_invites(self, channel_id):
        cursor = self._connection.cursor()
        cursor.execute("select match_id, user_id, opponent_id "
                       "from matches where channel_id=%s and status=%s",
                       (channel_id, DBGameStates.INVITE))
        row = cursor.fetchone()
        if row:
            return {
                "match_id": row[0],
                "user_id": row[1],
                "opponent_id": row[2]
            }

    def accept_invite(self, match_id, opponent_id):
        cursor = self._connection.cursor()
        cursor.execute("update matches set opponent_id=%s, status=%s where match_id=%s",
                       (opponent_id, DBGameStates.IN_PROGRESS, match_id))

    def decline_invite(self, match_id):
        cursor = self._connection.cursor()
        cursor.execute("update matches set status=%s where match_id=%s",
                       (DBGameStates.DECLINED, match_id))

    def cancel_invite(self, match_id):
        cursor = self._connection.cursor()
        cursor.execute("update matches set status=%s where match_id=%s",
                       (DBGameStates.CANCELLED, match_id))

    def get_current_game(self, channel_id):
        cursor = self._connection.cursor()
        cursor.execute("select match_id, game_state, user_id, opponent_id "
                       "from matches "
                       "where channel_id=%s and status=%s",
                       (channel_id, DBGameStates.IN_PROGRESS))
        row = cursor.fetchone()
        if row:
            result = {
                "match_id": row[0],
                "game_state": row[1],
                "user_id": row[2],
                "opponent_id": row[3]
            }
            return result

    def surrender_game(self, match_id, winner_id, loser_id):
        cursor = self._connection.cursor()
        cursor.execute("update matches set status=%s, winner_id=%s, loser_id=%s where match_id=%s",
                       (DBGameStates.SURRENDERED, winner_id, loser_id, match_id))

    def match_won(self, match_id, winner_id, loser_id):
        cursor = self._connection.cursor()
        cursor.execute("update matches set status=%s, winner_id=%s, loser_id=%s where match_id=%s",
                       (DBGameStates.WON, winner_id, loser_id, match_id))

    def match_draw(self, match_id):
        cursor = self._connection.cursor()
        cursor.execute("update matches set status=%s where match_id=%s",
                       (DBGameStates.STALEMATE, match_id))

    def save_game_state(self, match_id, game_state):
        cursor = self._connection.cursor()
        cursor.execute("update matches "
                       "set game_state=%s "
                       "where match_id=%s",
                       (game_state, match_id))

    def add_user_stats_win(self, guild_id, user_id):
        cursor = self._connection.cursor()
        cursor.execute("insert into user_stats "
                       " (guild_id, user_id, wins, win_ratio) "
                       "values "
                       " (%s, %s, 1, 1)"
                       "on conflict on constraint user_stats_guild_id_user_id_key "
                       "do update set "
                       "wins = user_stats.wins + 1, "
                       "win_ratio=(user_stats.wins + 1)::float / (user_stats.wins + user_stats.losses + 1 + (user_stats.draws::float / 2))",
                       (guild_id, user_id))

    def add_user_stats_loss(self, guild_id, user_id):
        cursor = self._connection.cursor()
        cursor.execute("insert into user_stats "
                       " (guild_id, user_id, losses, win_ratio) "
                       "values "
                       " (%s, %s, 1, 0)"
                       "on conflict on constraint user_stats_guild_id_user_id_key "
                       "do update set "
                       "losses = user_stats.losses + 1,"
                       "win_ratio=(user_stats.wins)::float / (user_stats.wins + user_stats.losses + 1 + (user_stats.draws::float / 2))",
                       (guild_id, user_id))

    def add_user_stats_draw(self, guild_id, user_id):
        cursor = self._connection.cursor()
        cursor.execute("insert into user_stats "
                       " (guild_id, user_id, draws, win_ratio) "
                       "values "
                       " (%s, %s, 1, 0)"
                       "on conflict on constraint user_stats_guild_id_user_id_key "
                       "do update set "
                       "draws = user_stats.draws + 1,"
                       "win_ratio=(user_stats.wins)::float / (user_stats.wins + user_stats.losses + 1 + (user_stats.draws::float / 2))",
                       (guild_id, user_id))

    def get_user_stats(self, guild_id, user_id):
        cursor = self._connection.cursor()
        cursor.execute("select wins, losses, draws, win_ratio  "
                       "from user_stats where guild_id=%s and user_id=%s",
                       (guild_id, user_id))
        row = cursor.fetchone()
        if row:
            return {
                "wins": row[0],
                "losses": row[1],
                "draws": row[2],
                "win_ratio": row[3]
            }

    def get_leaderboard(self, guild_id):
        results = []
        cursor = self._connection.cursor()
        cursor.execute("select user_id, wins, losses, draws, win_ratio  "
                       "from user_stats where guild_id=%s "
                       "order by win_ratio desc "
                       "limit 10 ",
                       [guild_id])
        rows = cursor.fetchall()
        for row in rows:
            results.append({
                "user_id": row[0],
                "wins": row[1],
                "losses": row[2],
                "draws": row[3],
                "win_ratio": row[4]
            })
        return results
