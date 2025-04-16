from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from os import environ
from enum import Enum
from typing import List, Dict, Tuple, Any
import logging

import requests
from aiohttp import ClientResponseError
from pulsefire.clients import RiotAPIClient

# get latest version
response = requests.get("https://ddragon.leagueoflegends.com/api/versions.json")
assert response.status_code == 200
latest = response.json()[0]

# get champions
response = requests.get(f"https://ddragon.leagueoflegends.com/cdn/{latest}/data/en_US/champion.json")
assert response.status_code == 200
LOL_CHAMPIONS: Dict[int, str] = {}
for champion_info in response.json()['data'].values():
    LOL_CHAMPIONS[int(champion_info['key'])] = champion_info['name']

# get spells
response = requests.get(f"https://ddragon.leagueoflegends.com/cdn/{latest}/data/en_US/summoner.json")
assert response.status_code == 200
LOL_SPELLS: Dict[int, str] = {}
for spell_info in response.json()['data'].values():
    LOL_SPELLS[int(spell_info['key'])] = spell_info['name']

logger = logging.getLogger("LoL_client")
logger.propagate = 0
logger.setLevel(logging.WARNING)
file_handler = logging.FileHandler("lol_client.log", mode='a+')
formatter = logging.Formatter('LoL_CLIENT Logger %(asctime)s %(message)s')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)
logger.info("Configured LoL Client logger")
logger.propagate = 0

LOL_GAME_MODES: Dict[int, str] = {
    76: 'URF',
    400: 'Draft Pick',
    420: 'Ranked',
    430: 'Blind pick',
    440: 'Flex',
    450: 'ARAM',
    490: 'Normal',
    700: 'Clash',
    720: 'ARAM Clash',
    900: 'ARURF',
    1700: 'Arena',
    1710: 'Arena',
    1900: 'URF Pick',
}


@dataclass(frozen=True)
class GameParticipant:
    name: str
    team: int
    spell1: str
    spell2: str
    champion: str
    bot: bool

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> GameParticipant:
        return cls(
            name=data['riotId'].replace('#EUW', ''),
            team=data['teamId'],
            spell1=LOL_SPELLS.get(data['spell1Id'], data['spell1Id']),
            spell2=LOL_SPELLS.get(data['spell2Id'], data['spell2Id']),
            champion=LOL_CHAMPIONS.get(data['championId'], data['championId']),
            bot=data['bot'],
        )

    def get_description(self) -> str:
        res = f'{self.name}: {self.champion}, {self.spell1}, {self.spell2}'
        if self.bot:
            res += ' (bot)'
        return res

    @staticmethod
    def get_headlines() -> List[str]:
        return ['name', 'champion', 'spell1', 'spell2', 'is bot']

    def get_table_data(self) -> List[str]:
        return [self.name, self.champion, self.spell1, self.spell2, 'bot' if self.bot else '']


def translate_lol_mode(game_mode: str, game_type: str, queue_id: int) -> str:
    if queue_id in LOL_GAME_MODES:
        logger.warning("Game in Config: %s-%s-%i: %s", game_mode, game_type, queue_id, LOL_GAME_MODES[queue_id])
        return LOL_GAME_MODES[queue_id]
    else:
        logger.warning("Missing Game in Config: %s-%s-%i", game_mode, game_type, queue_id)
        return game_mode.lower()


class LolRank(Enum):
    IRON = 'IRON'
    BRONZE = 'BRONZE'
    SILVER = 'SILVER'
    GOLD = 'GOLD'
    PLATINUM = 'PLATINUM'
    EMERALD = 'EMERALD'
    DIAMOND = 'DIAMOND'
    MASTER = 'MASTER'


class LolGame:
    """class for handling LoL Game"""
    _cache: Dict[str: LolGame] = {}  # key: gameID

    def __init__(
            self,
            game_id: int,
            mode: str,
            time: int,
            ts_participants: List[LolUser],
            lol_participants: Dict[str, List[GameParticipant]],
            banned_champions: List[str],
    ):
        self.game_id = game_id
        self.mode = mode
        self.time = time
        self.ts_participants = ts_participants
        self.lol_participants = lol_participants
        self.banned_champions = banned_champions

        self._cache[game_id] = self

    @classmethod
    def get_cached(cls, game_id):
        return cls._cache.get(game_id)

    @classmethod
    def clear_cache(cls):
        cls._cache.clear()

    def __del__(self):
        if self.game_id in self._cache:
            del self._cache[self.game_id]

    def __str__(self):
        return f"<LoL Game '{self.game_id}'>"

    def __repr__(self):
        ts_participants = [p.game_name for p in self.ts_participants]
        return (f"<LoL Game ID:'{self.game_id}', mode: '{self.mode}', time: '{self.time}, "
                f"participants: '{ts_participants}'>")

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.game_id == other.game_id
        else:
            return False

    def __hash__(self):
        return hash(self.game_id)


class LolUser:
    """represent a user of lol"""
    _cache: Dict[str: LolUser] = {}  # key: puuid or game_name

    def __init__(
            self,
            puuid: str,
            summoner_id: str,
            game_name: str,
            account_id: str,
            irl_name: str,
            client: RiotAPIClient = None,
    ):
        if client is None:
            client = RiotAPIClient(default_headers={"X-Riot-Token": environ['RIOT_API_KEY']})
        self.client = client
        self.puuid = puuid
        self.summoner_id = summoner_id
        self.game_name = game_name
        self.account_id = account_id
        self.irl_name = irl_name

        self._cache[puuid] = self
        self._cache[game_name] = self

    @classmethod
    async def from_name(cls, game_name: str, irl_name: str, client: RiotAPIClient = None):
        if game_name in cls._cache:
            return cls._cache[game_name]
        if client is None:
            client = RiotAPIClient(default_headers={"X-Riot-Token": environ['RIOT_API_KEY']})
        async with client:
            res = await client.get_account_v1_by_riot_id(region='europe', game_name=game_name, tag_line='euw')
            puuid = res['puuid']
            res = await client.get_lol_summoner_v4_by_puuid(region='euw1', puuid=puuid)
            summoner_id = res['id']
            account_id = res['accountId']
        return cls(puuid, summoner_id, game_name, account_id, irl_name, client)

    @classmethod
    async def from_puuid(cls, puuid: str, irl_name: str, client: RiotAPIClient = None):
        if puuid in cls._cache:
            return cls._cache[puuid]
        if client is None:
            client = RiotAPIClient(default_headers={"X-Riot-Token": environ['RIOT_API_KEY']})
        async with client:
            res = await client.get_lol_summoner_v4_by_puuid(region='euw1', puuid=puuid)
            summoner_id = res['id']
            account_id = res['accountId']
            res = await client.get_account_v1_by_puuid(region='europe', puuid=puuid)
            game_name = res['gameName']
        return cls(puuid, summoner_id, game_name, account_id, irl_name, client)

    @classmethod
    def get_cached(cls, puuid_or_game_name: str) -> LolUser:
        return cls._cache.get(puuid_or_game_name)

    async def get_rank(self) -> LolRank | None:
        async with self.client:
            res = await self.client.get_lol_league_v4_entries_by_summoner(region='euw1', summoner_id=self.summoner_id)
        for entry in res:
            if entry['queueType'] == 'RANKED_SOLO_5x5':
                return LolRank(entry['tier'])
        return None

    async def get_current_game(self) -> LolGame | None:
        async with self.client:

            try:
                game = await self.client.get_lol_spectator_v5_active_game_by_summoner(region='euw1', puuid=self.puuid)
            except ClientResponseError as e:
                if e.status == 404:
                    # not in a game
                    return None
                raise e

        cached = LolGame.get_cached(game['gameId'])
        if cached is not None:
            cached.time = game['gameLength']
            return cached

        ts_participants: List[LolUser] = []
        for participant in game['participants']:
            user = self.get_cached(participant['puuid'])
            if user is not None:
                ts_participants.append(user)

        lol_participants = defaultdict(list)
        for participant in game['participants']:
            lol_participant = GameParticipant.from_dict(participant)
            lol_participants[lol_participant.team].append(lol_participant)

        banned_champs = []

        for champ in game['bannedChampions']:
            if champ['championId'] != -1:
                banned_champs.append(LOL_CHAMPIONS.get(champ['championId'], str(champ['championId'])))

        return LolGame(
            game_id=game['gameId'],
            mode=translate_lol_mode(game['gameMode'], game['gameType'], game['gameQueueConfigId']),
            time=game['gameLength'],
            ts_participants=ts_participants,
            lol_participants=lol_participants,
            banned_champions=banned_champs,
        )

    def __str__(self):
        return f"<LoL User '{self.game_name}'>"

    def __repr__(self):
        return (f"<LoL User name:'{self.game_name}', puuid: '{self.puuid}', summonerId: '{self.summoner_id}, "
                f"accountId: '{self.account_id}'>")

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.puuid == other.puuid
        else:
            return False

    def __hash__(self):
        return hash(self.puuid)
