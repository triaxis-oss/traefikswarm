import sys, os, typing
from traefikswarm.dockertools import docker_host, ServiceUpdater, Container, ImageRef

class Context:
    class AbortException(Exception):
        pass

    def __init__(self, args):
        self.startdir = os.getcwd()
        self.args = args
        self.hostname = args.hostname
        self.stackname = args.stackname
        self.docker = docker_host(self.hostname)
        self.services = dict()
        self.global_services = dict()

        for svc in (ServiceUpdater(s) for s in self.docker.services.list()):
            stack = svc.stack
            if stack is None:
                self.global_services[svc.name] = svc
            elif stack == self.stackname:
                self.services[svc.name[len(self.stackname)+1:]] = svc

    @staticmethod
    def abort(*args, **kwargs):
        raise Context.AbortException(*args, **kwargs)

    def relpath(self, path):
        return os.path.join(self.startdir, path)

    def opt_arg(self, name, default=None):
        return getattr(self.args, name, default)

    def run(self, handler):
        try:
            handler(self)
            self.apply_changes()
        except Context.AbortException as err:
            print(err)
            exit(-1)

    def require_init(self, resType, resName, init=False):
        if not (init or self.opt_arg('init')):
            self.abort(f"{resType.capitalize()} '{resName}' not deployed, use --init")
        else:
            print(f"Creating {resType} '{resName}'...")

    def add_stackname(self, name):
        return f'{self.stackname}_{name}' if self.stackname else name

    def add_stacklabel(self, dictionary={}):
        if self.stackname:
            dictionary = dictionary.copy()
            dictionary['com.docker.stack.namespace'] = self.stackname
        return dictionary

    def get_network(self, name='default'):
        netname = self.add_stackname(name)
        networks = self.docker.networks.list(names=[netname])
        if len(networks):
            return networks[0]
        self.require_init('network', netname)
        return self.docker.networks.create(netname, driver='overlay', labels=self.add_stacklabel(), attachable=True)

    @property
    def stack_network(self):
        return self.get_network() if self.stackname else None

    def get_service(self, name) -> ServiceUpdater:
        return self.services.get(name, None)

    def pop_service(self, name) -> ServiceUpdater:
        return self.services.pop(name, None)

    def get_global_service(self, name) -> ServiceUpdater:
        return self.global_services.get(name, None)

    def get_or_deploy_service(self, name, image, init=False) -> ServiceUpdater:
        svc = self.get_service(name)
        if svc:
            return svc
        self.require_init('service', name, init=init)

        svc = ServiceUpdater.create(self.docker, self.add_stackname(name), image)
        svc.ensure_label('com.docker.stack.image', image)
        if self.stackname:
            svc.ensure_label('com.docker.stack.namespace', self.stackname)
            svc.ensure_clabel('com.docker.stack.namespace', self.stackname)
            svc.ensure_network(self.stack_network)
        self.services[name] = svc
        return svc

    def get_or_deploy_global_service(self, name, image) -> ServiceUpdater:
        svc = self.get_global_service(name)
        if svc:
            return svc
        self.require_init('global service', name)

        svc = ServiceUpdater.create(self.docker, name, image)
        self.global_services[name] = svc
        return svc

    def run_container(self, image, **kwargs) -> Container:
        return Container(image, client=self.docker, **kwargs)

    def apply_changes(self):
        if not self.args.commit:
            changes = False
            for svc in self.global_services.values():
                svc.preview()
                changes = changes or svc.dirty()
            for svc in self.services.values():
                svc.preview()
                changes = changes or svc.dirty()
            if not changes:
                print("No changes required")
                return
            if self.args.preview:
                return
            if input("To apply the changes, type 'yes': ") != 'yes':
                return
        for svc in self.global_services.values():
            svc.apply()
        for svc in self.services.values():
            svc.apply()
