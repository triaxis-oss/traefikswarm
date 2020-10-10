import argparse, os
from traefikswarm import context
from collections import OrderedDict

HELP = 'configure traefik service'

def configure_argparser(parser):
    parser.add_argument('--entrypoint-add', help=f'Entrypoint to add (name[=port])', action='append', default=[])
    parser.add_argument('--entrypoint-rm', help=f'Entrypoint to remove', action='append', default=[])
    parser.add_argument('--env-add', help='Environment to add', action='append', default=[])
    parser.add_argument('--env-rm', help='Environment to remove', action='append', default=[])
    parser.add_argument('--user-add', help=f'Basic auth user to add', action='append', default=[])
    parser.add_argument('--user-rm', help=f'Basic auth user to remove', action='append', default=[])
    parser.add_argument('--arg-add', help=f'Argument to add', action='append', default=[])
    parser.add_argument('--arg-rm', help=f'Argument to remove', action='append', default=[])
    parser.add_argument('--debug', help='Enable debug log', action='store_true', default=None)
    parser.add_argument('--no-debug', help='Disable debug log', action='store_false', dest='debug')
    parser.add_argument('--accesslog', help='Enable access log', action='store_true', default=None)
    parser.add_argument('--no-accesslog', help='Disable access log', action='store_false', dest='accesslog')
    parser.add_argument('--insecure-tls', help='Enable insecure backend access over TLS', action='store_true', default=None)
    parser.add_argument('--no-insecure-tls', help='Disable insecure backend access over TLS', action='store_false', dest='insecure_tls')
    parser.add_argument('--api', help='Enable API and dashboard', action='store_true', default=None)
    parser.add_argument('--no-api', help='Disable API and dashboard', action='store_false', dest='api')
    parser.add_argument('--acme-email', help=f'ACME (Let\'s Encrypt) e-mail to use for registration')
    parser.add_argument('--acme-domains', help=f'ACME (Let\'s Encrypt) domains to use', action='append')
    parser.add_argument('--acme-domains-add', help=f'ACME (Let\'s Encrypt) domains to add', action='append')
    parser.add_argument('--acme-domains-rm', help=f'ACME (Let\'s Encrypt) domains to remove', action='append')
    parser.add_argument('--acme-dns-exe', help=f'ACME (Let\'s Encrypt) DNS auth handler executable')
    parser.add_argument('--acme-server', help=f'ACME (Let\'s Encrypt) server to use', default=None)
    parser.add_argument('--acme-staging', help=f'Enable use of ACME staging server', action='store_true', default=None)
    parser.add_argument('--acme-no-staging', help=f'Disable use of ACME staging server', action='store_false', dest='acme_staging')
    parser.add_argument('--acme-store', help=f'ACME store')

class EntryPoint:
    def __init__(self, name):
        self.name = name
        self.args = OrderedDict()

    def redirect_to(self, entrypoint, schema):
        self.args['http.redirections.entryPoint.to'] = entrypoint
        self.args['http.redirections.entryPoint.scheme'] = schema

    def update(self, service, name):
        args = self.args.copy()

        # remove acme domain settings from entrypoints without acme
        if args.get('http.tls.certResolver', None) != 'acme':
            args.pop('http.tls.domains[0].main', None)
            args.pop('http.tls.domains[0].sans', None)

        prefix = f'--entrypoints.{name}.'
        for key, _ in [i for i in service.args.items()]:
            if key.startswith(prefix):
                lkey = key[len(prefix):]
                if lkey in args:
                    service.ensure_arg(key, args[lkey])
                    del(args[lkey])
                else:
                    service.remove_arg(key)
        for key, value in args.items():
            service.ensure_arg(prefix + key, value)
        if self.port:
            service.ensure_port(self.port, TargetPort=self.port)

    def remove(self, service, name):
        self.args.clear()
        self.update(service, name)

    @property
    def acme_domains(self):
        main = self.args.get('http.tls.domains[0].main', None)
        sans = self.args.get('http.tls.domains[0].sans', None)
        res = [main] if main else []
        if sans:
            res = res + sans.split(',')
        return res

    @acme_domains.setter
    def acme_domains(self, domains):
        if len(domains):
            self.args['http.tls.domains[0].main'] = domains[0]
        else:
            self.args.pop('http.tls.domains[0].main', None)

        if len(domains) > 1:
            self.args['http.tls.domains[0].sans'] = ','.join(domains[1:])
        else:
            self.args.pop('http.tls.domains[0].sans', None)

    @property
    def tls(self):
        return 'http.tls' in self.args

    @tls.setter
    def tls(self, value):
        if value:
            self.args['http.tls'] = None
        else:
            self.args.pop('http.tls', None)

    @property
    def acme(self):
        return self.args.get('http.tls.certResolver', None) == 'acme'

    @acme.setter
    def acme(self, value):
        if value:
            self.args['http.tls.certResolver'] = 'acme'
        elif self.acme:
            self.args.pop('http.tls.certResolver')

    @property
    def port(self):
        listen = self.args.get('address', None)
        if listen:
            return int(listen.split(':')[1].split('/')[0])
        else:
            return None

    @port.setter
    def port(self, value):
        listen = self.args.get('address', None)
        if listen:
            parts = listen.split(':')
            subparts = parts[1].split('/')
            subparts[0] = str(value)
            parts[1] = '/'.join(subparts)
            self.args['address'] = ':'.join(parts)
        else:
            self.args['address'] = f':{value}'

    @property
    def protocol(self):
        listen = self.args.get('address', None)
        if listen:
            parts = listen.split(':')
            subparts = parts[1].split('/')
            return subparts[1] if len(subparts) > 1 else ''
        else:
            return None

    @protocol.setter
    def protocol(self, value):
        listen = self.args.get('address', None)
        if listen:
            parts = listen.split(':')
            subparts = parts[1].split('/')
            if value:
                subparts = [subparts[0], value]
            else:
                subparts = [subparts[0]]
            parts[1] = '/'.join(subparts)
            self.args['address'] = ':'.join(parts)
        elif value:
            self.args['address'] = f':0/{value}'
        else:
            self.args['address'] = f':0'

default_ports = {
    'http': 80,
    'https': 443,
}

def execute(ctx: context.Context):
    args = ctx.args

    traefik = ctx.get_or_deploy_global_service('traefik', 'traefik:2.2')

    # required for docker access
    traefik.ensure_constraint('node.role == manager')
    # default stack network access
    if ctx.stackname:
        traefik.ensure_network(ctx.stack_network)

    # collect entrypoint args
    entrypoints = {}
    for key, value in traefik.args.items():
        parts = key.split('.')
        if parts[0] == '--entrypoints':
            ep = entrypoints.setdefault(parts[1], EntryPoint(parts[1]))
            ep.args['.'.join(parts[2:])] = value

    for name in args.entrypoint_rm:
        ep = entrypoints.pop(name, None)
        if ep:
            ep.remove(traefik, name)
            traefik.remove_port(port)
            
    for spec in args.entrypoint_add:
        parts = spec.split('=', 2)
        name = parts[0]
        protocol = ''
        if len(parts) == 1:
            port = default_ports.get(name, None)
            if port is None:
                ctx.abort(f'non-standard entrypoint name {name}, please specify port explicitly')
        else:
            subparts = parts[1].split('/', 2)
            port = int(subparts[0])
            if len(subparts) > 1:
                protocol = subparts[1]
        ep = entrypoints.setdefault(name, EntryPoint(name))
        ep.port = port
        ep.protocol = protocol
        ep.acme = ep.tls = (name != 'http' and protocol == '') # TODO: explicit setting

    # use Let's Encrypt certificates
    if args.acme_domains:
        for ep in entrypoints.values():
            ep.acme_domains = args.acme_domains
    else:
        if args.acme_domains_add:
            for ep in entrypoints.values():
                ep.acme_domains = ep.acme_domains + args.acme_domains_add
        if args.acme_domains_rm:
            for ep in entrypoints.values():
                ep.acme_domains = [d for d in ep.acme_domains if d not in args.acme_domains_rm]

    if args.acme_store:
        traefik.ensure_mount('/acme.json', ctx.relpath(args.acme_store))

    if args.acme_dns_exe:
        traefik.ensure_mount('/usr/local/bin/acme-dns', ctx.relpath(args.acme_dns_exe), 'ro')
        traefik.ensure_arg('--certificatesResolvers.acme.acme.dnsChallenge.provider', 'exec')
        traefik.ensure_env('EXEC_PATH', '/usr/local/bin/acme-dns')

    if args.acme_server:
        traefik.ensure_arg('--certificatesResolvers.acme.acme.caServer', ags.acme_server)
    elif args.acme_staging == True:
        traefik.ensure_arg('--certificatesResolvers.acme.acme.caServer', 'https://acme-staging-v02.api.letsencrypt.org/directory')
    elif args.acme_staging == False:
        traefik.remove_arg('--certificatesResolvers.acme.acme.caServer')

    if args.acme_email:
        traefik.ensure_arg('--certificatesResolvers.acme.acme.email', args.acme_email)

    for env in args.env_add:
        traefik.ensure_env(*env.split('=', 2))
    for env in args.env_rm:
        traefik.remove_env(env)

    if args.debug == True:
        traefik.ensure_arg('--log.level', 'debug')
    elif args.debug == False:
        traefik.remove_arg('--log.level')

    if args.accesslog == True:
        traefik.ensure_arg('--accesslog')
    elif args.accesslog == False:
        traefik.remove_arg('--accesslog')

    if args.insecure_tls == True:
        traefik.ensure_arg('--serverstransport.insecureskipverify')
    elif args.insecure_tls == False:
        traefik.remove_arg('--serverstransport.insecureskipverify')

    if args.api == True:
        traefik.ensure_arg('--api')
        traefik.ensure_arg('--api.dashboard')
        traefik.ensure_arg('--api.debug')
        traefik.ensure_label('traefik.http.routers.traefik-api.entrypoints', 'https')
        traefik.ensure_label('traefik.http.routers.traefik-api.rule', 'HostRegexp(`traefik.{domain:.+}`)')
        traefik.ensure_label('traefik.http.routers.traefik-api.priority', '9999')
        traefik.ensure_label('traefik.http.routers.traefik-api.service', 'api@internal')
        traefik.ensure_label('traefik.http.routers.traefik-api.middlewares', 'traefik-auth')
        traefik.ensure_label('traefik.http.services.traefik-api.loadbalancer.server.port', 9)
        traefik.ensure_label('traefik.enable', 'true')
    elif args.api == False:
        traefik.remove_args('--api')
        traefik.remove_labels('traefik.http.routers.traefik-api')

    traefik.ensure_arg('--providers.docker')
    traefik.ensure_arg('--providers.docker.swarmMode', 'true')
    traefik.ensure_arg('--providers.docker.exposedByDefault', 'false')

    for arg in args.arg_rm:
        traefik.remove_arg(f'--{arg}')
    for arg in args.arg_add:
        traefik.ensure_arg(f'--{arg}')

    # TODO: properly parameterize
    if 'http' in entrypoints:
        if 'https' in entrypoints:
            entrypoints['http'].redirect_to('https', 'https')
        else:
            entrypoints['http'].remove_redirect()

    for name, ep in entrypoints.items():
        ep.update(traefik, name)

    traefik.ensure_mount('/var/run/docker.sock', '/var/run/docker.sock', 'ro')

    if ctx.opt_arg('user_add') or ctx.opt_arg('user_rm'):
        users = OrderedDict()
        for entry in traefik.labels.get('traefik.http.middlewares.traefik-auth.basicauth.users', '').split(','):
            if entry:
                u, p = entry.split(':', 2)
                users[u] = p
        for u in ctx.opt_arg('user_rm'):
            users.pop(u)
        for e in ctx.opt_arg('user_add'):
            u, p = e.split(':', 2)
            users[u] = p
        users = ','.join((f'{u}:{p}' for u, p in users.items()))
        traefik.ensure_label('traefik.http.middlewares.traefik-auth.basicauth.users', users)
