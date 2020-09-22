from traefikswarm import Context

def configure_argparser(parser):
    parser.add_argument('service', metavar='SERVICE', help='Service to un-expose')
    parser.add_argument('port', metavar='PORT', help='Port to un-expose', nargs='?', type=int)
    parser.add_argument('--router', help='Traefik router name override')

def execute(ctx: Context):
    args = ctx.args
    name = args.service
    svc = ctx.get_service(name) if ctx.stackname else ctx.get_global_service(name)

    if not svc:
        ctx.abort(f'Service {name} not found')

    if args.port or args.router:
        router = args.router or f'{svc.name}-{args.port}'
        for remove in [l for l in svc.labels if f'.{router}.' in l]:
            svc.remove_label(remove)
    else:
        svc.remove_labels('traefik')
