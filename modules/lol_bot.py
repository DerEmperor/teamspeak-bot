"""LoL bot Module for the Teamspeak3 Bot."""
from __future__ import annotations

import asyncio
import json
import time
from os import environ
from threading import Thread
import traceback
import threading
from typing import Dict
from datetime import datetime

from Moduleloader import *
import Bot
from modules.lol_client import LolUser, LolGame, LolRank
from ts3.TS3Connection import TS3Connection

LOL_CHANNEL_IDS = [104, 105]
LOL_DATA_FILE = 'lol_names.json'

lol_bot: LolBot | None = None
lolStopper = threading.Event()
bot: Bot.Ts3Bot | None = None
autoStart = True

LOL_RANK_NAMES_TO_SERVER_GROUP_NAMES = {
    LolRank.IRON: 'Eisen',
    LolRank.BRONZE: 'Bronze',
    LolRank.SILVER: 'Silber',
    LolRank.GOLD: 'Gold',
    LolRank.PLATINUM: 'Platin',
    LolRank.EMERALD: 'Smaragd',
    LolRank.DIAMOND: 'Diamant',
    LolRank.MASTER: 'Meister',
}


class User:
    def __init__(self, name: str, ts_uids: List[str], ts_dbids: List[str], lol_users: List[LolUser]):
        self.name = name
        self.ts_uids = ts_uids
        self.ts_dbids = ts_dbids
        self.lol_users = lol_users

    def __str__(self):
        return f'<User {self.name}>'

    def __repr__(self):
        return f'<User: {self.name}, lol names: {[str(u) for u in self.lol_users]}, ts_uids: {self.ts_uids}>'

    @classmethod
    async def from_dict(cls, data: Dict[str, str | List[str]], ts3_con: TS3Connection) -> User:
        assert data
        assert data['name']
        assert data['ts_user_ids']
        assert data['lol_names']

        return cls(
            data['name'],
            data['ts_user_ids'],
            [ts3_con.clientgetdbidfromuid(cluid=id_)['cldbid'] for id_ in data['ts_user_ids']],
            [await LolUser.from_name(name, data['name']) for name in data['lol_names']]
        )

    @property
    def main_lol_user(self):
        return self.lol_users[0]

    def to_dict(self) -> Dict[str, str | List[str]]:
        return {
            "name": self.name,
            "ts_user_ids": self.ts_uids,
            "lol_names": [u.game_name for u in self.lol_users]
        }


@command('startlol', 'lolstart')
@group('Kaiser', )
def start_lol(sender=None, msg=None):
    """
    Start the LoL bot by clearing the lolStopper signal and starting the mover.
    """
    global lol_bot
    if lol_bot is None:
        lol_bot = LolBot(lolStopper, bot.ts3conn)
        lolStopper.clear()
        lol_bot.start()
        if sender is not None:
            Bot.send_msg_to_client(bot.ts3conn, sender, "LoL bot started.")
    else:
        if sender is not None:
            Bot.send_msg_to_client(bot.ts3conn, sender, "LoL bot already running.")


@command('stoplol', 'lolstop')
@group('Kaiser', )
def stop_lol(sender=None, msg=None):
    """
    Stop the LoL bot by setting the lolStopper signal and undefining the mover.
    """
    global lol_bot
    lolStopper.set()
    lol_bot = None
    Bot.send_msg_to_client(bot.ts3conn, sender, "LoL bot stopped.")


@command('lol_update_ranks', 'lolupdateranks')
@group('Kaiser', 'Truchsess')
def lol_update_ranks(sender=None, msg=None):
    """
    Stop the LoL bot by setting the lolStopper signal and undefining the mover.
    """
    global lol_bot
    asyncio.run(lol_bot.update_ranks())
    Bot.send_msg_to_client(bot.ts3conn, sender, "LoL ranks updated.")


@setup
def setup(ts3bot, **kwargs):
    assert 'riot_api_key' in kwargs
    environ['RIOT_API_KEY'] = kwargs['riot_api_key']
    global bot
    bot = ts3bot
    if autoStart:
        start_lol()


@exit
def lol_exit():
    global lol_bot
    lolStopper.set()
    lol_bot.join()
    lol_bot = None


class LolBot(Thread):
    """
    LoL bot class. Check if people play LoL.
    """
    logger = logging.getLogger("LoL")
    logger.propagate = 0
    logger.setLevel(logging.WARNING)
    file_handler = logging.FileHandler("lol.log", mode='a+')
    formatter = logging.Formatter('LoL Logger %(asctime)s %(message)s')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.info("Configured LoL logger")
    logger.propagate = 0

    def __init__(self, _event: threading.Event, ts3conn: TS3Connection):
        """
        Create a new LoLBot object.
        :param _event: Event to signalize the LolBot to stop moving.
        :type _event: threading.Event
        :param ts3conn: Connection to use
        :type: TS3Connection
        """
        Thread.__init__(self)
        self.stopped = _event
        self.ts3conn = ts3conn
        self.users: List[User] | None = None
        self.current_games: List[LolGame] = []
        self.lol_rank_to_server_group_id: Dict[LolRank, int] = self.init_lol_rank_to_server_group_id()
        self.rank_updated = False
        self.active_games = []

    def run(self):
        """
        Thread run method. Starts the bot.
        """
        self.logger.info("LoL bot Thread started")
        try:
            asyncio.run(self.main())
        except Exception as e:
            self.logger.exception("Exception occurred in run: %s", e)
            self.logger.exception("Uncaught exception:" + str(sys.exc_info()[0]))
            self.logger.exception(str(sys.exc_info()[1]))
            self.logger.exception(traceback.format_exc())

    async def init_users(self):
        with open(LOL_DATA_FILE, 'r', encoding='utf-8') as file:
            data = json.load(file)
        self.users = []
        for user in data:
            user = await User.from_dict(user, self.ts3conn)
            self.users.append(user)

    def save_users(self):
        data = [u.to_dict() for u in self.users]
        with open(LOL_DATA_FILE, 'w', encoding='utf-8') as file:
            json.dump(data, file, indent=4)

    def init_lol_rank_to_server_group_id(self) -> Dict[LolRank, int]:
        res = {}
        server_groups = self.ts3conn.servergrouplist()
        for lol, ts in LOL_RANK_NAMES_TO_SERVER_GROUP_NAMES.items():
            for server_group in server_groups:
                if server_group.get('name', '') == ts:
                    res[lol] = int(server_group.get('sgid', '-1'))
        return res

    async def update_ranks(self) -> None:
        lol_ranks = await asyncio.gather(*[user.main_lol_user.get_rank() for user in self.users])
        for user, lol_rank in zip(self.users, lol_ranks):
            right_rank_ts = self.lol_rank_to_server_group_id[lol_rank] if lol_rank is not None else None
            for cldbid in user.ts_dbids:
                # compare existing group
                res = self.ts3conn.servergroupsbyclientid(cldbid=cldbid)
                if isinstance(res, dict):
                    res = [res]
                cur_groups = [int(g.get('sgid', '-1')) for g in res]
                cur_ranks_ts = set(self.lol_rank_to_server_group_id.values()) & set(cur_groups)

                if len(cur_ranks_ts) > 2:
                    for cur_rank_ts in cur_ranks_ts:
                        # delete all groups
                        self.ts3conn.servergroupdelclient(sgid=cur_rank_ts, cldbid=cldbid)
                    cur_ranks_ts = set()

                cur_rank_ts = cur_ranks_ts.pop() if len(cur_ranks_ts) else None

                if cur_rank_ts != right_rank_ts:
                    # delete current
                    if cur_rank_ts is not None:
                        self.ts3conn.servergroupdelclient(sgid=cur_rank_ts, cldbid=cldbid)
                    # add right one
                    if right_rank_ts is not None:
                        self.ts3conn.servergroupaddclient(sgid=right_rank_ts, cldbid=cldbid)

    async def update_ranks_scheduled(self) -> None:
        """update ranks at 5 o'clock"""
        hour = datetime.now().hour
        if hour == 0:
            self.rank_updated = False
        elif not self.rank_updated and hour == 5:
            self.logger.warning('update ranks')
            LolGame.clear_cache()
            await self.update_ranks()
            self.rank_updated = True

    async def get_games(self) -> List[LolGame]:
        cors = []
        for user in self.users:
            for lol_user in user.lol_users:
                cors.append(lol_user.get_current_game())
        games = await asyncio.gather(*cors)
        games = set(games) - {None}  # eliminate doubles
        return list(games)

    async def update_games_channels(self, games: List[LolGame]):
        if len(games) > 2:
            LolBot.logger.warning('too many games: %i', len(games))
        for game, cid in zip(games, LOL_CHANNEL_IDS):
            game: LolGame = game
            new_channel_name = f'[lspacer]{game.mode}: {game.time // 60} min; '  # + names

            names = ','.join([p.irl_name for p in game.ts_participants])
            remaining_chars = 40 - len(new_channel_name)
            if len(names) > remaining_chars:
                max_len = 10
                while len(names) > remaining_chars:
                    names = ','.join([p.irl_name[:max_len] for p in game.ts_participants])
                    max_len -= 1
            new_channel_name = new_channel_name + names

            team_sep = '------------ vs ------------\n'
            participants_formatted = ''
            for team in game.lol_participants.values():
                for participant in team:
                    participants_formatted += participant.get_description() + '\n'
                participants_formatted += team_sep

            participants_formatted = participants_formatted[:-len(team_sep)]

            new_channel_description = (
                f"ID:{game.game_id} \n"
                f"mode: {game.mode} \n"
                f"time: {game.time // 60}:{game.time % 60} min\n"
                f"banned champions: {', '.join(game.banned_champions)} \n"
                f"\n"
                f"{participants_formatted}"
            )
            self.ts3conn.set_channel_name_and_description(cid, new_channel_name, new_channel_description)

        # clear remaining channels
        for cid in LOL_CHANNEL_IDS[len(games):]:
            self.ts3conn.set_channel_name_and_description(cid, f'[lspacer{cid}]', '')

    async def main(self):
        """
        Loop until the stop signal is sent.
        """
        await self.init_users()
        # run loop at max every 30s
        run_time = 30
        while not self.stopped.wait(max(0, 30 - run_time)):
            start = time.time()
            self.logger.debug("LoLBot running!")
            await self.update_ranks_scheduled()
            games = await self.get_games()
            await self.update_games_channels(games)
            run_time = time.time() - start
