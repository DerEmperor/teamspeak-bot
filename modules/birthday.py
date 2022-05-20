from __future__ import annotations

from threading import Thread
import Bot
from Moduleloader import *
import threading
from modules.utils import send_message_to_everyone, poke_message_to_everyone
import json
import datetime
from time import sleep
from typing import List, Dict
from dataclasses import dataclass

FILE_NAME = 'birthdays.json'
BIRTHDAY_CHANNEL_ID1 = 87
BIRTHDAY_CHANNEL_ID2 = 96
TIME_FOR_NOTIFICATION = [datetime.timedelta(minutes=5), datetime.timedelta(seconds=15)]
TIME_FOR_NOTIFICATION.sort(reverse=True)

birthdayNotifier: BirthdayNotifier | None = None
birthdayNotifierStopper = threading.Event()
bot: Bot.Ts3Bot | None = None
birthday_file = FILE_NAME
autoStart = True


def date_to_str(date: datetime.date):
    return f'{date.day}.{date.month}.'


def str_to_date(string: str):
    year = today().year
    day, month, ignore = string.split('.')
    date = datetime.date(year, int(month), int(day))

    if date < today():
        date = date.replace(year=year + 1)

    return date


def today():
    date = datetime.date.today()
    return date


def sleep_until(future):
    now = datetime.datetime.now()
    if future < now:
        return
    waiting_seconds = (future - now).total_seconds()
    sleep(waiting_seconds)


def delta_to_string(delta: datetime.timedelta):
    sec = delta.seconds
    if sec > 3600:
        return f'{round(sec / 3600, 1)} h'

    if sec > 60:
        return f'{round(sec / 60, 1)} min'

    return f'{sec} s'


@command('nextbirthday', 'nextbday', )
@group('Kaiser', 'Truchsess', 'Bürger')
def next_birthday(sender, msg):
    Bot.send_msg_to_client(bot.ts3conn, sender, str(birthdayNotifier.get_next_birthday()))


@command('addbirthday', )
@group('Kaiser', )
def add_birthday(sender, msg):
    _command, name, date = split_command(msg)
    day, month, year = date.split('.')
    if year == '':
        year = None
    birthday = Birthday(name, str_to_date(date), year, True)
    birthdayNotifier.add_birthday(birthday)
    Bot.send_msg_to_client(bot.ts3conn, sender, f'add birthday: {str(birthday)}')


@command('refreshbirthdaychannel', )
@group('Kaiser', 'Truchsess', )
def refresh_birthday_channel(sender, msg):
    birthdayNotifier.refresh_birthday_channel()
    Bot.send_msg_to_client(bot.ts3conn, sender, 'channel refreshed')


@command('refreshtodaysbirthday', )
@group('Kaiser', 'Truchsess', )
def refresh_todays_birthday(sender, msg):
    birthdayNotifier.refresh_todays_birthday()
    Bot.send_msg_to_client(bot.ts3conn, sender, "today's birthday refreshed")


@command('activatebirthday', )
@group('Kaiser', 'Truchsess', )
def activate_birthday(sender, msg):
    _command, name = split_command(msg)
    birthday = birthdayNotifier.activate_birthday(name)
    Bot.send_msg_to_client(bot.ts3conn, sender, f'activated birthday: {str(birthday)}')


@command('deactivatebirthday', 'Truchsess', )
@group('Kaiser', )
def deactivate_birthday(sender, msg):
    _command, name = split_command(msg)
    birthday = birthdayNotifier.deactivate_birthday(name)
    Bot.send_msg_to_client(bot.ts3conn, sender, f'deactivated birthday: {str(birthday)}')


@command('deletebirthday', )
@group('Kaiser', )
def delete_birthday(sender, msg):
    _command, name = split_command(msg)
    birthday = birthdayNotifier.delete_birthday(name)
    Bot.send_msg_to_client(bot.ts3conn, sender, f'deleted birthday: {str(birthday)}')


@command('startbirthday', 'birthdaystart', 'birthdayNotifier', )
@group('Kaiser', )
def start_birthday_notifier(sender=None, msg=None):
    """
    Start the BirthdayNotifier by clearing the birthdayNotifierStopper signal and starting the notifier.
    """
    global birthdayNotifier
    if birthdayNotifier is None:
        birthdayNotifier = BirthdayNotifier(birthday_file, birthdayNotifierStopper, bot.ts3conn)
        birthdayNotifierStopper.clear()
        birthdayNotifier.start()


@command('stopbirthday', 'birthdaystop')
@group('Kaiser', )
def stop_birthday_notifier(sender=None, msg=None):
    """
    Stop the BirthdayNotifier by setting the birthdayNotifierStopper signal and undefining the notifier.
    """
    global birthdayNotifier
    birthdayNotifierStopper.set()
    birthdayNotifier = None


@setup
def setup(ts3bot, file=FILE_NAME):
    global bot, birthday_file
    bot = ts3bot
    birthday_file = file
    if autoStart:
        start_birthday_notifier()


@exit
def birthday_notifier_exit():
    global birthdayNotifier
    birthdayNotifierStopper.set()
    birthdayNotifier.join()
    birthdayNotifier = None


@dataclass
class Birthday:
    name: str
    birthday: datetime.date
    year: int | None = None
    active: bool = False

    @classmethod
    def from_dict(cls, d):
        return cls(d['name'], d['birthday'], d.get('year', None), d.get('active', True))

    @property
    def age(self):
        if not self.year:
            return None
        age = self.birthday.year - self.year
        if self.birthday <= today():
            return age
        else:
            return age - 1

    def dict(self) -> Dict[str, str | datetime.date | int | bool]:
        return {'name': self.name, 'birthday': self.birthday, 'year': self.year, 'active': self.active}

    def __str__(self):
        if self.year:
            return f'{self.name}: {date_to_str(self.birthday)}{self.year}'
        else:
            return f'{self.name}: {date_to_str(self.birthday)}'

    def __repr__(self):
        status = 'active' if self.active else 'deactivated'
        return f'{self.name}: {date_to_str(self.birthday)}{self.year} ({status})'

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        if other is None:
            return False
        return self.name == other.name

    def __ne__(self, other):
        return not (self == other)


class BirthdayNotifier(Thread):
    """
    BirthdayNotifier class. Notifies users from birthdays
    """
    logger = logging.getLogger("birthday")
    logger.propagate = 0
    logger.setLevel(logging.WARNING)
    file_handler = logging.FileHandler("birthday.log", mode='a+')
    formatter = logging.Formatter('birthday Logger %(asctime)s %(message)s')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.info("Configured birthday logger")
    logger.propagate = 0

    def __init__(self, file: str, _event: threading.Event, ts3conn):
        Thread.__init__(self)
        self.stopped = _event
        self.ts3conn = ts3conn

        self.birthdays: List[Birthday] = []
        self.birthday_file = file

        self.todays_birthday = None
        self.post_init()

    def post_init(self):
        self.read_data()
        self.refresh_birthday_channel()
        self.refresh_todays_birthday()

    def run(self):
        """
        Thread run method. Starts the mover.
        """
        BirthdayNotifier.logger.info("AFKMove Thread started")
        try:
            self.main()
        except:
            self.logger.exception("Exception occurred in run:")

    def main(self):
        while not self.stopped.wait(2.0):
            BirthdayNotifier.logger.debug("BirthdayNotifier running!")
            # wait until TIME_FOR_CHECK
            # message everyone about birthday
            bday = self.get_next_birthday()
            for delta in TIME_FOR_NOTIFICATION:
                date = today()
                timepoint = datetime.datetime(date.year, date.month, date.day, 23, 59, 59, 999999) - delta
                sleep_until(timepoint)
                if bday.birthday == (today() + datetime.timedelta(days=1)):
                    #  tomorrow is a birthday
                    if bday.age:
                        message = f'{bday.name} wird in {delta_to_string(delta)} {bday.age}.'
                    else:
                        message = f'{bday.name} hat in {delta_to_string(delta)} Geburtstag.'
                    send_message_to_everyone(bot.ts3conn, message)
            # wait until midnight
            # change birthday
            date = today()
            midnight = datetime.datetime(date.year, date.month, date.day, 0, 0, 0, 1) + datetime.timedelta(days=1)
            sleep_until(midnight)
            self.refresh_todays_birthday()
            if self.todays_birthday:
                #  today is a birthday
                if bday.age:
                    message = f'{bday.name} wird heute {bday.age}.'
                else:
                    message = f'{bday.name} hat heute Geburtstag.'
                poke_message_to_everyone(bot.ts3conn, message)

        BirthdayNotifier.logger.warning("BirthdayNotifier stopped!")

    def read_data(self):
        with open(self.birthday_file, 'r') as file:
            data_dict = json.load(file)

        data = []
        for entry in data_dict:
            entry['birthday'] = str_to_date(entry['birthday'])
            birthday = Birthday.from_dict(entry)
            data.append(birthday)

        # sort by days
        data.sort(key=lambda _birthday: _birthday.birthday)

        self.birthdays = data

    def write_data(self):
        dicts = []
        for birthday in self.birthdays:
            entry = birthday.dict()
            # convert date to str
            entry['birthday'] = date_to_str(entry['birthday'])
            dicts.append(entry)

        with open(self.birthday_file, 'w', newline='') as file:
            json.dump(dicts, file, indent=4)

    def get_next_birthday(self):
        for birthday in self.birthdays:
            if birthday.active:
                return birthday
        return None

    def get_by_name(self, name: str):
        for birthday in self.birthdays:
            if birthday.name == name:
                return birthday

    def refresh_birthday_channel(self):
        # get next birthdays
        next_bday = self.birthdays[0]
        second_next_birthday = self.birthdays[1]
        first = True
        for birthday in self.birthdays:
            if birthday.active:
                if first:
                    next_bday = birthday
                    first = False
                else:
                    second_next_birthday = birthday
                    break

        # create channel names
        next_birthday_name = f'[cspacer]{next_bday.name} {date_to_str(next_bday.birthday)}'
        age = next_bday.age
        if age:
            next_birthday_name += f' ({age})'
        second_next_birthday_name = f'[cspacer] {second_next_birthday.name} {date_to_str(second_next_birthday.birthday)}'

        age = second_next_birthday.age
        if age:
            second_next_birthday_name += f' ({age})'

        # set channel names
        bot.ts3conn.set_channel_name(BIRTHDAY_CHANNEL_ID1, next_birthday_name)
        bot.ts3conn.set_channel_name(BIRTHDAY_CHANNEL_ID2, second_next_birthday_name)

    def refresh_birthday_list(self):
        while self.birthdays[0].birthday < today():
            self.birthdays.append(self.birthdays[0])
            del self.birthdays[0]

    def refresh_todays_birthday(self):
        self.refresh_birthday_list()
        if self.get_next_birthday().birthday == today():
            # someone's birthday is today
            if self.get_next_birthday() == self.todays_birthday:
                # everything is ok
                pass
            else:
                # set birthday
                self.todays_birthday = self.get_next_birthday()
            bday = self.todays_birthday
            if bday.age:
                bot.ts3conn.set_hostmessage(f"Alles Gute zum {bday.age}. Geburtstag, {bday.name}")
            else:
                bot.ts3conn.set_hostmessage(f"Alles Gute zum Geburtstag, {bday.name}")

        else:
            # no birthday today :(
            if self.todays_birthday:
                # clear bday
                self.todays_birthday = None
                self.refresh_birthday_channel()
            else:
                # everything is ok
                pass
            bot.ts3conn.disable_hostmessage()

    def post_changes(self):
        self.write_data()
        self.refresh_birthday_channel()
        self.refresh_todays_birthday()

    def add_birthday(self, birthday: Birthday):
        self.birthdays.append(birthday)
        self.birthdays.sort(key=lambda b: b.birthday)
        self.post_changes()
        return birthday

    def delete_birthday(self, name: str):
        birthday = self.get_by_name(name)
        self.birthdays.remove(birthday)
        self.post_changes()
        return birthday

    def deactivate_birthday(self, name: str):
        birthday = self.get_by_name(name)
        birthday.active = False
        self.post_changes()
        return birthday

    def activate_birthday(self, name: str):
        birthday = self.get_by_name(name)
        birthday.active = True
        self.post_changes()
        return birthday

    def set_year(self, name: str, year: str):
        birthday = self.get_by_name(name)
        if year:
            birthday.year = int(year)
        else:
            birthday.year = None
        self.post_changes()
        return birthday
