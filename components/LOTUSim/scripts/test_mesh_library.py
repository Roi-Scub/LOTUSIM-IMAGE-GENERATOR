#!/usr/bin/env python3
"""Local fixture tests: no production imports, server, converter or network."""
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
import types
import unittest
from unittest import mock


SOURCE = Path(__file__).resolve().parents[1] / 'tools/mesh_library.py'
OBJ = b'v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n'
STL = (b'solid triangle\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\n'
       b'vertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\nendsolid triangle\n')


def load_module():
    module = types.ModuleType('fixture_mesh_library')
    module.__file__ = str(SOURCE)
    exec(compile(SOURCE.read_text(encoding='utf-8'), str(SOURCE), 'exec'), module.__dict__)
    return module


def glb(document=None, binary=None):
    data = json.dumps(document or {'asset': {'version': '2.0'}}).encode('utf-8')
    data += b' ' * (-len(data) % 4)
    chunks = struct.pack('<II', len(data), 0x4E4F534A) + data
    if binary is not None:
        binary += b'\0' * (-len(binary) % 4)
        chunks += struct.pack('<II', len(binary), 0x004E4942) + binary
    return struct.pack('<4sII', b'glTF', 2, 12 + len(chunks)) + chunks


class MeshTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.temporary = tempfile.TemporaryDirectory(prefix='lotusim-mesh-test-', dir='/private/tmp')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.core = self.root / 'LOTUSim'
        self.unity = self.root / 'LOTUSim-Unity-modules'
        self.core.mkdir()
        self.unity.mkdir()
        self.library = self.module.MeshLibrary(self.core, self.unity)

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(value, bytes):
            path.write_bytes(value)
        elif isinstance(value, str):
            path.write_text(value, encoding='utf-8')
        else:
            path.write_text(json.dumps(value), encoding='utf-8')
        return path

    def model(self, name='buoy', geometry=None):
        root = self.core / 'assets/models' / name
        self.write(root / ('meshes/' + name + '.obj'), OBJ if geometry is None else geometry)
        return root

    def catalogue(self, assets):
        return self.write(self.core / 'assets/scenarios/catalogs/traffic_assets.json', {'assets': assets})

    def multipart(self, files=None, metadata=None, extra=(), include_metadata=True):
        metadata = {'name': 'Modèle local', 'license': 'CC0-1.0', 'category': 'boat'} if metadata is None else metadata
        files = [('boat.obj', OBJ)] if files is None else files
        if isinstance(files, dict):
            files = list(files.items())
        boundary = 'lotusim-fixture-boundary'
        parts = []
        if include_metadata:
            value = metadata if isinstance(metadata, bytes) else json.dumps(metadata).encode('utf-8')
            parts.append(('metadata', None, value))
        parts.extend(('files', name, value) for name, value in files)
        parts.extend(extra)
        body = bytearray()
        for field, filename, data in parts:
            body.extend(('--' + boundary + '\r\nContent-Disposition: form-data; name="' + field + '"').encode())
            if filename is not None:
                body.extend(('; filename="' + filename + '"').encode())
            body.extend(b'\r\nContent-Type: application/octet-stream\r\n\r\n')
            body.extend(data)
            body.extend(b'\r\n')
        body.extend(('--' + boundary + '--\r\n').encode())
        return 'multipart/form-data; boundary=' + boundary, bytes(body)

    def upload(self, **kwargs):
        return self.library.import_multipart(*self.multipart(**kwargs))

    def rejected(self, **kwargs):
        with self.assertRaises(self.module.MeshError):
            self.upload(**kwargs)
        if self.library.store.exists() and not self.library.store.is_symlink():
            self.assertEqual(list(self.library.store.iterdir()), [])

    def test_empty_catalogue_is_valid_and_explicit(self):
        result = self.library.catalog()
        self.assertEqual(result['schema'], 'lotusim-mesh-library-1')
        self.assertEqual(result['assets'], [])
        self.assertEqual(result['limits']['maxUploadBytes'], 64 * 1024 * 1024)

    def test_normalized_exact_obj_precedes_alphabetical_part_meshes(self):
        root = self.model('yacht')
        self.write(root / 'meshes/aaa_fin.stl', STL)
        self.catalogue([{'model': 'yacht', 'category': 'yacht', 'domain': 'surface', 'lengthM': 20}])
        asset = self.library.catalog()['assets'][0]
        self.assertEqual(asset['integrationStatus'], 'integrated')
        self.assertEqual(asset['category'], 'yacht')
        self.assertEqual(asset['dimensions'], {'lengthM': 20})
        self.assertTrue(asset['preview']['url'].endswith('/meshes/yacht.obj'))

    def test_alias_drone_reuses_normalized_small_drone_mesh(self):
        source = self.model('small_drone')
        alias = self.core / 'assets/models/drone_racer_sim'
        alias.mkdir()
        assets = {a['id']: a for a in self.library.catalog()['assets']}
        self.assertIn('drone_racer_sim', assets)
        self.assertEqual(self.library.resolve('drone_racer_sim', 'meshes/small_drone.obj'), source / 'meshes/small_drone.obj')
        self.assertIn('/drone_racer_sim/', assets['drone_racer_sim']['preview']['url'])

    def test_lrauv_primary_comes_from_sdf_collision_not_first_fin(self):
        root = self.core / 'assets/models/lrauv'
        self.write(root / 'meshes/aaa_fin.stl', STL)
        self.write(root / 'meshes/tethys.dae', b'<COLLADA/>')
        self.write(root / 'model.sdf', '<sdf><model><link><collision><geometry><mesh><uri>model://lrauv/meshes/tethys.dae</uri></mesh></geometry></collision></link></model></sdf>')
        asset = self.library.catalog()['assets'][0]
        self.assertTrue(asset['preview']['url'].endswith('/meshes/tethys.dae'))

    def test_visual_primary_precedes_collision_and_alphabetical_geometry(self):
        root = self.core / 'assets/models/old_fremm'
        self.write(root / 'meshes/a_collision.stl', STL)
        self.write(root / 'meshes/fremm.dae', b'<COLLADA/>')
        self.write(root / 'model.sdf', '<sdf><model><link><collision><geometry><mesh><uri>meshes/a_collision.stl</uri></mesh></geometry></collision><visual><geometry><mesh><uri>model://old_fremm/meshes/fremm.dae</uri></mesh></geometry></visual></link></model></sdf>')
        self.assertTrue(self.library.catalog()['assets'][0]['preview']['url'].endswith('/meshes/fremm.dae'))

    def test_sdf_unbound_gazebo_sensor_attribute_does_not_hide_primary_mesh(self):
        root = self.core / 'assets/models/lrauv'
        self.write(root / 'meshes/aaa_fin.stl', STL)
        self.write(root / 'meshes/tethys.dae', b'<COLLADA/>')
        source = self.write(root / 'model.sdf', '<sdf version="1.10"><model><link><sensor type="custom" gz:type="ais"/><collision><geometry><mesh><uri>model://lrauv/meshes/tethys.dae</uri></mesh></geometry></collision></link></model></sdf>')
        before = source.read_bytes()
        self.assertTrue(self.library.catalog()['assets'][0]['preview']['url'].endswith('/meshes/tethys.dae'))
        self.assertEqual(source.read_bytes(), before)

    def test_sdf_mesh_cannot_reference_another_model_or_remote_file(self):
        root = self.model('boat')
        self.write(root / 'model.sdf', '<sdf><visual><geometry><mesh><uri>https://evil.example/boat.obj</uri></mesh></geometry></visual></sdf>')
        files = self.library._files(root)
        self.assertIsNone(self.library._sdf_mesh_entry(root, files, 'boat', 'boat'))
        self.write(root / 'model.sdf', '<sdf><visual><geometry><mesh><uri>model://other/meshes/boat.obj</uri></mesh></geometry></visual></sdf>')
        self.assertIsNone(self.library._sdf_mesh_entry(root, files, 'boat', 'boat'))

    def test_sdf_primitives_have_finite_positive_dimensions(self):
        root = self.core / 'assets/models/marker'
        self.write(root / 'model.sdf', '<sdf><model><link><visual><pose>1 2 3 0 0 0</pose><geometry><cylinder><radius>0.5</radius><length>2</length></cylinder></geometry></visual><visual><geometry><sphere><radius>0.3</radius></sphere></geometry></visual><visual><geometry><box><size>1 2 3</size></box></geometry></visual></link></model></sdf>')
        asset = self.library.catalog()['assets'][0]
        self.assertEqual(asset['preview']['format'], 'sdf')
        self.assertEqual([s['type'] for s in asset['preview']['shapes']], ['cylinder', 'sphere', 'box'])
        self.assertIn('simplifié', asset['notes'])

    def test_invalid_sdf_values_are_omitted_not_serialized_as_nan(self):
        root = self.core / 'assets/models/marker'
        self.write(root / 'model.sdf', '<sdf><visual><geometry><sphere><radius>NaN</radius></sphere></geometry></visual><visual><geometry><box><size>1 2</size></box></geometry></visual><visual><geometry><cylinder><radius>-1</radius><length>2</length></cylinder></geometry></visual></sdf>')
        self.assertEqual(self.library._shapes(root), [])
        self.assertEqual(self.library.catalog()['assets'], [])

    def test_provenance_license_author_and_noai_are_visible(self):
        root = self.model('seagull')
        self.write(root / 'open-object-info.json', {'title': 'Oiseau réel', 'license': {'name': 'CC-BY-4.0'}, 'author': 'Créateur', 'source': 'https://example.org/model'})
        self.write(self.unity / 'ThirdParty/OpenObjects/seagull/creator-license.json', {'tags': ['NoAI']})
        asset = self.library.catalog()['assets'][0]
        self.assertEqual(asset['license'], 'CC-BY-4.0')
        self.assertEqual(asset['author'], 'Créateur')
        self.assertEqual(asset['sourceUrl'], 'https://example.org/model')
        self.assertIn('NoAI', asset['notes'])

    def test_missing_media_license_never_inherits_code_license(self):
        self.model()
        asset = self.library.catalog()['assets'][0]
        self.assertIn('vérifier', asset['license'])
        self.assertNotIn('EPL', asset['license'])
        self.assertEqual(asset['integrationStatus'], 'available_mesh')

    def test_corrupt_catalogue_and_metadata_do_not_crash(self):
        root = self.model()
        for value in ('bad json', {'assets': None}, {'assets': {'bad': 'shape'}}):
            with self.subTest(value=value):
                self.write(self.core / 'assets/scenarios/catalogs/traffic_assets.json', value)
                self.write(root / 'model-info.json', '{')
                self.assertEqual(len(self.library.catalog(force=True)['assets']), 1)

    def test_obj_material_and_local_texture_links_are_catalogued(self):
        root = self.model('boat', b'mtllib boat.mtl\n' + OBJ)
        self.write(root / 'meshes/boat.mtl', 'newmtl Paint\nmap_Kd tex.png\n')
        self.write(root / 'meshes/tex.png', b'fixture pixels')
        preview = self.library.catalog()['assets'][0]['preview']
        self.assertTrue(preview['mtlUrl'].endswith('/meshes/boat.mtl'))
        self.assertIn('meshes/tex.png', preview['files'])

    def test_file_urls_encode_spaces_without_absolute_paths(self):
        self.assertEqual(self.library.file_url('boat', 'meshes/my boat.obj'), '/api/assets/files/boat/meshes/my%20boat.obj')

    def test_unknown_models_and_unsafe_ids_do_not_resolve(self):
        for model in ('unknown', '../boat', '', None, 3, 'boat/name'):
            with self.subTest(model=model):
                self.assertIsNone(self.library.resolve(model, 'x.obj'))

    def test_child_rejects_traversal_absolute_hidden_and_backslash(self):
        root = self.model()
        for name in ('../x.obj', '/tmp/x.obj', 'meshes/../x.obj', '.hidden.obj', 'meshes//buoy.obj', 'meshes\\buoy.obj', 'x\0.obj'):
            with self.subTest(name=name):
                self.assertIsNone(self.module.child(root, name))

    def test_child_rejects_root_parent_and_leaf_symlinks(self):
        real = self.model()
        linked = self.root / 'linked'
        linked.symlink_to(real, target_is_directory=True)
        self.assertIsNone(self.module.child(linked, 'meshes/buoy.obj'))
        (real / 'meshes/link.obj').symlink_to(real / 'meshes/buoy.obj')
        self.assertIsNone(self.module.child(real, 'meshes/link.obj'))
        nested = self.root / 'nested'
        nested.mkdir()
        (nested / 'meshes').symlink_to(real / 'meshes', target_is_directory=True)
        self.assertIsNone(self.module.child(nested, 'meshes/buoy.obj'))

    def test_symlinked_existing_model_and_drone_alias_never_escape(self):
        outside = self.root / 'outside'
        self.write(outside / 'meshes/small_drone.obj', OBJ)
        models = self.core / 'assets/models'
        models.mkdir(parents=True)
        (models / 'small_drone').symlink_to(outside, target_is_directory=True)
        (models / 'drone_racer_sim').mkdir()
        self.assertEqual(self.library.catalog()['assets'], [])

    def test_bounded_regular_reads_ignore_fifos_directories_and_oversize(self):
        path = self.write(self.root / 'value.json', b'{}')
        self.assertEqual(self.module.read_json(path), {})
        os.mkfifo(self.root / 'fifo.json')
        self.assertIsNone(self.module.regular_bytes(self.root / 'fifo.json', 100))
        self.assertIsNone(self.module.regular_bytes(self.root, 100))
        self.assertIsNone(self.module.regular_bytes(path, 1))

    def test_json_reads_do_not_follow_symlinked_parent_or_leaf(self):
        real = self.write(self.root / 'real/value.json', {'secret': 1})
        link = self.root / 'alias'
        link.symlink_to(real.parent, target_is_directory=True)
        self.assertEqual(self.module.read_json(link / real.name), {})
        leaf = self.root / 'leaf.json'
        leaf.symlink_to(real)
        self.assertEqual(self.module.read_json(leaf), {})

    def test_strict_json_rejects_nonfinite_overflow_duplicate_and_depth(self):
        values = (b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e9999}', b'{"x":1,"x":2}', ('[' * 80 + '0' + ']' * 80).encode())
        for value in values:
            with self.subTest(value=value), self.assertRaises(self.module.MeshError):
                self.module.strict_json(value)

    def test_metadata_read_is_bounded_and_malformed_json_returns_empty(self):
        for value in (b'{' , b'[]', b'{"x":NaN}', b'x' * (2 * 1024 * 1024 + 1)):
            path = self.write(self.root / 'bad.json', value)
            self.assertEqual(self.module.read_json(path), {})

    def test_import_obj_publishes_pending_asset_and_hash_receipt(self):
        asset = self.upload()
        self.assertEqual(asset['integrationStatus'], 'imported_pending')
        self.assertEqual(asset['domain'], 'unknown')
        receipt = self.module.read_json(self.library.store / asset['id'] / 'asset.json')
        self.assertEqual(receipt['sha256']['boat.obj'], hashlib.sha256(OBJ).hexdigest())
        self.assertEqual(receipt['entryFile'], 'boat.obj')
        self.assertEqual(self.library.resolve(asset['id'], 'boat.obj').read_bytes(), OBJ)
        self.assertFalse(any(path.name.startswith('pending-') for path in self.library.store.iterdir()))

    def test_import_glb_with_valid_chunks(self):
        asset = self.upload(files={'boat.glb': glb(binary=b'1234')})
        self.assertEqual(asset['preview']['format'], 'glb')
        self.assertEqual(asset['preview']['upAxis'], 'Y')

    def test_import_ascii_stl(self):
        self.assertEqual(self.upload(files={'boat.stl': STL})['preview']['format'], 'stl')

    def test_import_binary_stl(self):
        data = b'binary fixture'.ljust(80, b'\0') + struct.pack('<I12fH', 1, *([0.0] * 12), 0)
        self.assertEqual(self.upload(files={'boat.stl': data})['preview']['format'], 'stl')

    def test_import_multifile_gltf_local_buffers_and_images(self):
        doc = {'asset': {'version': '2.0'}, 'buffers': [{'uri': '../data/mesh.bin', 'byteLength': 4}], 'images': [{'uri': 'texture%20one.png'}], 'accessors': [{'count': 3}]}
        files = {'models/boat.gltf': json.dumps(doc).encode(), 'data/mesh.bin': b'1234', 'models/texture one.png': b'PNG fixture'}
        asset = self.upload(files=files)
        self.assertEqual(asset['fileCount'], 3)
        self.assertEqual(set(asset['preview']['files']), set(files))

    def test_import_obj_mtl_and_texture_keeps_relative_resources(self):
        files = {'meshes/boat.obj': b'mtllib boat.mtl\n' + OBJ,
                 'meshes/boat.mtl': b'newmtl Paint\nmap_Kd ../textures/a.png\n',
                 'textures/a.png': b'pixels'}
        asset = self.upload(files=files)
        self.assertTrue(asset['preview']['mtlUrl'].endswith('/meshes/boat.mtl'))

    def test_embedded_gltf_data_is_accepted_but_not_executed(self):
        uri = 'data:application/octet-stream;base64,' + base64.b64encode(b'1234').decode()
        doc = {'asset': {'version': '2.0'}, 'buffers': [{'uri': uri, 'byteLength': 4}]}
        self.assertEqual(self.upload(files={'x.gltf': json.dumps(doc).encode()})['preview']['format'], 'gltf')

    def test_malformed_gltf_object_shapes_all_raise_mesherror(self):
        cases = ({'asset': None}, {'asset': []}, {'asset': '2.0'},
                 {'asset': {'version': '2.0'}, 'accessors': [None]},
                 {'asset': {'version': '2.0'}, 'buffers': 'bad'},
                 {'asset': {'version': '2.0'}, 'images': [12]},
                 {'asset': {'version': '2.0'}, 'extensionsRequired': [None]},
                 {'asset': {'version': '2.0'}, 'extensionsRequired': {}})
        for doc in cases:
            with self.subTest(doc=doc):
                self.rejected(files={'x.gltf': json.dumps(doc).encode()})

    def test_gltf_accessor_limits_and_nonfinite_values_rejected(self):
        for value in (-1, 10000001, 2.2, True, '10'):
            doc = {'asset': {'version': '2.0'}, 'accessors': [{'count': value}]}
            with self.subTest(value=value):
                self.rejected(files={'x.gltf': json.dumps(doc).encode()})
        self.rejected(files={'x.gltf': b'{"asset":{"version":"2.0"},"nodes":[{"translation":[NaN,0,0]}]}'})

    def test_gltf_compressed_required_extensions_are_rejected(self):
        for extension in ('KHR_draco_mesh_compression', 'EXT_meshopt_compression', 'KHR_texture_basisu'):
            doc = {'asset': {'version': '2.0'}, 'extensionsRequired': [extension]}
            with self.subTest(extension=extension):
                self.rejected(files={'x.gltf': json.dumps(doc).encode()})

    def test_gltf_remote_absolute_escape_and_missing_resources_rejected(self):
        for uri in ('https://evil.example/x.bin', '//evil.example/x.bin', 'file:///tmp/x.bin',
                    '/tmp/x.bin', '../x.bin', '%2e%2e/x.bin', 'x.bin?query=1', 'x.bin#fragment', 'missing.bin'):
            doc = {'asset': {'version': '2.0'}, 'buffers': [{'uri': uri}]}
            with self.subTest(uri=uri):
                self.rejected(files={'x.gltf': json.dumps(doc).encode()})

    def test_embedded_script_mime_invalid_base64_and_empty_payload_rejected(self):
        for uri in ('data:text/html;base64,PHNjcmlwdD4=', 'data:image/svg+xml;base64,PHN2Zz4=',
                    'data:image/png;base64,!!!', 'data:application/octet-stream;base64,'):
            doc = {'asset': {'version': '2.0'}, 'images': [{'uri': uri}]}
            with self.subTest(uri=uri):
                self.rejected(files={'x.gltf': json.dumps(doc).encode()})

    def test_glb_invalid_header_and_truncated_or_duplicate_chunks_rejected(self):
        good = glb()
        bad_json = b'not json'.ljust(8, b' ')
        duplicate = good[12:] + good[12:]
        cases = (b'x', b'NOPE' + good[4:], good[:4] + struct.pack('<I', 1) + good[8:],
                 good[:-1], struct.pack('<4sII', b'glTF', 2, 28) + struct.pack('<II', 8, 0x4E4F534A) + bad_json,
                 struct.pack('<4sII', b'glTF', 2, 12 + len(duplicate)) + duplicate,
                 good + b'junk')
        for data in cases:
            with self.subTest(data=data[:20]):
                self.rejected(files={'x.glb': data})

    def test_corrupt_gltf_json_is_not_an_unhandled_exception(self):
        for value in (b'{', b'null', b'[]', b'"text"', b'\xff', b'{"asset":{"version":"1.0"}}'):
            with self.subTest(value=value):
                self.rejected(files={'x.gltf': value})

    def test_obj_accepts_whitespace_and_valid_negative_indices(self):
        data = b' v\t0 0 0\n v\t1 0 0\n v\t0 1 0\n f\t-3 -2 -1\n'
        self.assertEqual(self.upload(files={'x.obj': data})['preview']['format'], 'obj')

    def test_obj_nonfinite_coordinates_and_invalid_faces_rejected(self):
        for value in (b'NaN', b'Infinity', b'1e9999', b'10000000000', b'notnumber'):
            with self.subTest(value=value):
                self.rejected(files={'x.obj': OBJ.replace(b'v 0 0 0', b'v ' + value + b' 0 0', 1)})
        for face in (b'f 1 2', b'f 0 1 2', b'f 1 2 99', b'f 1 2 hello'):
            with self.subTest(face=face):
                self.rejected(files={'x.obj': OBJ.replace(b'f 1 2 3', face)})

    def test_obj_missing_vertices_faces_and_nul_are_rejected(self):
        for data in (b'v 0 0 0\n', b'f 1 2 3\n', OBJ + b'\0', b'not a model'):
            with self.subTest(data=data):
                self.rejected(files={'x.obj': data})

    def test_stl_nonfinite_vertices_and_invalid_data_rejected(self):
        binary = b'fixture'.ljust(80, b'\0') + struct.pack('<I12fH', 1, float('nan'), *([0.0] * 11), 0)
        for data in (b'no mesh', STL.replace(b'vertex 0 0 0', b'vertex inf 0 0'), binary):
            with self.subTest(data=data[:30]):
                self.rejected(files={'x.stl': data})

    def test_mtl_remote_texture_or_unsupported_options_are_rejected(self):
        for texture in (b'https://evil.example/x.png', b'../../x.png', b'-s 1 1 1 x.png', b'missing.png'):
            with self.subTest(texture=texture):
                self.rejected(files={'x.obj': b'mtllib x.mtl\n' + OBJ, 'x.mtl': b'map_Kd ' + texture + b'\n'})

    def test_disallowed_import_formats_and_filename_paths_are_rejected(self):
        for name in ('run.py', 'run.sh', 'x.fbx', 'x.zip', 'x.svg', 'x.html', 'x.dae',
                     '../x.obj', '/tmp/x.obj', '.hidden.obj', 'meshes/../x.obj', 'x\\y.obj', 'x%2f.obj'):
            with self.subTest(name=name):
                self.rejected(files={name: OBJ})

    def test_empty_duplicate_files_and_missing_geometry_are_rejected(self):
        self.rejected(files={'x.obj': b''})
        self.rejected(files=[('x.obj', OBJ), ('x.obj', OBJ)])
        self.rejected(files={'x.png': b'pixels'})

    def test_missing_or_duplicate_metadata_and_unknown_form_fields_rejected(self):
        self.rejected(include_metadata=False)
        self.rejected(extra=[('metadata', None, b'{}')])
        self.rejected(extra=[('execute', None, b'no')])

    def test_corrupt_metadata_json_duplicate_keys_and_wrong_type_rejected(self):
        for value in (b'{', b'null', b'[]', b'{"name":"a","name":"b"}', b'{"name":NaN}'):
            with self.subTest(value=value):
                self.rejected(metadata=value)

    def test_required_metadata_fields_and_control_characters_rejected(self):
        for metadata in ({}, {'name': 'A'}, {'name': 'A', 'license': ''},
                         {'name': ['A'], 'license': 'CC0'}, {'name': 'A\nB', 'license': 'CC0'},
                         {'name': 'A', 'license': 'CC0', 'category': 'BOAT'},
                         {'name': 'A', 'license': 'CC0', 'upAxis': 'X'}):
            with self.subTest(metadata=metadata):
                self.rejected(metadata=metadata)

    def test_multiple_model_entries_require_explicit_entry_file(self):
        files = {'a.obj': OBJ, 'b.stl': STL}
        self.rejected(files=files)
        asset = self.upload(files=files, metadata={'name': 'A', 'license': 'à préciser', 'entryFile': 'b.stl', 'upAxis': 'Z'})
        self.assertEqual(asset['preview']['format'], 'stl')
        self.assertEqual(asset['preview']['upAxis'], 'Z')

    def test_body_file_and_part_limits_are_enforced_before_storage(self):
        with mock.patch.object(self.module, 'MAX_UPLOAD', 100):
            self.rejected()
        with mock.patch.object(self.module, 'MAX_FILE', 10):
            self.rejected()
        with mock.patch.object(self.module, 'MAX_FILES', 1):
            self.rejected(files={'a.obj': OBJ, 'texture.png': b'pixels'})
        self.rejected(metadata={'name': 'A', 'license': 'L' * 8200})

    def test_content_type_injection_nonascii_and_malformed_multipart_rejected(self):
        _, body = self.multipart()
        for content_type in ('application/json', 'multipart/form-data', 'x\r\nX-Test: yep', 'multipart/é', None):
            with self.subTest(content_type=content_type), self.assertRaises(self.module.MeshError):
                self.library.import_multipart(content_type, body)
        with self.assertRaises(self.module.MeshError):
            self.library.import_multipart('multipart/form-data; boundary=x', b'--x\r\n')

    def test_nonbytes_body_is_rejected(self):
        for body in (None, 'text', 42):
            with self.subTest(body=body), self.assertRaises(self.module.MeshError):
                self.library.import_multipart('multipart/form-data; boundary=x', body)

    def test_mime_parser_depth_failure_is_normalized_to_mesherror(self):
        request = self.multipart()
        with mock.patch.object(self.module.BytesParser, 'parsebytes', side_effect=RecursionError('fixture nested MIME')):
            with self.assertRaises(self.module.MeshError):
                self.library.import_multipart(*request)

    def test_source_url_is_provenance_only_and_has_no_credentials_or_script(self):
        for value in ('javascript:alert(1)', 'file:///tmp/x', 'http://example.org', 'https://user:pass@example.org/x',
                      'https://example.org/\nsecret', 'https://example.org:999999/x'):
            with self.subTest(value=value):
                self.assertEqual(self.module.source_url(value), '')
        self.assertEqual(self.module.source_url('https://example.org/x'), 'https://example.org/x')

    def test_symlinked_store_parent_rejected_without_creating_outside_directories(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (self.core / 'artifacts').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(self.module.MeshError):
            self.upload()
        self.assertEqual(list(outside.iterdir()), [])

    def test_symlinked_imports_leaf_is_rejected(self):
        parent = self.core / 'artifacts/mesh-library'
        parent.mkdir(parents=True)
        outside = self.root / 'outside'
        outside.mkdir()
        self.library.store.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(self.module.MeshError):
            self.upload()
        self.assertEqual(list(outside.iterdir()), [])

    def test_partial_write_cleanup_removes_only_own_unpublished_staging(self):
        original = self.library._write_file
        calls = [0]
        def fail_second(*args):
            calls[0] += 1
            if calls[0] == 2:
                raise OSError('fixture disk write failure')
            return original(*args)
        with mock.patch.object(self.library, '_write_file', side_effect=fail_second):
            with self.assertRaises(self.module.MeshError):
                self.upload()
        self.assertEqual(list(self.library.store.iterdir()), [])

    def test_pending_or_corrupt_receipts_are_not_published_in_catalogue(self):
        self.write(self.library.store / 'pending-fixture/asset.json', {'schema': 'lotusim-imported-mesh-1', 'asset': {}})
        self.write(self.library.store / 'broken/asset.json', {'schema': 'lotusim-imported-mesh-1', 'asset': None})
        self.assertEqual(self.library.catalog()['assets'], [])

    def test_manifest_edits_cannot_promote_import_or_publish_remote_preview(self):
        asset = self.upload()
        receipt_file = self.library.store / asset['id'] / 'asset.json'
        receipt = self.module.read_json(receipt_file)
        receipt['asset']['integrationStatus'] = 'integrated'
        receipt['asset']['preview']['url'] = 'https://evil.example/x.obj'
        receipt['asset']['preview']['files'] = {'secrets': 'file:///etc/passwd'}
        self.write(receipt_file, receipt)
        result = self.library.catalog(force=True)['assets'][0]
        self.assertEqual(result['integrationStatus'], 'imported_pending')
        self.assertTrue(result['preview']['url'].startswith('/api/assets/files/'))
        self.assertNotIn('secrets', result['preview']['files'])

    def test_symlinked_uploaded_file_root_cannot_expose_outside(self):
        asset = self.upload()
        files = self.library.store / asset['id'] / 'files'
        (files / 'boat.obj').unlink()
        files.rmdir()
        outside = self.root / 'outside'
        self.write(outside / 'boat.obj', OBJ)
        files.symlink_to(outside, target_is_directory=True)
        self.assertEqual(self.library.catalog(force=True)['assets'], [])
        self.assertIsNone(self.library.resolve(asset['id'], 'boat.obj'))

    def test_uploads_never_run_converters_open_network_or_edit_scenes(self):
        original = self.write(self.unity / 'Assets/Scenes/unchanged.unity', 'original scene')
        with mock.patch('subprocess.run', side_effect=AssertionError('no external commands')), \
                mock.patch('subprocess.Popen', side_effect=AssertionError('no converter')), \
                mock.patch('socket.socket', side_effect=AssertionError('no network')):
            asset = self.upload(files={'model.obj': b'# __import__("os").system("no")\n' + OBJ})
            self.library.catalog(force=True)
        self.assertEqual(asset['integrationStatus'], 'imported_pending')
        self.assertEqual(original.read_text(), 'original scene')
        self.assertFalse((self.core / 'assets/models').exists())

    def test_parallel_imports_have_distinct_receipts_and_invalidate_cache(self):
        self.library.catalog()
        request = self.multipart()
        with ThreadPoolExecutor(max_workers=3) as pool:
            assets = list(pool.map(lambda _: self.library.import_multipart(*request), range(3)))
        self.assertEqual(len({asset['id'] for asset in assets}), 3)
        self.assertEqual(len(self.library.catalog()['assets']), 3)
        self.assertTrue(all(asset['integrationStatus'] == 'imported_pending' for asset in assets))


if __name__ == '__main__':
    unittest.main()
