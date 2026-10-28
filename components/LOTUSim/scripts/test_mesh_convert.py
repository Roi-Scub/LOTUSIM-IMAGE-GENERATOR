import base64
import copy
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import mesh_convert as m
import numpy as np
from PIL import Image

OBJ = b'v 0 0 0\nv 2 0 0\nv 0 0 2\nf 1 2 3\n'


def png():
    buffer = io.BytesIO(); Image.new('RGBA', (2, 2), (200, 50, 25, 255)).save(buffer, 'PNG')
    return buffer.getvalue()


def gltf_fixture():
    positions = np.asarray([[0, 0, 0], [2, 0, 0], [0, 2, 0]], dtype='<f4').tobytes()
    indices = np.asarray([0, 1, 2], dtype='<u2').tobytes()
    uv = np.asarray([[0, 0], [1, 0], [0, 1]], dtype='<f4').tobytes()
    binary = positions + indices + b'\0\0' + uv
    doc = {'asset': {'version': '2.0'}, 'scene': 0, 'scenes': [{'nodes': [0]}],
           'nodes': [{'mesh': 0}], 'meshes': [{'primitives': [{'attributes': {'POSITION': 0, 'TEXCOORD_0': 2}, 'indices': 1}]}],
           'buffers': [{'uri': 'mesh.bin', 'byteLength': len(binary)}],
           'bufferViews': [{'buffer': 0, 'byteOffset': 0, 'byteLength': len(positions)},
                           {'buffer': 0, 'byteOffset': len(positions), 'byteLength': len(indices)},
                           {'buffer': 0, 'byteOffset': len(positions) + len(indices) + 2, 'byteLength': len(uv)}],
           'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': 3, 'type': 'VEC3'},
                         {'bufferView': 1, 'componentType': 5123, 'count': 3, 'type': 'SCALAR'},
                         {'bufferView': 2, 'componentType': 5126, 'count': 3, 'type': 'VEC2'}]}
    return doc, binary


def pack_glb(doc, binary):
    doc = copy.deepcopy(doc); doc['buffers'][0].pop('uri', None)
    encoded = json.dumps(doc).encode(); encoded += b' ' * (-len(encoded) % 4)
    binary += b'\0' * (-len(binary) % 4)
    total = 12 + 8 + len(encoded) + 8 + len(binary)
    return struct.pack('<III', 0x46546C67, 2, total) + struct.pack('<II', len(encoded), 0x4E4F534A) + encoded + struct.pack('<II', len(binary), 0x004E4942) + binary


def bundle(path):
    data = (path / 'geometry.bytes').read_bytes()
    magic, batches = struct.unpack_from('<II', data); offset = 8; result = []
    assert magic == 0x4C424D31
    for _ in range(batches):
        material, vertices, indices = struct.unpack_from('<III', data, offset); offset += 12
        points = np.frombuffer(data, dtype='<f4', count=vertices * 8, offset=offset).reshape(-1, 8); offset += vertices * 32
        faces = np.frombuffer(data, dtype='<i4', count=indices, offset=offset).reshape(-1, 3); offset += indices * 4
        result.append((material, points, faces))
    assert offset == len(data)
    return result


class ConverterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir='/private/tmp')
        self.root = Path(self.temp.name).resolve()
        self.output = self.root / 'output'
        self.metadata = dict(model='import_test', category='buoy', label='Original test mesh',
                             license='CC0', sourceUrl='https://example.org/source',
                             upAxis='Z', forwardAxis='+X', metresPerUnit=1, domain='moored')

    def tearDown(self):
        self.temp.cleanup()

    def convert(self, data=OBJ, suffix='.obj', extra=None, metadata=None):
        files = {'mesh' + suffix: data}; files.update(extra or {})
        return m.convert('mesh' + suffix, files, metadata or self.metadata, self.output)

    def gltf(self, doc=None, binary=None, glb=False, metadata=None):
        base, buffer = gltf_fixture(); doc = doc or base; binary = binary if binary is not None else buffer
        meta = dict(self.metadata, upAxis='Y', forwardAxis='+Z', domain='air')
        meta.update(metadata or {})
        if glb:
            return self.convert(pack_glb(doc, binary), '.glb', metadata=meta)
        return self.convert(json.dumps(doc).encode(), '.gltf', {'mesh.bin': binary}, meta)

    def rejected(self, function):
        with self.assertRaises(m.MeshConvertError):
            function()
        self.assertFalse(self.output.exists(), 'Invalid models must not create a partial bundle')

    def test_obj_bundle_contract_and_finite_normals(self):
        info = self.convert()
        self.assertEqual(info['key'], 'import_test'); self.assertEqual(info['license'], 'CC0')
        self.assertEqual(info['triangles'], 1); self.assertEqual(info['materialBatches'], 1)
        material, vertices, triangles = bundle(self.output)[0]
        self.assertEqual(vertices.shape, (3, 8)); self.assertEqual(material, 0)
        self.assertTrue(np.isfinite(vertices).all())
        self.assertTrue(np.allclose(np.linalg.norm(vertices[:, 3:6], axis=1), 1))
        normal = np.cross(vertices[triangles[0, 1], :3] - vertices[triangles[0, 0], :3], vertices[triangles[0, 2], :3] - vertices[triangles[0, 0], :3])
        self.assertGreater(np.dot(normal, vertices[triangles[0, 0], 3:6]), 0)
        stored = json.loads((self.output / 'model-info.json').read_text())
        self.assertEqual(stored, info)

    def test_gazebo_uses_same_geometry_with_z_up_and_reversed_winding(self):
        info = self.convert()
        vertices = bundle(self.output)[0][1]
        source = (self.output / info['gazeboObj']).read_text()
        points = np.asarray([[float(x) for x in line.split()[1:]] for line in source.splitlines() if line.startswith('v ')])
        np.testing.assert_allclose(points, vertices[:, [0, 2, 1]])
        face = next(line for line in source.splitlines() if line.startswith('f '))
        indices = [int(value.split('/')[0]) - 1 for value in face.split()[1:]]
        unity_faces = bundle(self.output)[0][2][0]
        self.assertEqual(indices, unity_faces[[0, 2, 1]].tolist())
        self.assertIn('mtllib gazebo.mtl', source)

    def test_gazebo_material_uses_local_texture(self):
        doc, binary = gltf_fixture(); doc['materials'] = [{'pbrMetallicRoughness': {'baseColorTexture': {'index': 0}}}]
        doc['textures'] = [{'source': 0}]; doc['images'] = [{'uri': 'data:image/png;base64,' + base64.b64encode(png()).decode()}]
        info = self.gltf(doc, binary)
        material = (self.output / info['gazeboMtl']).read_text()
        self.assertIn('map_Kd ' + info['materials'][0]['baseMap'], material)

    def test_user_scale_and_waterline_draft(self):
        info = self.convert(metadata=dict(self.metadata, metresPerUnit=.5, draftM=.25))
        self.assertAlmostEqual(info['lengthM'], 1); self.assertAlmostEqual(info['heightM'], 1)
        self.assertAlmostEqual(info['boundsMin'][1], -.25)

    def test_air_mesh_centred(self):
        info = self.convert(metadata=dict(self.metadata, domain='air'))
        self.assertAlmostEqual(info['boundsMin'][1], -1)
        self.assertAlmostEqual(info['boundsMax'][1], 1)

    def test_zero_thickness_is_explicit_bounding_proxy(self):
        info = self.convert()
        self.assertEqual(info['beamM'], .001)
        self.assertTrue(any('1 mm' in item for item in info['changes']))

    def test_quad_negative_indices_and_tabs(self):
        source = b'v\t0 0 0\nv 1 0 0\nv 1 0 1\nv 0 0 1\nf -4 -3 -2 -1\n'
        self.assertEqual(self.convert(source)['triangles'], 2)

    def test_obj_texture_and_mtl_color(self):
        source = b'mtllib material.mtl\nv 0 0 0\nv 1 0 0\nv 0 0 1\nvt 0 0\nvt 1 0\nvt 0 1\nusemtl paint\nf 1/1 2/2 3/3\n'
        info = self.convert(source, extra={'material.mtl': b'newmtl paint\nKd .8 .1 .2\nmap_Kd texture.png\n', 'texture.png': png()})
        self.assertEqual(info['materials'][1]['color'], [.8, .1, .2, 1])
        self.assertTrue((self.output / info['materials'][1]['baseMap']).is_file())

    def test_obj_trailing_comments_are_accepted(self):
        source = b'v 0 0 0 # origin\nv 1 0 0 # tip\nv 0 0 1\nf 1 2 3 # surface\n'
        self.assertEqual(self.convert(source)['triangles'], 1)

    def test_obj_nested_texture_resource(self):
        source = b'mtllib materials/a.mtl\nv 0 0 0\nv 1 0 0\nv 0 0 1\nusemtl paint\nf 1 2 3\n'
        info = self.convert(source, extra={'materials/a.mtl': b'newmtl paint\nmap_Kd ../textures/a.png\n', 'textures/a.png': png()})
        self.assertTrue(info['materials'][1]['baseMap'])

    def test_obj_missing_texture_rejected(self):
        source = b'mtllib a.mtl\n' + OBJ
        self.rejected(lambda: self.convert(source, extra={'a.mtl': b'newmtl paint\nmap_Kd missing.png\n'}))

    def test_obj_remote_texture_rejected(self):
        source = b'mtllib a.mtl\n' + OBJ
        self.rejected(lambda: self.convert(source, extra={'a.mtl': b'newmtl paint\nmap_Kd https://example.org/private.png\n'}))

    def test_obj_bump_map_not_misidentified_as_normal_map(self):
        source = b'mtllib a.mtl\n' + OBJ
        self.rejected(lambda: self.convert(source, extra={'a.mtl': b'newmtl paint\nbump t.png\n', 't.png': png()}))

    def test_invalid_obj_index_rejected(self):
        self.rejected(lambda: self.convert(OBJ.replace(b'1 2 3', b'0 2 3')))

    def test_nonfinite_obj_rejected(self):
        self.rejected(lambda: self.convert(OBJ.replace(b'v 2', b'v nan')))

    def test_obj_vertex_color_not_silently_lost(self):
        self.rejected(lambda: self.convert(OBJ.replace(b'v 2 0 0', b'v 2 0 0 1 0 0')))

    def test_obj_curve_not_silently_lost(self):
        self.rejected(lambda: self.convert(OBJ + b'l 1 2\n'))

    def test_unknown_material_rejected(self):
        self.rejected(lambda: self.convert(b'usemtl missing\n' + OBJ))

    def test_parallel_axes_rejected(self):
        self.rejected(lambda: self.convert(metadata=dict(self.metadata, forwardAxis='+Z')))

    def test_nonfinite_scale_rejected(self):
        self.rejected(lambda: self.convert(metadata=dict(self.metadata, metresPerUnit=float('nan'))))

    def test_draft_greater_than_height_rejected(self):
        self.rejected(lambda: self.convert(metadata=dict(self.metadata, draftM=3)))

    def test_output_existing_user_file_preserved(self):
        self.output.mkdir(); (self.output / 'user.txt').write_text('keep')
        with self.assertRaises(m.MeshConvertError):
            self.convert()
        self.assertEqual((self.output / 'user.txt').read_text(), 'keep')

    def test_output_symlink_rejected(self):
        target = self.root / 'other'; target.mkdir(); self.output.symlink_to(target)
        with self.assertRaises(m.MeshConvertError):
            self.convert()
        self.assertEqual(list(target.iterdir()), [])

    def test_source_path_traversal_rejected(self):
        self.rejected(lambda: m.convert('../mesh.obj', {'../mesh.obj': OBJ}, self.metadata, self.output))

    def test_binary_stl(self):
        data = b'Original QA STL'.ljust(80, b' ') + struct.pack('<I12fH', 1, 0, 0, 0, 0, 0, 0, 2, 0, 0, 0, 0, 2, 0)
        self.assertEqual(self.convert(data, '.stl')['triangles'], 1)

    def test_ascii_stl(self):
        data = b'solid qa\nfacet normal 0 0 0\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 0 1\nendloop\nendfacet\nendsolid qa\n'
        self.assertEqual(self.convert(data, '.stl')['triangles'], 1)

    def test_degenerate_stl_rejected(self):
        data = b'solid qa\nfacet normal 0 0 0\nvertex 0 0 0\nvertex 0 0 0\nvertex 0 0 0\nendsolid qa\n'
        self.rejected(lambda: self.convert(data, '.stl'))

    def test_external_gltf_buffers(self):
        self.assertEqual(self.gltf()['triangles'], 1)

    def test_glb_embedded_geometry(self):
        self.assertEqual(self.gltf(glb=True)['triangles'], 1)

    def test_gltf_missing_normals_are_generated(self):
        self.gltf(); vertices = bundle(self.output)[0][1]
        self.assertTrue(np.isfinite(vertices[:, 3:6]).all())

    def test_gltf_node_transform_affects_actual_dimensions(self):
        doc, binary = gltf_fixture(); doc['nodes'][0]['scale'] = [2, 3, 1]
        info = self.gltf(doc, binary)
        self.assertEqual(info['heightM'], 6); self.assertEqual(info['beamM'], 4)

    def test_gltf_negative_node_scale_winding(self):
        doc, binary = gltf_fixture(); doc['nodes'][0]['scale'] = [-1, 1, 1]
        self.gltf(doc, binary); _, vertices, triangles = bundle(self.output)[0]
        cross = np.cross(vertices[triangles[0, 1], :3] - vertices[triangles[0, 0], :3], vertices[triangles[0, 2], :3] - vertices[triangles[0, 0], :3])
        self.assertGreater(np.dot(cross, vertices[triangles[0, 0], 3:6]), 0)

    def test_gltf_data_uri_buffer(self):
        doc, binary = gltf_fixture(); doc['buffers'][0]['uri'] = 'data:application/octet-stream;base64,' + base64.b64encode(binary).decode()
        self.assertEqual(self.gltf(doc, binary)['triangles'], 1)

    def test_gltf_embedded_texture(self):
        doc, binary = gltf_fixture()
        doc['materials'] = [{'pbrMetallicRoughness': {'baseColorTexture': {'index': 0}, 'metallicFactor': .2}}]
        doc['textures'] = [{'source': 0}]; doc['images'] = [{'uri': 'data:image/png;base64,' + base64.b64encode(png()).decode()}]
        info = self.gltf(doc, binary)
        self.assertTrue((self.output / info['materials'][0]['baseMap']).is_file())
        self.assertEqual(info['materials'][0]['metallic'], .2)

    def test_textured_gltf_without_uv_is_rejected(self):
        doc, binary = gltf_fixture(); doc['meshes'][0]['primitives'][0]['attributes'].pop('TEXCOORD_0')
        doc['materials'] = [{'pbrMetallicRoughness': {'baseColorTexture': {'index': 0}}}]
        doc['textures'] = [{'source': 0}]; doc['images'] = [{'uri': 'data:image/png;base64,' + base64.b64encode(png()).decode()}]
        self.rejected(lambda: self.gltf(doc, binary))

    def test_malformed_optional_collection_is_rejected(self):
        doc, binary = gltf_fixture(); doc['animations'] = {}
        self.rejected(lambda: self.gltf(doc, binary))

    def test_gltf_remote_buffers_rejected(self):
        doc, binary = gltf_fixture(); doc['buffers'][0]['uri'] = 'https://example.org/data.bin'
        self.rejected(lambda: self.gltf(doc, binary))

    def test_gltf_animations_rejected(self):
        doc, binary = gltf_fixture(); doc['animations'] = [{}]
        self.rejected(lambda: self.gltf(doc, binary))

    def test_gltf_skin_rejected(self):
        doc, binary = gltf_fixture(); doc['skins'] = [{}]
        self.rejected(lambda: self.gltf(doc, binary))

    def test_gltf_morph_rejected(self):
        doc, binary = gltf_fixture(); doc['meshes'][0]['primitives'][0]['targets'] = [{}]
        self.rejected(lambda: self.gltf(doc, binary))

    def test_gltf_compression_rejected(self):
        doc, binary = gltf_fixture(); doc['extensionsRequired'] = ['KHR_draco_mesh_compression']
        self.rejected(lambda: self.gltf(doc, binary))

    def test_gltf_accessor_bounds_rejected(self):
        doc, binary = gltf_fixture(); doc['accessors'][0]['count'] = 4
        self.rejected(lambda: self.gltf(doc, binary))

    def test_gltf_indices_type_rejected(self):
        doc, binary = gltf_fixture(); doc['accessors'][1]['componentType'] = 5126
        self.rejected(lambda: self.gltf(doc, binary))

    def test_gltf_node_cycle_rejected(self):
        doc, binary = gltf_fixture(); doc['nodes'][0]['children'] = [0]
        self.rejected(lambda: self.gltf(doc, binary))

    def test_gltf_unknown_required_extension_rejected(self):
        doc, binary = gltf_fixture(); doc['extensionsRequired'] = ['CUSTOM_execute_something']
        self.rejected(lambda: self.gltf(doc, binary))

    def test_gltf_z_up_override_rejected(self):
        self.rejected(lambda: self.gltf(metadata={'upAxis': 'Z', 'forwardAxis': '+X'}))

    def test_malformed_glb_rejected(self):
        self.rejected(lambda: self.convert(b'glTF' + b'\0' * 50, '.glb'))

    def test_duplicate_json_keys_rejected(self):
        self.rejected(lambda: self.convert(b'{"asset":{"version":"2.0"},"asset":{}}', '.gltf', metadata=dict(self.metadata, upAxis='Y', forwardAxis='+Z')))

    def test_metadata_source_is_not_executed(self):
        marker = self.root / 'never-created'
        info = self.convert(metadata=dict(self.metadata, label='<script>run()</script>', sourceUrl='https://example.org/$(touch ' + str(marker) + ')'))
        self.assertFalse(marker.exists()); self.assertIn('<script>', info['title'])


if __name__ == '__main__':
    unittest.main()
