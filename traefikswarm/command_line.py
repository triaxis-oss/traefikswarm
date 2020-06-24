import argparse
import os

from traefikswarm import commands, context

def main():
    parser = argparse.ArgumentParser(description='Manage traefik serving a Docker Swarm')
    defaultHost=os.environ.get('TRAEFIKSWARM_HOST')
    parser.add_argument('-H', '--hostname', metavar='HOST', help=f'Target docker host (default: {defaultHost or "from environment"})', default=defaultHost)
    parser.add_argument('-S', '--stackname', metavar='STACK', help=f'Target stack (default: only non-stack services)', default=None)
    parser.add_argument('--init', help='Initialize missing resources', action='store_true')
    parser.add_argument('--commit', help='Commit the changes without asking', action='store_true')
    parser.add_argument('--preview', help='Only preview changes', action='store_true')

    sub = parser.add_subparsers(help='sub-command', metavar='COMMAND', required=True, dest='command')
    for cmd in commands.commands:
        cmdname = cmd.__name__.split('.')[-1]
        cmdparser = sub.add_parser(cmdname, help=getattr(cmd, 'HELP', None))
        if hasattr(cmd, 'configure_argparser'):
            cmd.configure_argparser(cmdparser)
        cmdparser.set_defaults(handler=cmd.execute)

    args = parser.parse_args()
    ctx = context.Context(args)
    ctx.run(args.handler)
