#!/usr/bin/env python3

import os
import sys
#  import locale
import asyncio
import inotify
#  import argparse

#  encoding = locale.getpreferredencoding(False)

def colorize(color, pathname):
    icon = ''
    text = ''
    with open(pathname) as f:
        line = f.readline().rstrip()
        if len(line):
            icon = f'%{{F{color}}}{line[0]}%{{F-}}'
            if len(line) > 1:
                text = line[1:]
    return f'{icon}{text}'


def main(root: str, paths=[], color=None):
    loop = asyncio.get_event_loop()
    paths_to_watch = list(
            map(
                lambda p: os.path.join(root, p),
                paths if paths else os.listdir(root),
                )
            )
    async def mainline() :
        watcher = inotify.Watcher.create()
        for path in paths_to_watch :
            #  watcher.watch(path, inotify.IN.ALL_EVENTS)
            watcher.watch(path, inotify.IN.MODIFY)
        #end for
        async for event in watcher.iter_async():
            output = colorize(color, event.watch.pathname)
            if output:
                sys.stdout.write(f'{output}\n')
                sys.stdout.flush()
        #end for

        #  while True :
        #      event = await watcher.get()
        #      #  sys.stdout.write("Got event: %s\n" % repr(event))
        #end while

    #end mainline
    loop.run_until_complete(mainline())


if __name__ == '__main__':
    root = os.environ['XDG_RUNTIME_DIR']
    root = os.path.join(root, 'ui-statuses')
    color = sys.argv[1]
    resource = sys.argv[2]
    try:
        asyncio.run(main(root, [resource], color=color))
    except KeyboardInterrupt:
        print("\ninterrupt received, stopping…\n")


# vim: set ft=python fdm=indent ai ts=4 sw=4 tw=79 et:
