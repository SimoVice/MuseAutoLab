/** Simplify the two known STEP-derived meshes and write scratch GLB files. */
import { readFileSync, writeFileSync } from 'node:fs';
import { MeshoptSimplifier } from '../web/node_modules/meshoptimizer/index.js';

const name = process.argv[2];
if (!['static', 'bed'].includes(name)) throw new Error('Choose static or bed.');
await MeshoptSimplifier.ready;
const positionBytes = readFileSync(`.local/upstream-cad/${name}-vertices.bin`);
const indexBytes = readFileSync(`.local/upstream-cad/${name}-indices.bin`);
const positions = new Float32Array(positionBytes.buffer, positionBytes.byteOffset, positionBytes.length / 4);
const originalIndices = new Uint32Array(indexBytes.buffer, indexBytes.byteOffset, indexBytes.length / 4);
const [simplified, error] = originalIndices.length <= 900000
  ? [originalIndices, 0]
  : MeshoptSimplifier.simplify(originalIndices, positions, 3, 900000, 0.002, []);

const remap = new Map();
const coordinates = [];
const indices = new Uint32Array(simplified.length);
for (let i = 0; i < simplified.length; i += 1) {
  const old = simplified[i];
  let mapped = remap.get(old);
  if (mapped === undefined) {
    mapped = remap.size;
    remap.set(old, mapped);
    coordinates.push(positions[old * 3], positions[old * 3 + 1], positions[old * 3 + 2]);
  }
  indices[i] = mapped;
}
const vertices = new Float32Array(coordinates);
const vertexBuffer = Buffer.from(vertices.buffer);
const indexBuffer = Buffer.from(indices.buffer);
const min = [Infinity, Infinity, Infinity];
const max = [-Infinity, -Infinity, -Infinity];
for (let i = 0; i < vertices.length; i += 1) {
  const axis = i % 3;
  min[axis] = Math.min(min[axis], vertices[i]);
  max[axis] = Math.max(max[axis], vertices[i]);
}
const gltf = {
  asset: { version: '2.0', generator: 'MuseAutoLab STEP tessellation' },
  buffers: [{ byteLength: vertexBuffer.length + indexBuffer.length }],
  bufferViews: [
    { buffer: 0, byteOffset: 0, byteLength: vertexBuffer.length, target: 34962 },
    { buffer: 0, byteOffset: vertexBuffer.length, byteLength: indexBuffer.length, target: 34963 },
  ],
  accessors: [
    { bufferView: 0, componentType: 5126, count: vertices.length / 3, type: 'VEC3', min, max },
    { bufferView: 1, componentType: 5125, count: indices.length, type: 'SCALAR' },
  ],
  meshes: [{ primitives: [{ attributes: { POSITION: 0 }, indices: 1, mode: 4 }] }],
  nodes: [{ mesh: 0 }], scenes: [{ nodes: [0] }], scene: 0,
};
let json = Buffer.from(JSON.stringify(gltf));
json = Buffer.concat([json, Buffer.alloc((4 - json.length % 4) % 4, 0x20)]);
const binary = Buffer.concat([vertexBuffer, indexBuffer]);
const header = Buffer.alloc(12);
header.write('glTF');
header.writeUInt32LE(2, 4);
header.writeUInt32LE(12 + 8 + json.length + 8 + binary.length, 8);
const jsonHeader = Buffer.alloc(8);
jsonHeader.writeUInt32LE(json.length, 0);
jsonHeader.write('JSON', 4);
const binaryHeader = Buffer.alloc(8);
binaryHeader.writeUInt32LE(binary.length, 0);
binaryHeader.write('BIN\0', 4);
writeFileSync(`.local/upstream-cad/${name}.glb`, Buffer.concat([
  header, jsonHeader, json, binaryHeader, binary,
]));
console.log({ name, triangles: indices.length / 3, vertices: vertices.length / 3, error, min, max });
