# Docker container manipulation helpers

import os, subprocess, sys, tarfile, base64, io, tempfile
import json
import docker
import atexit
import pprint
from collections import OrderedDict, namedtuple

from docker.types import EndpointSpec
from docker.types.services import ConfigReference, SecretReference

_cache = dict()
_localCache = None

def docker_host(hostname=None):
    global _cache, _localCache

    if hostname is None:
        if _localCache is None:
            _localCache = docker.from_env()
        return _localCache

    if hostname in _cache:
        return _cache[hostname]

    if hostname.startswith('env:'):
        # use host specification from environment variables (for CI)
        prefix = hostname[4:]
        hostvar = f'{prefix}_HOST'
        secretsvar = f'{prefix}_SECRETS'
        host, secrets = (os.environ.get(hostvar), os.environ.get(secretsvar))
        if host and secrets:
            print(f'Using {hostvar} and {secretsvar} environment variables...')
            tmpdir = tempfile.TemporaryDirectory()
            atexit.register(tmpdir.cleanup)
            tmpdir = tmpdir.name
            if os.path.isfile(secrets):
                with open(secrets, 'r') as f:
                    secrets = f.read()
            with io.BytesIO(base64.b64decode(secrets)) as f, tarfile.open(fileobj=f, mode='r') as tar:
                tar.extractall(path=tmpdir)
            res = docker.DockerClient(base_url=host, tls=docker.tls.TLSConfig(
                client_cert=(os.path.join(tmpdir, 'cert.pem'), os.path.join(tmpdir, 'key.pem')),
                ca_cert=os.path.join(tmpdir, 'ca.pem'),
                verify=True, assert_hostname=False, assert_fingerprint=False))
        else:
            print(f'ERROR: Both {hostvar} and {secretsvar} environment variables must be defined')
            sys.exit(1)
    else:
        # use docker-machine host
        with open(os.path.expanduser(f'~/.docker/machine/machines/{hostname}/config.json')) as machine:
            cfg = json.load(machine)
        addr = cfg['Driver'].get('URL', None) or f"tcp://{cfg['Driver']['IPAddress']}:2376"
        machine = cfg['Driver']['MachineName']
        certs = cfg['HostOptions']['AuthOptions']
        res = docker.DockerClient(base_url=addr, tls=docker.tls.TLSConfig(
            client_cert=(certs['ClientCertPath'], certs['ClientKeyPath']),
            ca_cert=certs['CaCertPath'],
            verify=True, assert_hostname=False, assert_fingerprint=False))
        vars(res)['hostname']=machine

    _cache[hostname] = res
    return res

class ImageRef:
    def __init__(self, ref=''):
        self.hash = None
        self.tag = None

        i = ref.rfind('@')
        if i > 0:
            self.hash = ref[i+1:]
            ref = ref[:i]
        i = ref.rfind(':')
        if i > 0:
            self.tag = ref[i+1:]
            ref = ref[:i]

        self.name = ref

    def format(self, withTag=True, withHash=True):
        res = self.name
        if withTag and self.tag:
            res = res + ':' + self.tag
        if withHash and self.hash:
            res = res + '@' + self.hash
        return res

    @property
    def imageWithTag(self):
        return self.format(withHash=False)

    def __str__(self):
        return self.format()

    def find_update_tag(self, images):
        prefix = self.name + ':'
        if images:
            for img in images:
                if img.startswith(prefix):
                    return img[len(prefix):]
        return None

    def find(self, docker: docker.DockerClient):
        match = docker.images.list(self.imageWithTag)
        if match and len(match):
            return match[0]
        return None

    def find_update(self, docker : docker.DockerClient, tag, pull=False):
        res = ImageRef()
        res.name = self.name
        res.tag = tag

        new = None if pull else res.find(docker)
        if new is None:
            new = docker.images.pull(res.imageWithTag)

        repoDigests = new.attrs['RepoDigests']
        if len(repoDigests):
            res.hash = repoDigests[0].split('@')[1]
        else:
            res.hash = None
        return res

class ServiceUpdater:
    ANY_VALUE = object()
    IDName = namedtuple('IDName', ('id', 'name'))

    def __init__(self, service: docker.models.services.Service, client=None, name=None):
        self.service = service
        if service:
            self.client = service.client
            self.name = service.name
            self.spec = service.attrs.get('Spec', {})
        else:
            if not client or not name:
                raise Exception(f'Client and name must be specified when creating new services')
            self.client = client
            self.name = name
            self.spec = {}
        self.reset()

    def reset(self):
        self.template = self.spec.get('TaskTemplate', {})
        self.cspec = self.template.get('ContainerSpec', {})
        self.labels = self.spec.get('Labels', {})
        self.clabels = self.cspec.get('Labels', {})
        self.image = ImageRef(self.cspec.get('Image', ''))
        self.env = dict(k.split('=', 1) for k in self.cspec.get('Env', []))
        self.args = ServiceUpdater.parse_args(self.cspec.get('Args', []))
        self.mounts = {m['Target']:(m['Source'],'ro' if m.get('ReadOnly', False) else 'rw') for m in self.cspec.get('Mounts', [])}
        self.placement = self.template.get('Placement', {})
        self.constraints = self.placement.get('Constraints', [])
        self.networks = [n['Target'] for n in self.template.get('Networks', [])]
        self.endpoint_spec = self.spec.get('EndpointSpec', {})
        self.ports = self.endpoint_spec.get('Ports', [])
        self.secrets = [SecretReference(s['SecretID'], s['SecretName']) for s in self.cspec.get('Secrets', [])]
        self.configs = {self.IDName(c['ConfigID'], c['ConfigName']):c['File']['Name'] for c in self.cspec.get('Configs', [])}

        self.updates = dict()

    @staticmethod
    def create(client, name, image):
        svc = ServiceUpdater(None, client, name)
        if type(image) is str:
            image = ImageRef(image)
        svc.image = image
        return svc

    @property
    def stack(self):
        return self.labels.get('com.docker.stack.namespace', None)

    def get_env(self, key):
        return self.env.get(key, None)

    def ensure_constraint(self, constraint):
        if not constraint in self.constraints:
            self.constraints.append(constraint)
            self.updates['constraints'] = self.constraints

    def ensure_env(self, key, value):
        if self.env.get(key, None) != value:
            if value is None:
                self.env.pop(key)
            else:
                self.env[key] = value
            self.updates['env'] = [f'{k}={v}' for (k,v) in self.env.items()]

    def remove_env(self, key):
        if self.env.pop(key, None):
            self.updates['env'] = [f'{k}={v}' for (k,v) in self.env.items()]

    def ensure_network(self, network):
        if not network.id in self.networks:
            self.networks.append(network.id)
            self.updates['networks'] = self.networks

    def has_label(self, name, value=ANY_VALUE):
        if not name in self.labels:
            return False
        if value is not self.ANY_VALUE and self.labels[name] != value:
            return False
        return True

    def ensure_label(self, name, value):
        if not value is None:
            value = str(value)
        if self.labels.get(name, None) != value:
            if value is None:
                self.labels.pop(name)
            else:
                self.labels[name] = value
            self.updates['labels'] = self.labels

    def remove_label(self, name):
        if self.labels.pop(name, None) is not None:
            self.updates['labels'] = self.labels

    def remove_labels(self, prefix):
        remove = [k for k in self.labels if k == prefix or k.startswith(prefix) and not k[len(prefix)].isalnum()]
        for k in remove:
            self.remove_label(k)

    def ensure_clabel(self, name, value):
        if not value is None:
            value = str(value)
        if self.clabels.get(name, None) != value:
            if value is None:
                self.clabels.pop(name)
            else:
                self.clabels[name] = value
            self.updates['container_labels'] = self.clabels

    @staticmethod
    def _obj_match(obj, **kwargs):
        for k, v in kwargs.items():
            if not k in obj:
                return False
            if obj[k] != v:
                return False
        return True

    def ensure_port(self, port, override=None, **kwargs):
        match = next((p for p in self.ports if ServiceUpdater._obj_match(p, **kwargs)), None)
        if match and not override:
            return match
        port = override or port
        if match and match['PublishedPort'] == port:
            return match
        if match:
            match['PublishedPort'] = port
        else:
            self.ports.append(dict(kwargs, PublishedPort=port))
        self.updates['endpoint_spec'] = EndpointSpec(ports={ p['PublishedPort']: (p['TargetPort'], p.get('Protocol', 'tcp')) for p in self.ports })

    def emit_args(self):
        return [k if v is None else f'{k}={v}' for (k,v) in self.args.items()]

    @staticmethod
    def parse_args(args):
        return OrderedDict((a.split('=', 1) + [None])[:2] for a in args)

    def has_arg(self, arg, value=ANY_VALUE):
        if not arg in self.args:
            return False
        if value is not self.ANY_VALUE and self.args[arg] != value:
            return False
        return True

    def remove_arg(self, arg):
        if self.args.pop(arg, None) is not None:
            self.updates['args'] = self.emit_args()

    def remove_args(self, prefix):
        remove = [k for k in self.args if k == prefix or k.startswith(prefix) and not k[len(prefix)].isalnum()]
        for k in remove:
            self.remove_arg(k)

    def ensure_arg(self, arg, value=None):
        if not arg in self.args or self.args[arg] != value:
            self.args[arg] = value
            self.updates['args'] = self.emit_args()

    def ensure_args(self, *args):
        if len(self.args) != len(args) or args != self.emit_args():
            self.args = self.parse_args(args)
            self.updates['args'] = self.emit_args()

    def ensure_mount(self, target, source, options='rw'):
        value = (source,options)
        if not target in self.mounts or self.mounts[target] != value:
            self.mounts[target] = value
            self.updates['mounts'] = [f'{v[0]}:{k}:{v[1]}' for k,v in self.mounts.items()]

    def ensure_secret(self, secret):
        if isinstance(secret, str):
            secret = self.client.secrets.get(secret)
            secret = SecretReference(secret.id, secret.name)

        if not secret in self.secrets:
            self.secrets.append(secret)
            self.updates['secrets'] = self.secrets

    def ensure_config(self, config, filename=None):
        if isinstance(config, str):
            config = self.client.configs.get(config)

        key = self.IDName(config.id, config.name)

        if not key in self.configs or self.configs[key] != filename:
            self.configs[key] = filename
            self.updates['configs'] = [ConfigReference(c.id, c.name, filename=f) for (c,f) in self.configs.items()]

    def update_image(self, images=None, pull=False):
        tag = self.image.find_update_tag(images)
        if tag and (pull or tag != self.image.tag):
            print(f'  {self.name} ({self.image.name})')
            print(f'    current: {self.image.tag}@{self.image.hash}')
            print(f'    new:     ', end='')
            new = self.image.find_update(self.client, tag, pull)
            print(f"{new.tag}@{new.hash or 'local'}")
            if self.image.hash != new.hash:
                self.image = new
                self.updates['image'] = self.image.format()

    def pending(self):
        return len(self.updates)

    def dirty(self):
        return not self.service or self.pending()

    def preview(self):
        if not self.service:
            print(f'Will create service {self.name}: {self}')
        elif self.pending():
            print(f'Will update service {self.name}: {self}')

    def apply(self):
        if not self.service:
            print(f'Creating service {self.name}: {self}')
            self.client.services.create(self.image.format(), name=self.name, **self.updates)
        elif self.pending():
            print(f'Updating service {self.name}: {self}')
            self.service.update(**self.updates)
        self.updates.clear()

    def __str__(self):
        return pprint.pformat(self.updates)

    def run(self):
        return self.get_container(use_existing=False);

    def get_container(self, use_existing=True):
        container = None
        if use_existing:
            container = next(iter(self.client.containers.list(filters={'label':f'com.docker.swarm.service.id={self.service.id}'})), None)
        if container:
            return Container(container)
        else:
            return Container(self.image, client=self.client, networks=self.networks, environment=self.env)

class Container:
    def __init__(self, imageOrContainer, client=None, networks=None, **kwargs):
        if isinstance(imageOrContainer, docker.models.containers.Container):
            self.container = imageOrContainer
            self.kill_atexit = None
        else:
            image = str(imageOrContainer)
            print(f'Spawning container {image}...', end='', flush=True)
            if networks and len(networks):
                kwargs['network'] = networks[0]
                additionalNetworks = [client.networks.get(n) for n in networks[1:]]
            else:
                additionalNetworks = []
            self.container = client.containers.run(image, entrypoint=['sleep', 'infinity'], detach=True, remove=True, healthcheck={}, **kwargs)
            def kill_atexit():
                self.kill()

            self.kill_atexit = kill_atexit
            atexit.register(kill_atexit)

            for net in additionalNetworks:
                net.connect(self.container)

            print(self.container.short_id)

    def kill(self):
        if self.kill_atexit:
            atexit.unregister(self.kill_atexit)
            self.kill_atexit = None

            print(f'Destroying container {self.container.short_id}...')
            self.container.kill()

    def exec(self, *command, line=None, ignore_error=False, entrypoint_override=False, environment=None):
        if not entrypoint_override:
            entrypoint = self.container.image.attrs['ContainerConfig']['Entrypoint']
            if entrypoint:
                command = (*entrypoint, *command)
        exec_id = self.container.client.api.exec_create(self.container.id, command, tty=True, environment=environment)['Id']
        for r in self.container.client.api.exec_start(exec_id, stream=True):
            os.write(1, r)
            if line:
                line(r.decode('utf-8'))
        resp = self.container.client.api.exec_inspect(exec_id)
        err = resp['ExitCode']
        if not ignore_error and err != 0:
            print(f'Command {command} in container {self.container} failed with error code {err}')
            sys.exit(err)

        return resp

class CommandArgs:
    def __init__(self, args):
        self.args = dict(a.split('=', 1) for a in args)
