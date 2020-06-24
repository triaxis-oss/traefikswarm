from traefikswarm import Context

def configure_argparser(parser):
    parser.add_argument('service', metavar='SERVICE', help='Service to un-expose')

def execute(ctx: Context):
    name = ctx.args.service
    svc = ctx.get_service(name) if ctx.stackname else ctx.get_global_service(name)

    if not svc:
        ctx.abort(f'Service {name} not found')

    svc.remove_labels('traefik')
