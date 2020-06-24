from traefikswarm import Context

HELP = 'create a container for forwarding to another host inside or outside docker'

def configure_argparser(parser):
    parser.add_argument('name', metavar='NAME', help='name of the forwarding service')
    parser.add_argument('host', metavar='HOST', help='target host where traffic is forwarded')
    parser.add_argument('port', metavar='PORT', help='target port where traffic is forwarded (default: 80)', default=80, nargs='?')

def execute(ctx: Context):
    svc = ctx.get_or_deploy_service(ctx.args.name, 'alpine/socat', init=True)
    svc.ensure_args(f'TCP4-LISTEN:{ctx.args.port},fork', f'TCP4:{ctx.args.host}:{ctx.args.port}')
