"""AfkMover Module for the Teamspeak3 Bot."""
from __future__ import annotations

import datetime
from threading import Thread
import traceback
from typing import Dict
import random

from Moduleloader import *
import ts3.Events as Events
import threading
import Bot
from ts3.utilities import TS3Exception

afkMover: AfkMover | None = None
afkStopper = threading.Event()
bot: Bot.Ts3Bot | None = None
autoStart = True
AFK_CHANNEL = "Bin weg"
AFK_CHANNELS = ["Masturbationszimmer", "Kramis Kühlkammer", "Anderer Gs / Zwietracht", "Anstubsbar"]
MUTE_TIME = datetime.timedelta(minutes=45)
MUTE_TIME_WORK = datetime.timedelta(hours=1, minutes=30)
channel_name = AFK_CHANNEL


@command('startafk', 'afkstart', 'afkmove', )
@group('Kaiser', )
def start_afkmover(sender=None, msg=None):
    """
    Start the AfkMover by clearing the afkStopper signal and starting the mover.
    """
    global afkMover
    if afkMover is None:
        afkMover = AfkMover(afkStopper, bot.ts3conn)
        afkStopper.clear()
        afkMover.start()
        if sender is not None:
            Bot.send_msg_to_client(bot.ts3conn, sender, "AFK mover started.")
    else:
        if sender is not None:
            Bot.send_msg_to_client(bot.ts3conn, sender, "AFK already running.")


@command('stopafk', 'afkstop')
@group('Kaiser', )
def stop_afkmover(sender=None, msg=None):
    """
    Stop the AfkMover by setting the afkStopper signal and undefining the mover.
    """
    global afkMover
    afkStopper.set()
    afkMover = None
    Bot.send_msg_to_client(bot.ts3conn, sender, "AFK mover stopped.")


@command('afkgetclientchannellist')
@group('Kaiser', 'Truchsess', 'Bürger')
def get_afk_list(sender=None, msg=None):
    """
    Get afkmover saved client channels. Mainly for debugging.
    """
    if afkMover is not None:
        Bot.send_msg_to_client(bot.ts3conn, sender, str(afkMover.client_channels))


@command('getmutedsincelist', 'muted')
@group('Kaiser', 'Truchsess', 'Bürger')
def get_muted_since_list(sender=None, msg=None):
    if afkMover is not None:
        message = "{"
        for clid, time in afkMover.muted_since.items():
            message += f"{afkMover.get_name(clid)}: {time.hour}:{time.minute}:{time.second}, "
        if len(message) <= 1:
            message += ", "
        message = message[:-2] + "}"
        Bot.send_msg_to_client(bot.ts3conn, sender, message)


@command('getmutetime', )
@group('Kaiser', 'Truchsess', 'Bürger', )
def get_mute_time(sender=None, msg=None):
    Bot.send_msg_to_client(bot.ts3conn, sender, f"mute time set to {afkMover.mute_time.seconds / 60} minutes.")


@command('setmutetime', )
@group('Kaiser', 'Truchsess', )
def set_mute_time(sender=None, msg=None):
    global MUTE_TIME, MUTE_TIME_WORK
    _command, time = msg.split(' ')
    new_mute_time = float(time)
    if new_mute_time > 0:
        afkMover.mute_time = datetime.timedelta(minutes=new_mute_time)
    if datetime.datetime.now().weekday() in (0, 1, 2, 3, 4) and 7 < datetime.datetime.now().hour < 17:
        MUTE_TIME_WORK = new_mute_time
    else:
        MUTE_TIME = new_mute_time
    Bot.send_msg_to_client(bot.ts3conn, sender, f"mute time set to {new_mute_time} minutes.")


@event(Events.ClientLeftEvent, )
def client_left(_event):
    """
    Clean up leaving clients.
    """
    # Forgets clients that were set to afk and then left
    if afkMover is not None:
        if str(_event.client_id) in afkMover.client_channels:
            del afkMover.client_channels[str(_event.client_id)]
        if str(_event.client_id) in afkMover.muted_since:
            del afkMover.muted_since[str(_event.client_id)]


@setup
def setup(ts3bot, channel=AFK_CHANNEL):
    global bot, channel_name
    bot = ts3bot
    channel_name = channel
    if autoStart:
        start_afkmover()


@exit
def afkmover_exit():
    global afkMover
    afkStopper.set()
    afkMover.join()
    afkMover = None


class AfkMover(Thread):
    """
    AfkMover class. Moves clients set to afk another channel.
    """
    logger = logging.getLogger("afk")
    logger.propagate = 0
    logger.setLevel(logging.WARNING)
    file_handler = logging.FileHandler("afk.log", mode='a+')
    formatter = logging.Formatter('AFK Logger %(asctime)s %(message)s')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.info("Configured afk logger")
    logger.propagate = 0

    def __init__(self, _event, ts3conn):
        """
        Create a new AfkMover object.
        :param _event: Event to signalize the AfkMover to stop moving.
        :type _event: threading.Event
        :param ts3conn: Connection to use
        :type: TS3Connection
        """
        Thread.__init__(self)
        self.stopped = _event
        self.ts3conn = ts3conn
        self.afk_channel = self.get_afk_channel(channel_name)
        self.afk_channels = [self.get_afk_channel(channel) for channel in (AFK_CHANNELS + [AFK_CHANNEL])]
        self.client_channels = {}
        self.muted_since: Dict[str, datetime.datetime] = dict()
        self.afk_list = None
        self.mute_time = MUTE_TIME
        if self.afk_channel is None:
            AfkMover.logger.error("Could not get afk channel")

    def run(self):
        """
        Thread run method. Starts the mover.
        """
        AfkMover.logger.info("AFKMove Thread started")
        try:
            self.auto_move_all()
        except:
            self.logger.exception("Exception occured in run:")

    def update_afk_list(self):
        """
        Update the list of clients.
        """
        try:
            afk_list = self.ts3conn.clientlist(["away", "voice"])
            self.afk_list = [client for client in afk_list if client.get('client_type', '1') == '0']  # ignore bots
            AfkMover.logger.debug("Awaylist: " + str(self.afk_list))
        except TS3Exception:
            AfkMover.logger.exception("Error getting away list!")
            self.afk_list = list()

    def get_away_list(self):
        """
        Get list of clients with afk status.
        :return: List of clients that are set to afk.
        """
        if self.afk_list is not None:
            AfkMover.logger.debug(str(self.afk_list))
            awaylist = list()
            for client in self.afk_list:
                AfkMover.logger.debug(str(self.afk_list))
                if "cid" not in client.keys():
                    AfkMover.logger.error("Client without cid!")
                    AfkMover.logger.error(str(client))
                elif client.get("client_away", '0') == '1' and \
                        client.get("cid", '-1') not in self.afk_channels:
                    awaylist.append(client)
                elif ("client_output_muted" in client.keys() or "client_output_hardware" in client.keys()) and \
                        int(client.get("cid", '-1')) != int(self.afk_channel):
                    clid = client.get("clid", '-1')
                    if client["client_output_muted"] == '1' or client["client_output_hardware"] == '0':
                        # client is muted
                        if clid in self.muted_since:
                            if client.get('cid', -1) in self.afk_channels:
                                del self.muted_since[clid]
                            else:
                                # still muted, but more than x minutes?
                                if datetime.datetime.now() - self.muted_since[clid] > afkMover.mute_time:
                                    # regarded as AFK
                                    awaylist.append(client)
                        else:
                            # add to mute list
                            if client.get('cid', -1) not in self.afk_channels:
                                self.muted_since[clid] = datetime.datetime.now()
                    else:
                        # client is not muted
                        if clid in self.muted_since:
                            # delete from muted dict
                            del self.muted_since[clid]
            return awaylist
        else:
            AfkMover.logger.error("Clientlist is None!")
            return list()

    def get_back_list(self):
        """
        Get list of clients in the afk channel, but not away or muted.
        :return: List of clients who are back from afk.
        """
        return [
            client for client in self.afk_list if (
                    client.get("client_away", '1') == '0' and
                    client.get("client_output_muted", '1') == '0' and
                    client.get("client_output_hardware", '0') == '1' and
                    int(client.get("cid", '-1')) == int(self.afk_channel)
            )
        ]

    def get_afk_channel(self, name=AFK_CHANNEL):
        """
        Get the channel id of the channel specified by name.
        :param name: Channel name
        :return: Channel id
        """
        try:
            channel = self.ts3conn.channelfind(name)[0].get("cid", '-1')
        except TS3Exception:
            AfkMover.logger.exception("Error getting afk channel")
            raise
        return channel

    def move_to_afk(self, clients):
        """
        Move clients to the afk_channel.
        :param clients: List of clients to move.
        """
        AfkMover.logger.info("Moving clients to afk!")
        for client in clients:
            AfkMover.logger.info("Moving somebody to afk!")
            AfkMover.logger.debug("Client: " + str(client))
            try:
                cid = self.afk_channel
                if client.get("client_nickname", '').lower() in ('aqer', 'krami'):
                    cid = 90
                self.ts3conn.clientmove(cid, int(client.get("clid", '-1')))
            except TS3Exception:
                AfkMover.logger.exception("Error moving client! Clid=" + str(client.get("clid", '-1')))
            self.client_channels[client.get("clid", '-1')] = client.get("cid", '0')
            if client.get("clid", '-1') in self.muted_since:
                del self.muted_since[client.get("clid", '-1')]
            AfkMover.logger.debug("Moved List after move: " + str(self.client_channels))

    def move_all_afk(self):
        """
        Move all afk clients.
        """
        try:
            afk_list = self.get_away_list()
            self.move_to_afk(afk_list)
        except AttributeError:
            AfkMover.logger.exception("Connection error!")

    def move_all_back(self):
        """
        Move all clients who are back from afk.
        """
        back_list = self.get_back_list()
        AfkMover.logger.debug("Moving clients back")
        AfkMover.logger.debug("Backlist is: " + str(back_list))
        AfkMover.logger.debug("Saved channel list keys are:" + str(self.client_channels.keys()) + "\n")
        for client in back_list:
            if client.get("clid", -1) in self.client_channels.keys():
                AfkMover.logger.info("Moving a client back!")
                AfkMover.logger.debug("Client: " + str(client))
                AfkMover.logger.debug("Saved channel list keys:" + str(self.client_channels))
                cid = self.client_channels.get(client.get("clid", -1))
                channels = {c.get('cid', -1): c for c in bot.ts3conn.channellist() if c.get('pid', -1) == '15'}
                if int(channels.get(cid, {}).get('total_clients', 1)) == 0:
                    # find max
                    cid = max(channels, key=lambda e: int(channels[e].get('total_clients', 0)))
                    if int(channels[cid].get('total_clients', 1)) == 0:
                        cid = random.choice(list(channels.keys()))
                self.ts3conn.clientmove(cid, int(client.get("clid", '-1')))
                del self.client_channels[client.get("clid", '-1')]

    def auto_move_all(self):
        """
        Loop move functions until the stop signal is sent.
        """
        while not self.stopped.wait(2.0):
            if datetime.datetime.now().weekday() in (0, 1, 2, 3, 4) and 7 < datetime.datetime.now().hour < 17:
                self.mute_time = MUTE_TIME_WORK
            else:
                self.mute_time = MUTE_TIME

            AfkMover.logger.debug("Afkmover running!")
            self.update_afk_list()
            try:
                self.move_all_back()
                self.move_all_afk()
            except:
                AfkMover.logger.error("Uncaught exception:" + str(sys.exc_info()[0]))
                AfkMover.logger.error(str(sys.exc_info()[1]))
                AfkMover.logger.error(traceback.format_exc())
                AfkMover.logger.error("Saved channel list keys are:" + str(self.client_channels.keys()) + "\n")
        AfkMover.logger.warning("AFKMover stopped!")
        self.client_channels = {}

    def get_name(self, clid):
        name = str(clid)
        for client in self.afk_list:
            if client.get('clid', '-1') == str(clid):
                name = client['client_nickname']
        return name
