"""Local mesh catalogue and quarantined file imports. Never executes a converter or edits a scene."""
from datetime import datetime, timezone
import base64
import binascii
from contextlib import contextmanager
from email import policy
from email.errors import MessageError
from email.parser import BytesParser
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import stat
import struct
import threading
import time
from urllib.parse import quote, unquote, urlsplit
import uuid
import xml.etree.ElementTree as ET

MAX_UPLOAD = 64 * 1024 * 1024
MAX_FILES = 100
MAX_FILE = 96 * 1024 * 1024
MODEL_FORMATS = {'.glb', '.gltf', '.obj', '.stl'}
FILE_FORMATS = MODEL_FORMATS | {'.bin', '.mtl', '.png', '.jpg', '.jpeg', '.webp', '.tga', '.bmp'}
EXISTING_FORMATS = FILE_FORMATS | {'.dae', '.ktx2'}
ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,100}\Z')


class MeshError(ValueError):
    pass


def strict_json(data):
    """Reject non-standard numbers, duplicate keys and excessive nesting."""
    def constant(value):
        raise MeshError('Nombre JSON non fini interdit.')

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise MeshError('Clé JSON dupliquée.')
            result[key] = value
        return result

    try:
        result = json.loads(data, parse_constant=constant, object_pairs_hook=pairs)
        pending = [(result, 0)]
        while pending:
            value, depth = pending.pop()
            if depth > 64:
                raise MeshError('Document JSON trop imbriqué.')
            if isinstance(value, float) and not math.isfinite(value):
                raise MeshError('Nombre JSON non fini interdit.')
            if isinstance(value, dict):
                pending.extend((item, depth + 1) for item in value.values())
            elif isinstance(value, list):
                pending.extend((item, depth + 1) for item in value)
        return result
    except (ValueError, UnicodeError, RecursionError) as error:
        if isinstance(error, MeshError):
            raise
        raise MeshError('Document JSON invalide.') from error


def no_symlinks(path):
    path = Path(os.path.abspath(path))
    return not any(item.is_symlink() for item in (path, *path.parents))


def regular_bytes(path, limit):
    """Bounded regular-file read; never follows a symlink, including parents."""
    path = Path(os.path.abspath(path))
    descriptor = None
    try:
        descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
        for part in path.parts[1:-1]:
            child_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                               dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child_fd
        leaf = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                       dir_fd=descriptor)
        with os.fdopen(leaf, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                return None
            result = stream.read(limit + 1)
            return result if len(result) <= limit else None
    except (OSError, ValueError):
        return None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def read_json(path):
    try:
        data = regular_bytes(path, 2 * 1024 * 1024)
        if data is None:
            return {}
        result = strict_json(data)
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError, UnicodeError):
        return {}


def sdf_xml(data):
    """Inspect Gazebo's common gz:type attribute without rewriting its SDF."""
    try:
        return ET.fromstring(data)
    except ET.ParseError:
        if b'gz:' not in data or b'xmlns:gz' in data:
            raise
        inspection = re.sub(br'<sdf(?=[\s>])',
                            b'<sdf xmlns:gz="urn:lotusim:gazebo-inspection"', data, count=1)
        if inspection == data:
            raise
        return ET.fromstring(inspection)


def child(root, relative, extensions=EXISTING_FORMATS):
    if not isinstance(relative, str) or not relative or '\\' in relative or '\0' in relative:
        return None
    parts = relative.split('/')
    if any(not part or part in ('.', '..') or part.startswith('.') for part in parts):
        return None
    root = Path(os.path.abspath(root))
    if not no_symlinks(root):
        return None
    candidate = root.joinpath(*parts)
    if any(root.joinpath(*parts[:index]).is_symlink() for index in range(1, len(parts) + 1)):
        return None
    try:
        candidate.resolve(strict=True).relative_to(root)
        if candidate.is_file() and candidate.suffix.lower() in extensions and candidate.stat().st_size <= MAX_FILE:
            return candidate
    except (OSError, ValueError):
        pass
    return None


def text(value, limit=300):
    return str(value or '')[:limit].strip()


def source_url(value):
    value = text(value, 1500)
    if any(ord(character) < 33 or ord(character) == 127 for character in value):
        return ''
    try:
        parts = urlsplit(value)
        return value if parts.scheme == 'https' and parts.hostname and parts.port != 0 and not parts.username and not parts.password else ''
    except ValueError:
        return ''


def safe_name(value):
    if not isinstance(value, str) or len(value) > 200 or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_ .\-/]*', value):
        raise MeshError('Nom de fichier non pris en charge. Utiliser lettres, chiffres, tirets et underscores.')
    if any(not part or part in ('.', '..') or part.startswith('.') for part in value.split('/')):
        raise MeshError('Chemin de fichier non autorisé.')
    return value


def reference(value, parent, files):
    if not isinstance(value, str):
        raise MeshError('Référence de ressource invalide.')
    if value.startswith('data:'):
        if not re.match(r'\Adata:(?:application/(?:octet-stream|gltf-buffer)|image/(?:png|jpeg|webp));base64,', value):
            raise MeshError('Seules les données binaires et images embarquées sont acceptées.')
        try:
            payload = base64.b64decode(value.split(',', 1)[1], validate=True)
        except (binascii.Error, ValueError) as error:
            raise MeshError('Ressource base64 invalide.') from error
        if not payload or len(payload) > MAX_FILE:
            raise MeshError('Ressource embarquée vide ou trop volumineuse.')
        return
    try:
        parts = urlsplit(value)
    except ValueError:
        raise MeshError('URI de ressource invalide.')
    if parts.scheme or parts.netloc or parts.query or parts.fragment or '\\' in value or value.startswith('/'):
        raise MeshError('Les ressources distantes/absolues sont interdites. Joindre les textures et buffers locaux.')
    relative = posixpath.normpath(posixpath.join(str(PurePosixPath(parent).parent), unquote(parts.path)))
    safe_name(relative)
    if relative not in files:
        raise MeshError('Ressource manquante : ' + relative)


def validate_gltf(document, parent, files):
    if not isinstance(document, dict) or not isinstance(document.get('asset'), dict) or document['asset'].get('version') != '2.0':
        raise MeshError('Un modèle glTF 2.0 est requis.')
    required = document.get('extensionsRequired', [])
    if not isinstance(required, list) or any(not isinstance(value, str) for value in required):
        raise MeshError('Liste d’extensions glTF invalide.')
    unsupported = set(required) & {
        'KHR_draco_mesh_compression', 'EXT_meshopt_compression', 'KHR_texture_basisu'}
    if unsupported:
        raise MeshError('Importer une version glTF/GLB sans compression Draco, Meshopt ou KTX2.')
    for group in ('buffers', 'images', 'accessors'):
        items = document.get(group, [])
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise MeshError('Collection glTF invalide : ' + group)
        for item in items:
            if 'uri' in item:
                reference(item['uri'], parent, files)
            if group == 'buffers' and 'byteLength' in item:
                count = item['byteLength']
                if type(count) is not int or not 0 <= count <= MAX_FILE:
                    raise MeshError('Buffer glTF invalide ou trop volumineux.')
            if group == 'accessors':
                count = item.get('count', 0)
                if type(count) is not int or not 0 <= count <= 10000000:
                    raise MeshError('Géométrie trop volumineuse pour cet aperçu local.')


def validate_geometry(entry, files):
    data = files[entry]
    suffix = PurePosixPath(entry).suffix.lower()
    if suffix == '.glb':
        if len(data) < 20:
            raise MeshError('GLB incomplet.')
        magic, version, length = struct.unpack_from('<4sII', data)
        if magic != b'glTF' or version != 2 or length != len(data):
            raise MeshError('En-tête GLB 2.0 invalide.')
        offset, document, chunks = 12, None, set()
        while offset < len(data):
            if offset + 8 > len(data):
                raise MeshError('Bloc GLB incomplet.')
            size, kind = struct.unpack_from('<II', data, offset)
            offset += 8
            if size % 4 or offset + size > len(data) or kind in chunks:
                raise MeshError('Taille ou répétition de bloc GLB invalide.')
            if document is None:
                if kind != 0x4E4F534A or size > 8 * 1024 * 1024:
                    raise MeshError('Premier bloc JSON GLB invalide.')
                document = strict_json(data[offset:offset + size])
            chunks.add(kind)
            offset += size
        validate_gltf(document, entry, files)
    elif suffix == '.gltf':
        if len(data) > 8 * 1024 * 1024:
            raise MeshError('JSON glTF supérieur à 8 Mio.')
        validate_gltf(strict_json(data), entry, files)
    elif suffix == '.obj':
        value = data.decode('utf-8-sig')
        if '\0' in value or not re.search(r'^\s*v\s+', value, re.M) or not re.search(r'^\s*f\s+', value, re.M):
            raise MeshError('OBJ sans géométrie lisible (sommets et faces requis).')
        vertices = faces = 0
        for line in value.splitlines():
            fields = line.split('#', 1)[0].split()
            if not fields:
                continue
            if fields[0] == 'v':
                coords = fields[1:4]
                if len(coords) != 3 or not all(math.isfinite(float(x)) and abs(float(x)) < 1e9 for x in coords):
                    raise MeshError('Coordonnées OBJ invalides.')
                vertices += 1
            elif fields[0] == 'f':
                if len(fields) < 4:
                    raise MeshError('Face OBJ invalide.')
                for index in fields[1:]:
                    if not re.fullmatch(r'[+-]?[0-9]+(?:/[+-]?[0-9]*){0,2}', index):
                        raise MeshError('Indice de face OBJ invalide.')
                    vertex = int(index.split('/')[0])
                    if vertex == 0 or abs(vertex) > vertices:
                        raise MeshError('Indice OBJ hors des sommets disponibles.')
                faces += 1
            elif fields[0] == 'mtllib':
                reference(line.strip()[6:].strip(), entry, files)
            if vertices > 2000000 or faces > 2000000:
                raise MeshError('OBJ supérieur à deux millions de sommets/faces ; exporter un LOD ou un GLB.')
        if not vertices or not faces:
            raise MeshError('OBJ sans sommets ou faces.')
    elif suffix == '.stl':
        binary = len(data) >= 84 and 84 + struct.unpack_from('<I', data, 80)[0] * 50 == len(data)
        if binary:
            if struct.unpack_from('<I', data, 80)[0] > 2000000:
                raise MeshError('STL trop volumineux.')
            for offset in range(84, len(data), 50):
                if not all(math.isfinite(value) and abs(value) < 1e9 for value in struct.unpack_from('<12f', data, offset)):
                    raise MeshError('Coordonnées STL invalides.')
        elif not (data.lstrip().startswith(b'solid') and b'facet' in data and b'vertex' in data):
            raise MeshError('STL invalide.')
        else:
            vertices = 0
            for line in data.decode('utf-8-sig').splitlines():
                fields = line.split()
                if fields and fields[0] == 'vertex':
                    if len(fields) != 4 or not all(math.isfinite(float(value)) and abs(float(value)) < 1e9 for value in fields[1:]):
                        raise MeshError('Coordonnées STL invalides.')
                    vertices += 1
                    if vertices > 6000000:
                        raise MeshError('STL trop volumineux.')
            if not vertices or vertices % 3 or b'endsolid' not in data:
                raise MeshError('Triangles STL incomplets.')
    else:
        raise MeshError('Choisir un fichier GLB, glTF, OBJ ou STL comme entrée.')
    for name, content in files.items():
        if name.lower().endswith('.mtl'):
            for line in content.decode('utf-8-sig').splitlines():
                fields = line.strip().split(None, 1)
                if len(fields) == 2 and (fields[0].lower().startswith('map_') or fields[0].lower() in ('bump', 'disp', 'decal')):
                    value = fields[1].strip()
                    if value.startswith('-'):
                        raise MeshError('Options de texture MTL non prises en charge ; exporter un GLB ou simplifier le MTL.')
                    reference(value, name, files)


class MeshLibrary:
    def __init__(self, core, unity):
        self.core, self.unity = Path(core).resolve(), Path(unity).resolve()
        self.models = self.core / 'assets/models'
        self.store = self.core / 'artifacts/mesh-library/imports'
        self.lock = threading.RLock()
        self._updated = 0
        self._records, self._roots = [], {}

    @contextmanager
    def _store_directory(self, create=False):
        """Traverse storage by directory descriptors, never through a symlink."""
        descriptor = os.open(self.core, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for component in ('artifacts', 'mesh-library', 'imports'):
                if create:
                    try:
                        os.mkdir(component, mode=0o700, dir_fd=descriptor)
                    except FileExistsError:
                        pass
                child_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                   dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child_fd
            yield descriptor
        except OSError as error:
            raise MeshError('Dossier d’import non sûr ou inaccessible.') from error
        finally:
            os.close(descriptor)

    @staticmethod
    def _write_file(directory, relative, data):
        descriptor = os.dup(directory)
        try:
            parts = relative.split('/')
            for part in parts[:-1]:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
                child_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                   dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child_fd
            leaf = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                           0o600, dir_fd=descriptor)
            with os.fdopen(leaf, 'wb') as stream:
                stream.write(data)
        finally:
            os.close(descriptor)

    @staticmethod
    def _remove_staging(directory, name):
        """Remove only an unpublished, uniquely named request directory, via its parent fd."""
        descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                             dir_fd=directory)
        try:
            for entry in os.scandir(descriptor):
                if entry.is_dir(follow_symlinks=False):
                    MeshLibrary._remove_staging(descriptor, entry.name)
                else:
                    os.unlink(entry.name, dir_fd=descriptor)
        finally:
            os.close(descriptor)
        os.rmdir(name, dir_fd=directory)

    def file_url(self, model, relative):
        return '/api/assets/files/' + quote(model, safe='') + '/' + quote(relative, safe='/')

    def _files(self, root):
        result = {}
        if not no_symlinks(root):
            return result
        for path in sorted(root.rglob('*')):
            if len(result) >= 1000:
                break
            relative = path.relative_to(root).as_posix()
            if child(root, relative):
                result[relative] = path
        return result

    def _shapes(self, root):
        source = child(root, 'model.sdf', {'.sdf'})
        data = regular_bytes(source, 1024 * 1024) if source else None
        if data is None:
            return []
        try:
            xml = sdf_xml(data)
            shapes = []
            for visual in xml.findall('.//visual')[:100]:
                try:
                    pose = [float(x) for x in visual.findtext('pose', '0 0 0 0 0 0').split()]
                    color = [float(x) for x in visual.findtext('material/diffuse', '0.5 0.6 0.7 1').split()]
                    if len(pose) != 6 or len(color) != 4 or not all(math.isfinite(x) for x in pose + color):
                        continue
                    base = {'position': pose[:3], 'rotation': pose[3:], 'color': color}
                    cylinder = visual.find('geometry/cylinder')
                    sphere = visual.find('geometry/sphere')
                    box = visual.find('geometry/box')
                    if cylinder is not None:
                        dimensions = [float(cylinder.findtext('radius')), float(cylinder.findtext('length'))]
                        base.update(type='cylinder', radius=dimensions[0], length=dimensions[1])
                    elif sphere is not None:
                        dimensions = [float(sphere.findtext('radius'))]
                        base.update(type='sphere', radius=dimensions[0])
                    elif box is not None:
                        dimensions = [float(x) for x in box.findtext('size').split()]
                        if len(dimensions) != 3:
                            continue
                        base.update(type='box', size=dimensions)
                    else:
                        continue
                    if all(math.isfinite(value) and 0 < value < 1e6 for value in dimensions):
                        shapes.append(base)
                except (ValueError, TypeError):
                    continue
            return shapes
        except (ET.ParseError, OSError):
            return []

    def _sdf_mesh_entry(self, root, files, model, source_model):
        source = child(root, 'model.sdf', {'.sdf'})
        data = regular_bytes(source, 1024 * 1024) if source else None
        if data is None:
            return None
        try:
            xml = sdf_xml(data)
            # The rendered visual is the primary object. Collision meshes are
            # only a fallback, e.g. lrauv's tethys.dae rather than its fin STL.
            for query in ('.//visual/geometry/mesh/uri', './/collision/geometry/mesh/uri'):
                for element in xml.findall(query):
                    uri = (element.text or '').strip()
                    parts = urlsplit(uri)
                    if parts.scheme == 'model' and parts.netloc in (model, source_model):
                        relative = unquote(parts.path.lstrip('/'))
                    elif not parts.scheme and not parts.netloc:
                        relative = unquote(parts.path)
                    else:
                        continue
                    if parts.query or parts.fragment or '\\' in relative:
                        continue
                    relative = posixpath.normpath(relative)
                    if relative in files and Path(relative).suffix.lower() in MODEL_FORMATS | {'.dae'}:
                        return relative
        except (ValueError, ET.ParseError):
            pass
        return None

    def _metadata(self, root, model):
        values = []
        for name in ('open-object-info.json', 'open-boat-info.json', 'marine-model-info.json', 'model-info.json'):
            value = read_json(root / name)
            if value:
                values.append(value)
        for library in ('open_objects', 'open_boats', 'marine_library', 'aerial_library'):
            value = read_json(self.unity / 'Assets/models' / library / model / 'model-info.json')
            if value:
                values.append(value)
        result = {}
        for value in reversed(values):
            result.update(value)
        return result

    def _existing(self):
        raw = read_json(self.core / 'assets/scenarios/catalogs/traffic_assets.json')
        entries = raw.get('assets', [])
        catalogue = {item['model']: item for item in entries if isinstance(item, dict) and isinstance(item.get('model'), str) and ID.fullmatch(item['model'])} if isinstance(entries, list) else {}
        if not no_symlinks(self.models) or not self.models.is_dir():
            return
        for root in sorted(self.models.iterdir()):
            model = root.name
            if root.is_symlink() or not root.is_dir() or not ID.fullmatch(model):
                continue
            # Generated simulation views have one public entry: their original
            # import receipt below, not a duplicate historical model card.
            if model.startswith('import_') and read_json(root / 'auto-import.json'):
                continue
            source = self.models / 'small_drone' if model == 'drone_racer_sim' else root
            files = self._files(source)
            geometries = [name for name in files if Path(name).suffix.lower() in MODEL_FORMATS | {'.dae'}]
            exact = 'meshes/' + ('small_drone' if model == 'drone_racer_sim' else model) + '.obj'
            entry = exact if exact in files else self._sdf_mesh_entry(root, files, model, source.name)
            entry = entry or next(iter(geometries), None)
            shapes = self._shapes(root) if entry is None else []
            if entry is None and not shapes:
                continue
            metadata = self._metadata(root, model)
            info = catalogue.get(model, {})
            preview = {'format': Path(entry).suffix[1:].lower() if entry else 'sdf', 'upAxis': 'Z',
                       'files': {name: self.file_url(model, name) for name in files}}
            notes = []
            if entry:
                preview['url'] = self.file_url(model, entry)
                if entry.lower().endswith('.obj'):
                    try:
                        with files[entry].open(encoding='utf-8-sig') as stream:
                            for _ in range(100):
                                line = stream.readline()
                                if line.startswith('mtllib '):
                                    mtl = posixpath.normpath(posixpath.join(posixpath.dirname(entry), line[7:].strip()))
                                    if mtl in files:
                                        preview['mtlUrl'] = self.file_url(model, mtl)
                                    break
                    except (OSError, UnicodeError):
                        pass
            else:
                preview['shapes'] = shapes
                notes.append('Aperçu simplifié des primitives Gazebo ; le prefab Unity détaillé peut différer.')
            licence = metadata.get('license')
            if isinstance(licence, dict):
                licence = licence.get('name') or licence.get('label')
            licence = text(licence, 250) or 'Licence média à vérifier — ne pas déduire la licence du code'
            for library in ('OpenObjects', 'OpenBoats'):
                tags = read_json(self.unity / 'ThirdParty' / library / model / 'creator-license.json')
                if 'noai' in json.dumps(tags).lower():
                    notes.append('Mention NoAI dans la provenance : usage entraînement/dataset à clarifier avant utilisation.')
            dimensions = {key: info.get(key, metadata.get(key)) for key in ('lengthM', 'beamM', 'heightM')}
            dimensions = {key: value for key, value in dimensions.items() if type(value) in (int, float) and math.isfinite(value)}
            self._roots[model] = source
            yield {'id': model, 'model': model, 'label': text(metadata.get('title') or model.replace('_', ' '), 150),
                   'category': info.get('category', 'historical'), 'domain': info.get('domain', 'unknown'),
                   'integrationStatus': 'integrated' if model in catalogue else 'available_mesh',
                   'preview': preview, 'dimensions': dimensions, 'license': licence,
                   'sourceUrl': source_url(metadata.get('source')), 'author': text(metadata.get('author'), 150),
                   'notes': ' '.join(notes), 'fileCount': len(files),
                   'bytes': sum(path.stat().st_size for path in files.values()),
                   'previewBytes': files[entry].stat().st_size if entry else 0}

    def catalog(self, force=False):
        with self.lock:
            if force or not self._updated or time.monotonic() - self._updated > 2:
                self._roots = {}
                records = list(self._existing())
                if no_symlinks(self.store) and self.store.is_dir():
                    from mesh_integration import integration_public, ready_imports
                    checked_imports = {item['importId']: item for item in ready_imports(self.core, self.unity)}
                    for root in sorted(self.store.iterdir()):
                        if root.is_symlink() or not root.is_dir() or not ID.fullmatch(root.name) or root.name.startswith('pending-'):
                            continue
                        manifest = read_json(root / 'asset.json')
                        asset = manifest.get('asset')
                        if manifest.get('schema') != 'lotusim-imported-mesh-1' or not isinstance(asset, dict) or asset.get('id') != root.name:
                            continue
                        files = self._files(root / 'files')
                        preview = asset.get('preview')
                        if not isinstance(preview, dict):
                            continue
                        entry = manifest.get('entryFile')
                        prefix = self.file_url(root.name, '')
                        if not entry and isinstance(preview.get('url'), str) and preview['url'].startswith(prefix):
                            entry = unquote(preview['url'][len(prefix):])
                        if not isinstance(entry, str) or entry not in files or Path(entry).suffix.lower() not in MODEL_FORMATS:
                            continue
                        normal_preview = {'url': self.file_url(root.name, entry),
                                          'format': Path(entry).suffix[1:].lower(),
                                          'files': {name: self.file_url(root.name, name) for name in files},
                                          'upAxis': preview.get('upAxis') if preview.get('upAxis') in ('Y', 'Z') else 'Y'}
                        material_url = preview.get('mtlUrl')
                        if isinstance(material_url, str) and material_url.startswith(prefix):
                            material = unquote(material_url[len(prefix):])
                            if material in files and material.lower().endswith('.mtl'):
                                normal_preview['mtlUrl'] = self.file_url(root.name, material)
                        # Only the checked Unity acknowledgement + generated
                        # model registry can promote an uploaded mesh.
                        integration = integration_public(self.core, self.unity, root.name)
                        ready = checked_imports.get(root.name)
                        records.append({'id': root.name, 'model': ready['model'] if ready else root.name,
                                        'label': text(asset.get('label'), 120),
                                        'category': text(asset.get('category'), 60), 'domain': ready['domain'] if ready else 'unknown',
                                        'integrationStatus': 'integrated' if ready else 'imported_pending', 'preview': normal_preview,
                                        'integration': integration,
                                        'dimensions': {key: ready[key] for key in ('lengthM', 'beamM', 'heightM') if key in ready} if ready else {},
                                        'license': text(asset.get('license'), 1000),
                                        'sourceUrl': source_url(asset.get('sourceUrl')),
                                        'notes': 'Les capacités sont déclarées, non certifiées. Échelle et droits à vérifier. ' + integration.get('message', ''),
                                        'createdAt': text(asset.get('createdAt'), 80),
                                        'fileCount': len(files), 'bytes': sum(path.stat().st_size for path in files.values()),
                                        'previewBytes': files[entry].stat().st_size})
                        self._roots[root.name] = root / 'files'
                self._records, self._updated = records, time.monotonic()
            return {'schema': 'lotusim-mesh-library-1', 'assets': self._records,
                    'limits': {'maxUploadBytes': MAX_UPLOAD, 'maxFiles': MAX_FILES,
                               'formats': ['glb', 'gltf', 'obj', 'stl']}}

    def resolve(self, model, relative):
        if not isinstance(model, str) or not ID.fullmatch(model):
            return None
        self.catalog()
        with self.lock:
            root = self._roots.get(model)
            return child(root, relative) if root else None

    def import_multipart(self, content_type, body):
        if not isinstance(body, bytes):
            raise MeshError('Corps d’import binaire requis.')
        if len(body) > MAX_UPLOAD:
            raise MeshError('Import supérieur à 64 Mio.')
        if not isinstance(content_type, str) or '\r' in content_type or '\n' in content_type or len(content_type) > 300 or not content_type.isascii():
            raise MeshError('Multipart invalide.')
        try:
            message = BytesParser(policy=policy.default).parsebytes(
                ('Content-Type: ' + content_type + '\r\nMIME-Version: 1.0\r\n\r\n').encode('ascii') + body)
        except (MessageError, ValueError, TypeError, RecursionError) as error:
            raise MeshError('Multipart invalide ou trop imbriqué.') from error
        if message.get_content_type() != 'multipart/form-data' or not message.is_multipart() or message.defects:
            raise MeshError('Choisir les fichiers dans le formulaire d’import.')
        files, metadata = {}, None
        parts = list(message.iter_parts())
        if len(parts) > MAX_FILES + 1:
            raise MeshError('Maximum 100 fichiers par import.')
        for part in parts:
            if part.is_multipart() or part.defects or part.get_content_disposition() != 'form-data':
                raise MeshError('Partie multipart invalide.')
            # The email parser unescapes quoted backslashes in filenames;
            # reject those raw headers before normalisation can hide a path.
            if any(key.lower() == 'content-disposition' and '\\' in value
                   for key, value in part.raw_items()):
                raise MeshError('Antislash interdit dans le nom de fichier.')
            value = part.get_payload(decode=True)
            if not isinstance(value, bytes):
                raise MeshError('Fichier vide ou encodage invalide.')
            if part.get_param('name', header='content-disposition') == 'metadata' and not part.get_filename():
                if metadata is not None or len(value) > 8192:
                    raise MeshError('Métadonnées invalides.')
                metadata = strict_json(value)
            elif part.get_param('name', header='content-disposition') in ('files', 'files[]'):
                name = safe_name(part.get_filename())
                if not value or len(value) > MAX_FILE or name in files or Path(name).suffix.lower() not in FILE_FORMATS:
                    raise MeshError('Fichier vide, dupliqué ou format non autorisé : ' + name)
                files[name] = value
            else:
                raise MeshError('Champ d’import non autorisé.')
        if not isinstance(metadata, dict) or not files:
            raise MeshError('Métadonnées et fichiers sont requis.')
        if not isinstance(metadata.get('name'), str) or not isinstance(metadata.get('license'), str) or not isinstance(metadata.get('category', 'other'), str):
            raise MeshError('Nom, catégorie et licence doivent être du texte.')
        name = text(metadata.get('name'), 120)
        category = text(metadata.get('category') or 'other', 60)
        licence = text(metadata.get('license'), 1000)
        if not name or not licence or any(ord(c) < 32 for c in name + licence) or not re.fullmatch(r'[a-z][a-z0-9_]{0,59}', category):
            raise MeshError('Renseigner un nom, une catégorie et une licence (ou « à préciser »).')
        up_axis = metadata.get('upAxis', 'Y')
        if up_axis not in ('Y', 'Z'):
            raise MeshError('Axe vertical Y ou Z requis.')
        integration_options = None
        if 'integrationOptions' in metadata:
            from mesh_integration import normalize_options
            integration_options = normalize_options(category, up_axis, metadata['integrationOptions'])
        entries = sorted(value for value in files if Path(value).suffix.lower() in MODEL_FORMATS)
        entry = metadata.get('entryFile') or (entries[0] if len(entries) == 1 else None)
        if entry not in entries:
            raise MeshError('Choisir un unique fichier principal GLB, glTF, OBJ ou STL.')
        try:
            validate_geometry(entry, files)
        except (ValueError, UnicodeError, TypeError, KeyError, AttributeError, RecursionError, struct.error) as error:
            if isinstance(error, MeshError):
                raise
            raise MeshError('Fichier 3D invalide ou non pris en charge.') from error
        model = 'import-' + str(uuid.uuid4())
        preview = {'url': self.file_url(model, entry), 'format': Path(entry).suffix[1:].lower(),
                   'files': {path: self.file_url(model, path) for path in files}, 'upAxis': up_axis}
        if entry.lower().endswith('.obj'):
            for line in files[entry].decode('utf-8-sig').splitlines():
                if line.startswith('mtllib '):
                    material = posixpath.normpath(posixpath.join(posixpath.dirname(entry), line[7:].strip()))
                    preview['mtlUrl'] = self.file_url(model, material)
                    break
        asset = {'id': model, 'model': model, 'label': name, 'category': category, 'domain': 'unknown',
                 'integrationStatus': 'imported_pending', 'preview': preview, 'dimensions': {},
                 'license': licence, 'sourceUrl': source_url(metadata.get('sourceUrl')),
                 'notes': 'Import local uniquement. Aucun prefab Unity, collider, réglage de flottabilité ou scénario n’a été créé. Valider l’échelle, la licence et l’intégration avant génération.',
                 'fileCount': len(files), 'bytes': sum(len(value) for value in files.values()),
                 'previewBytes': len(files[entry]), 'createdAt': datetime.now(timezone.utc).isoformat()}
        if integration_options is not None:
            asset['integrationOptions'] = integration_options
        with self.lock, self._store_directory(create=True) as directory:
            temporary = 'pending-' + str(uuid.uuid4())
            os.mkdir(temporary, mode=0o700, dir_fd=directory)
            staging = os.open(temporary, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                              dir_fd=directory)
            try:
                for relative, data in files.items():
                    self._write_file(staging, 'files/' + relative, data)
                receipt = {'schema': 'lotusim-imported-mesh-1', 'asset': asset, 'entryFile': entry,
                           'sha256': {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
                self._write_file(staging, 'asset.json', json.dumps(receipt, ensure_ascii=False, indent=2).encode('utf-8'))
                os.rename(temporary, model, src_dir_fd=directory, dst_dir_fd=directory)
            except Exception:
                self._remove_staging(directory, temporary)
                raise
            finally:
                os.close(staging)
            self._updated = 0
        return asset
