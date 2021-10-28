#!/usr/bin/env python3

import os
import sys
import asyncio
import inotify
import argparse


class PolybarModule:
    def __init__(self, resource, bgcolor, hicolor, bottom=True):
        self.resource = resource
        self.bgcolor = bgcolor
        self.hicolor = hicolor
        self.tag = 'o' if bottom else 'u'
        self.buffer = ''
        self.memoized = ''

    def update(self):
        with open(self.resource) as f:
            line = f.readline().rstrip()
            if line != self.buffer:
                self.buffer = line
                self.memoized = self.format_status(self.colorize_icon(line))
    #end update

    @property
    def status(self):
        return self.memoized

    def colorize_icon(self, output):
        icon = ''
        text = ''
        if len(output):
            icon = f'%{{F{self.hicolor}}}{output[0]}%{{F-}}'
            if len(output) > 1:
                text = output[1:]
        return f'{icon}{text}'
    #end colorize_icon

    def format_status(self, output):
        #  return f'%{{{self.tag}{self.hicolor}}}%{{+{self.tag}}}%{{B{self.bgcolor}}} {output} %{{B-}}%{{-{self.tag}}}'
        str_fmt = '%{{{0}{1}}}%{{+{0}}}%{{B{2}}} {3} %{{B-}}%{{-{0}}}'
        return str_fmt.format(self.tag, self.hicolor, self.bgcolor, output)
    #end format_status
#end PolybarModule


def main(modules, color=None):
    loop = asyncio.get_event_loop()
    paths_to_watch = [modules[key].resource for key in modules]
    def get_fullstatus():
        return ' '.join([modules[key].status for key in modules])
    #end get_fullstatus
    async def mainline() :
        current = get_fullstatus()
        watcher = inotify.Watcher.create()
        for path in paths_to_watch :
            watcher.watch(path, inotify.IN.MODIFY)
        #end for
        async for event in watcher.iter_async():
            resource = event.watch.pathname
            name = os.path.basename(resource)
            modules[name].update()
            output = get_fullstatus()
            if output != current:
                sys.stdout.write(f'{output}\n')
                sys.stdout.flush()
                current = output
        #end for
    #end mainline
    loop.run_until_complete(mainline())
#end main


def get_module(name, root, args, bottom=True):
    return PolybarModule(
            os.path.join(root, name),
            vars(args)[f'bg_{name}'],
            vars(args)[f'hi_{name}'],
            bottom=bottom,
            )
#end get_module


if __name__ == '__main__':
    root = os.environ['XDG_RUNTIME_DIR']
    root = os.path.join(root, 'ui-statuses')

    parser = argparse.ArgumentParser()
    parser.add_argument('--top', action='store_true')
    parser.add_argument('--bg-cpupercent', default='#7fcc0000')
    parser.add_argument('--hi-cpupercent', default='#c0392b')
    parser.add_argument('--bg-mempercent', default='#5fff79c6')
    parser.add_argument('--hi-mempercent', default='#f012be')
    parser.add_argument('--bg-downspeed', default='#5fffb86c')
    parser.add_argument('--hi-downspeed', default='#ff851b')
    parser.add_argument('--bg-upspeed', default='#5fc4a000')
    parser.add_argument('--hi-upspeed', default='#fce947')
    args = parser.parse_args()

    bottom = False if args.top else True
    modules = {name: get_module(name, root, args, bottom=bottom)
            for name in [
                'cpupercent',
                'mempercent',
                'downspeed',
                'upspeed',
                ]
            }
    try:
        asyncio.run(main(modules))
    except KeyboardInterrupt:
        print("\n\ninterrupt received, stopping…\n")


# vim: set ft=python fdm=indent ai ts=4 sw=4 tw=79 et:
