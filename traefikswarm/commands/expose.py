from traefikswarm import Context

def configure_argparser(parser):
    parser.add_argument('service', metavar='SERVICE', help='Service to expose')
    parser.add_argument('port', metavar='PORT', help='Service port to expose', type=int)
    parser.add_argument('--entrypoint-add', help='Entrypoints to add', action='append')
    parser.add_argument('--entrypoint-rm', help='Entrypoints to remove', action='append')
    parser.add_argument('-H', '--host-add', help='Hostname prefixes to add', action='append')
    parser.add_argument('--host-rm', help='Hostname prefixes to remove', action='append')
    parser.add_argument('--lbswarm', help='Use swarm load balancer', action='store_true', default=None)
    parser.add_argument('--lbtraefik', help='Use traefik load balancer', action='store_true', default=None)
    parser.add_argument('--router', help='Traefik router name override')
    parser.add_argument('--https', help='Use HTTPS for communication with backend', action='store_true', default=None)
    parser.add_argument('--http', help='Use HTTP for communication with backend (default)', action='store_false', dest='https')
    parser.add_argument('--tcp', help='Expose TCP directly', action='store_true', dest='tcp')

def execute(ctx: Context):
    args = ctx.args
    name = args.service
    port = args.port
    svc = ctx.get_service(name) if ctx.stackname else ctx.get_global_service(name)

    if not svc:
        ctx.abort(f'Service {name} not found')

    router = args.router or f'{svc.name}-{port}'
    protocol = 'tcp' if args.tcp else 'http'
    lprefix = f'traefik.{protocol}.routers.{router}'

    entrypoints = [ep for ep in svc.labels.get(f'{lprefix}.entryPoints', '').split(',') if ep]
    for e in args.entrypoint_rm or ():
        entrypoints.remove(e)

    for e in args.entrypoint_add or ():
        if e not in entrypoints:
            entrypoints.append(e)

    hosts = []
    rule = svc.labels.get(f'{lprefix}.rule', '')
    if rule.endswith('`)'):
        if rule.startswith('HostRegexp(`'):
            hosts = rule[12:-2].replace('{domain:.+}', '*').split('`,`')
        elif rule.startswith('Host(`'):
            hosts = rule[6:-2].split('`,`')
    
    for h in args.host_rm or ():
        hosts.remove(h)

    for h in args.host_add or ():
        if h not in hosts:
            hosts.append(h)

    wild = any((h for h in hosts if '*' in h))
    sni = 'SNI' if args.tcp else ''
    if hosts:
        if wild:
            rule = 'Host{sni}Regexp(`' + '`,`'.join((h.replace('*', '{domain:.+}') for h in hosts)) + '`)'
        else:
            rule = 'Host{sni}(`' + '`,`'.join(hosts) + '`)'
    else:
        rule = 'HostSNI(`*`)' if args.tcp else 'PathPrefix(`/`)'     # catch-all

    if not entrypoints:
        entrypoints = ['https']

    svc.ensure_label('traefik.enable', 'true')
    if args.lbswarm == True:
        svc.ensure_label('traefik.docker.lbswarm', 'true')
    elif args.lbtraefik == True:
        svc.remove_label('traefik.docker.lbswarm')
    svc.ensure_label(f'{lprefix}.entryPoints', ','.join(entrypoints))
    svc.ensure_label(f'{lprefix}.service', router)
    svc.ensure_label(f'{lprefix}.rule', rule)
    if not args.tcp:
        svc.ensure_label(f'{lprefix}.priority', len(rule) + (0 if wild else 100))
    svc.ensure_label(f'traefik.{protocol}.services.{router}.loadbalancer.server.port', port)
    if not args.tcp:
        if args.https == True:
            svc.ensure_label(f'traefik.http.services.{router}.loadbalancer.server.scheme', 'https')
        elif args.https == False:
            svc.remove_label(f'traefik.http.services.{router}.loadbalancer.server.scheme')
