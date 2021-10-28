#!/usr/bin/env python3

import os
import sys
import locale
import asyncio
#  import signal
import argparse
#  from contextlib import suppress

import pulsectl_asyncio
#  from mprisctl import PlayerManager
#  import aiofiles

import time
from operator import itemgetter
from pydbus import SessionBus
from gi.repository import GLib

def get_volume_icon(value: float, mute: bool):
    muted = ''
    ramp = [
            '',
            '',
            '',
            '',
            '',
            '',
            ]
    if mute:
        return muted
    pos = int(value * 6 / 100)
    pos = 5 if pos == 6 else pos
    return ramp[0]

def shorten(s: str, t: str, l: int):
    return s if (len(s) <= l) else s[:l] + t

async def volume(queue: asyncio.Queue):
    def raw(value, mute):
        return ('rawvolume', '', str(value) + ('!' if mute else ''))

    def status(value, mute):
        return ('volume', get_volume_icon(value, mute), f'{value: 3d}%')

    async with pulsectl_asyncio.PulseAsync('event-printer') as pulse:
        # Get name of monitor_source of default sink
        server_info = await pulse.server_info()
        sink_info = await pulse.get_sink_by_name(server_info.default_sink_name)
        #  print(sink_info)
        index = sink_info.index
        async for event in pulse.subscribe_events('sink'):
            #  print('Pulse event:', event)
            if index == event.index:
                sinks = await pulse.sink_list()
                value = round(sinks[index].volume.value_flat * 100)
                mute = sinks[index].mute == 1
                queue.put_nowait(raw(value, mute))
                queue.put_nowait(status(value, mute))

__service__ = 'org.mpris.MediaPlayer2'
__object__ = '/org/mpris/MediaPlayer2'
__interface__ = 'org.mpris.MediaPlayer2'

bus = SessionBus()


class SafeDict(dict):
    def __missing__(self, key):
        return None


class Player:
    def __init__(self, bus_name, owner):
        self.bus_name = bus_name
        self.name = bus_name.split('.')[3]
        self.owner = owner
        self.disconnecting = False
        self.proxy = None
        self.connect()
        self.properties = SafeDict()
        self.properties['PlaybackStatus'] = self.proxy.PlaybackStatus
        self.properties['Metadata'] = self.proxy.Metadata
        self.properties['Volume'] = self.proxy.Volume

    def refreshStatus(self):
        # Some clients (VLC) will momentarily create a new player before
        # removing it again so we can't be sure the interface still exists
        self.properties['PlaybackStatus'] = self.proxy.PlaybackStatus

    def refreshMetadata(self):
        # Some clients (VLC) will momentarily create a new player before
        #  removing it again so we can't be sure the interface still exists
        self.properties['Metadata'] = self.proxy.Metadata

    def connect(self):
        self.disconnecting = False
        self.proxy = bus.get(self.bus_name, __object__)

    def disconnect(self):
        self.disconnecting = True
        self.proxy = None

    @property
    def Metadata(self):
        return self.properties['Metadata']

    @Metadata.setter
    def Metadata(self, metadata):
        self.properties['Metadata'] = metadata

    @property
    def PlaybackStatus(self):
        return self.properties['PlaybackStatus']

    @PlaybackStatus.setter
    def PlaybackStatus(self, status):
        self.properties['PlaybackStatus'] = status

    @property
    def Volume(self):
        return self.properties['Volume']

    @Volume.setter
    def Volume(self, value):
        self.properties['Volume'] = value

    @property
    def Position(self):
        return self.properties['Position']

    @Position.setter
    def Position(self, value):
        self.properties['Position'] = value

    def __repr__(self):
        return f'{self.name}[{self.owner}]({self.PlaybackStatus})'
#- Player


class MprisListener():
    def __init__(self, blacklist=[]):
        self.blacklist = blacklist[:]
        self.players = {}
        self.last_status = None
        self.status_owner = None
        self.connected = False
        self.subscriptions = []

    def connect(self):
        self.initializePlayerList()
        self.subscriptions.append(
                bus.subscribe(
                    signal='NameOwnerChanged',
                    signal_fired=self.on_name_owner_changed,
                    )
                )
        self.subscriptions.append(
                bus.subscribe(
                    object=__object__,
                    signal='Seeked',
                    signal_fired=self.on_seeked,
                    )
                )
        self.subscriptions.append(
                bus.subscribe(
                    object=__object__,
                    signal='PropertiesChanged',
                    signal_fired=self.on_properties_changed,
                    )
                )
        try:
            subscription = bus.subscribe(
                    object=__object__,
                    signal='TrackMetadataChanged',
                    signal_fired=self.on_track_metadata_changed,
                    )
            self.subscriptions.append(subscription)
        except AttributeError:
            pass

    def disconnect(self):
        for owner in self.players:
            self.players[owner].disconnect()
        for subscription in self.subscriptions:
            subscription.unsubscribe()
        self.connected = False

    def on_name_owner_changed(self, sender, path, iface, signal, params):
        bus_name, old_owner, new_owner = params
        if self.busNameIsAPlayer(bus_name):
            time.sleep(0.5)
            if new_owner and not old_owner:
                need_update = self.addPlayer(bus_name, new_owner)
            elif old_owner and not new_owner:
                need_update = self.removePlayer(old_owner)
            else:
                need_update = self.changePlayerOwner(bus_name, old_owner, new_owner)
            if need_update:
                self.refreshStatus()

    def on_track_metadata_changed(self, sender, path, iface, signal, params):
        track_id, metadata = params
        player = self.players[sender]
        name = player.name
        owner = player.owner
        try:
            player.refreshMetadata()
            if player.owner == self.getStatusOwner():
                self.refreshStatus()
        except AttributeError:
            pass

    def on_seeked(self, sender, path, iface, signal, params):
        position = params
        player = self.players[sender]
        if player.owner == self.getStatusOwner():
            self.refreshStatus()

    def on_properties_changed(self, sender, path, iface, signal, params):
        interface, properties, signature = params
        player = self.players[sender]
        updated = False
        if 'Metadata'in properties:
            if properties['Metadata'] != player.Metadata:
                player.Metadata = properties['Metadata']
                updated = True
        if 'PlaybackStatus' in properties:
            if properties['PlaybackStatus'] != player.PlaybackStatus:
                player.PlaybackStatus = properties['PlaybackStatus']
                updated = True
        if 'Volume' in properties:
            if properties['Volume'] != player.Volume:
                player.Volume = properties['Volume']
                updated = True
        if updated:
            if player.owner == self.getStatusOwner():
                self.refreshStatus()

    def busNameIsAPlayer(self, bus_name):
        return bus_name.startswith(__service__) and bus_name.split('.')[3] not in self.blacklist

    def initializePlayerList(self):
        bus_names = [bus_name for bus_name in bus.dbus.ListNames()
                if self.busNameIsAPlayer(bus_name)]
        for bus_name in bus_names:
            owner = bus.dbus.GetNameOwner(bus_name)
            self.addPlayer(bus_name, owner=owner)
        if self.connected != True:
            self.connected = True
            self.refreshStatus()

    def addPlayer(self, bus_name, owner = None) -> bool:
        self.players[owner] = Player(bus_name, owner)
        return self.getStatusOwner() == owner

    def removePlayer(self, owner) -> bool:
        if owner in self.players:
            self.players[owner].disconnect()
            del self.players[owner]
            return True
        return False

    def changePlayerOwner(self, bus_name, old_owner, new_owner):
        updated = False
        if self.removePlayer(old_owner):
            updated = True
        if self.addPlayer(bus_name, new_owner):
            updated = True
        return updated

    # Get a list of player owners sorted by current status and age
    def getSortedPlayerOwnerList(self):
        players = [
                {
                    'number': int(owner.split('.')[-1]),
                    'status': 2 if player.PlaybackStatus == 'Playing' else 1 if player.PlaybackStatus == 'paused' else 0,
                    'owner': owner,
                    }
                for owner, player in self.players.items()
                ]
        return [info['owner'] for info in reversed(sorted(players, key=itemgetter('status', 'number')))]

    # Get status owner
    def getStatusOwner(self):
        if len(self.players):
            sorted_owners = self.getSortedPlayerOwnerList()
            playing_players = [
                    owner for owner in sorted_owners
                    if self.players[owner].PlaybackStatus == 'Playing' or
                    self.players[owner].PlaybackStatus == 'Paused'
                    ]
            self.status_owner = playing_players[0] \
                    if playing_players else sorted_owners[0]
        else:
            self.status_owner = None
        return self.status_owner

    def refreshStatus(self):
        raise NotImplementedError


class MprisListenerAsync(MprisListener):
    def __init__(self, queue: asyncio.Queue, blacklist=[]):
        super().__init__(blacklist)
        self.queue = queue

    async def run(self):
        self.connect()
        while self.connected:
            await asyncio.sleep(5)

    def getStatus(self):
        if len(self.players):
            owner = self.getStatusOwner()
            return self.playerStatus(owner)
        else:
            return ICON_STOPPED, ''

    def refreshStatus(self):
        #  if len(self.players):
        #      owner = self.getStatusOwner()
        #      self.queue.put_nowait(('mpris', *self.playerStatus(owner)))
        #  else:
        #      self.queue.put_nowait(('mpris', ICON_STOPPED, ''))
        status = self.getStatus()
        if status != self.last_status:
            self.last_status = status
            self.queue.put_nowait(('mpris', *status))
            #  print(*status, flush=True)

    def playerStatus(self, owner: str):
        player = self.players[owner]
        nowplaying = ''
        icon = {
                'Playing': ICON_PLAYING,
                'Paused': ICON_PAUSED,
                'Stopped': ICON_STOPPED,
                }[player.PlaybackStatus]
        if player.PlaybackStatus in [ 'Playing', 'Paused' ]:
            key = ''
            for k in list(player.Metadata):
                if k.endswith(':nowplaying'):
                    key = k
                    break
            if key:
                nowplaying = player.Metadata.get(key)
            else:
                artists = player.Metadata.get('xesam:artist')
                artist = artists[0] if artists else ''
                title = player.Metadata.get('xesam:title', '')
                url = player.Metadata.get('xesam:url', '')
                artist = shorten(artist, TRUNCATE_STRING, 30)
                title = shorten(title, TRUNCATE_STRING, 45)
                nowplaying = f'{artist} - {title}' \
                        if url.startswith('file://') and artist and title \
                        else f'{title}' if title else url
            nowplaying = shorten(nowplaying, TRUNCATE_STRING, 75)
        return icon, nowplaying


async def mpris(queue: asyncio.Queue):
    # Requires a running glib mainloop
    try:
        listener = MprisListenerAsync(queue, BLACKLIST)
        task = asyncio.create_task(listener.run())
        await task
    except KeyboardInterrupt:
        listener.disconnect()

#  async def mpris(queue: asyncio.Queue):
#      # Create the subprocess; redirect the standard output into a pipe.
#      mpris_format='{{lc(status)}}|{{xesam:artist}}|{{xesam:title}}|{{xesam:url}}|{{playerName}}|{{vlc:nowplaying}}'
#      cmdargs = [
#              'playerctl',
#              '-F', '-a',
#              '-f', mpris_format, 'metadata',
#              ]
#      proc = await asyncio.create_subprocess_exec(*cmdargs, stdout=asyncio.subprocess.PIPE)
#
#      #  To read one line of output.
#      #  data = await proc.stdout.readline()
#      #  line = data.decode('ascii').rstrip()
#      encoding = locale.getpreferredencoding(False)
#      async for line in proc.stdout:
#          items = line.decode(encoding).rstrip().split('|')
#          player = items[4]
#          if player in BLACKLIST:
#              continue
#          icon = {
#                  'playing': ICON_PLAYING,
#                  'paused': ICON_PAUSED,
#                  'stopped': ICON_STOPPED,
#                  }[items[0]]
#          artist = items[1]
#          title = items[2]
#          url = items[3]
#          nowplaying = items[5]
#          if not nowplaying:
#              artist = shorten(artist, TRUNCATE_STRING, 30)
#              title = shorten(title, TRUNCATE_STRING, 45)
#              nowplaying = f'{artist} - {title}' \
#                      if url.startswith('file://') and artist and title \
#                      else f'{title}' if title else url
#          else:
#              nowplaying = shorten(nowplaying, TRUNCATE_STRING, 75)
#          queue.put_nowait(('mpris', icon, nowplaying))
#      # Wait for the subprocess exit.
#      await proc.wait()

async def cpupercent(queue: asyncio.Queue):
    idle = 0
    total = 0
    while True:
        #  async with aiofiles.open('/proc/stat', mode='r') as f:
        #      line = await f.readline()
        with open('/proc/stat') as f:
            line = f.readline()
        tokens = line.split()
        cur_total = sum(map(int, tokens[1:]))
        cur_idle = int(tokens[4])
        percent = 1 - ( (cur_idle - idle) / (cur_total - total))
        queue.put_nowait(('cpupercent', '', f'{percent: 3.0%}'))
        idle = cur_idle
        total = cur_total
        await asyncio.sleep(1)

async def loadavg(queue: asyncio.Queue):
    while True:
        #  async with aiofiles.open('/proc/loadavg', mode='r') as f:
        #      line = await f.readline()
        with open('/proc/loadavg') as f:
            line = f.readline()
        tokens = line.split()
        queue.put_nowait(('loadavg', '', '{} {} {}'.format(*tokens[:3])))
        await asyncio.sleep(10)

async def mempercent(queue: asyncio.Queue):
    while True:
        #  async with aiofiles.open('/proc/meminfo', mode='r') as f:
        #      async for line in f:
        with open('/proc/meminfo') as f:
            for line in f:
                if line.startswith('Mem'):
                    if line.startswith('MemTotal'):
                        memtotal = int(line.split()[1])
                    elif line.startswith('MemAvailable'):
                        memavailable = int(line.split()[1])
                elif line.startswith('Swap'):
                    if line.startswith('SwapTotal'):
                        swaptotal = int(line.split()[1])
                    elif line.startswith('SwapFree'):
                        swapfree = int(line.split()[1])
                        break
        mempercent = (memtotal - memavailable) / memtotal
        queue.put_nowait(('mempercent', '', f'{mempercent: 3.0%}'))
        swapused = (swaptotal - swapfree) / 1024
        queue.put_nowait(('swapused', '', f'{swapused: 3.0f} MiB'))
        await asyncio.sleep(5)

async def netspeed(queue: asyncio.Queue):
    downbytes = 0
    upbytes = 0
    while True:
        with open('/proc/net/dev') as f:
            for line in f:
                tokens = line.split()
                if tokens[0].endswith(':') and tokens[0] != 'lo:':
                    device = tokens[0].strip(':')
                    down = int(tokens[1])
                    up = int(tokens[9])
                    downspeed = (down - downbytes) / 1024
                    downtotal = down / 1024 / 1024
                    upspeed = (up - upbytes) / 1024
                    uptotal = up / 1024 / 1024
                    downbytes = down
                    upbytes = up
                    break
        queue.put_nowait(('device', '', device))
        queue.put_nowait(('downspeed', '', f'{downspeed: 4.1f} KiB/s'))
        queue.put_nowait(('downtotal', '', f'{downtotal: 4.1f} MiB'))
        queue.put_nowait(('upspeed', '', f'{upspeed: 4.1f} KiB/s'))
        queue.put_nowait(('uptotal', '', f'{uptotal: 4.1f} MiB'))
        await asyncio.sleep(1)

async def consumer(root: str, queue: asyncio.Queue):
    def write_status(tag: str, icon: str, output: str):
        dest = os.path.join(root, tag)
        if icon:
            output = f'{icon} {output}'
        with open(dest, mode='w') as f:
            f.write(f'{output}')
        #  print(text, flush=True)

    while True:
        tag, icon, output = await queue.get()
        write_status(tag, icon, output)
        queue.task_done()

async def main(args):
    # Create a queue that we will use to store our "workload".
    queue = asyncio.Queue()
    # Set up glib mailoop
    loop = asyncio.get_running_loop()
    glib_loop = GLib.MainLoop()
    fut = loop.run_in_executor(None, glib_loop.run)
    # Create worker tasks to process the queue concurrently.
    tasks = []
    if args.cpu:
        tasks.append(asyncio.create_task(cpupercent(queue)))
    if args.load:
        tasks.append(asyncio.create_task(loadavg(queue)))
    if args.mem:
        tasks.append(asyncio.create_task(mempercent(queue)))
    if args.net:
        tasks.append(asyncio.create_task(netspeed(queue)))
    if args.vol:
        tasks.append(asyncio.create_task(volume(queue)))
    if args.mpris:
        tasks.append(asyncio.create_task(mpris(queue)))
    tasks.append(asyncio.create_task(consumer(args.root, queue)))
    try:
        await asyncio.gather(*tasks, return_exceptions=True)
    except KeyboardInterrupt:
        print("\ninterrupt received, stopping…\n", flush=True)
    except asyncio.CancelledError as e:
        pass
    finally:
        GLib.idle_add(glib_loop.quit)
        await fut

if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    parser.add_argument('-a', '--all', action='store_true', help='all statuses')

    parser.add_argument('-c', '--cpu', action='store_true', help='cpu percent usage')
    parser.add_argument('-l', '--load', action='store_true', help='load average')
    parser.add_argument('-m', '--mem', action='store_true', help='memory percent and swap usage')
    parser.add_argument('-n', '--net', action='store_true', help='network download/upload speed/total')
    parser.add_argument('-v', '--vol', action='store_true', help='volume status')
    parser.add_argument('-p', '--mpris', action='store_true', help='mpris player status')
    parser.add_argument(
            '-b', '--blacklist',
            help="ignore a player by it's bus name. Can be be given multiple times (e.g. -b vlc -b audacious)",
            action='append',
            metavar="BUS_NAME",
            default=[],
            )
    parser.add_argument('--truncate-text', default='…')
    parser.add_argument('--icon-playing', default='')
    parser.add_argument('--icon-paused', default='')
    parser.add_argument('--icon-stopped', default='')
    parser.add_argument('--icon-none', default='')

    root = os.environ['XDG_RUNTIME_DIR']
    root = os.path.join(root, 'ui-statuses')
    parser.add_argument('--root', default=root)

    args = parser.parse_args()

    if args.all:
        args.cpu = True
        args.mem = True
        args.load = True
        args.net = True
        args.vol = True
        args.mpris = True

    if not os.path.isdir(args.root):
        os.mkdir(args.root, mode=0o700)

    BLACKLIST = args.blacklist
    TRUNCATE_STRING = args.truncate_text
    ICON_PLAYING = args.icon_playing
    ICON_PAUSED = args.icon_paused
    ICON_STOPPED = args.icon_stopped
    ICON_NONE = args.icon_none

    #  print(args)

    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        print("\n\ninterrupt received, stopping…\n")


# vim: set ft=python fdm=indent ai ts=4 sw=4 tw=79 et:
