// Check dependency compatibility without claiming browser or WebGL validation.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { Canvas } from '@react-three/fiber';
import { createElement, version as reactVersion } from 'react';
import { BoxGeometry, REVISION } from 'three';

const manifest = JSON.parse(await readFile(new URL('../package.json', import.meta.url), 'utf8'));
const lock = JSON.parse(await readFile(new URL('../package-lock.json', import.meta.url), 'utf8'));
assert.equal(process.versions.node, manifest.engines.node, 'Use the pinned Node.js version');
for (const [name, expected] of Object.entries({ ...manifest.dependencies, ...manifest.devDependencies })) {
  const entry = lock.packages[`node_modules/${name}`];
  assert.equal(entry?.version, expected, `${name} must match its exact direct version`);
  // Read direct dependency manifests without invoking runtime exports of @types packages.
  const installed = JSON.parse(await readFile(new URL(`../node_modules/${name}/package.json`, import.meta.url), 'utf8'));
  assert.equal(installed.name, name);
  assert.equal(installed.version, expected, `${name} is not installed at its pinned version`);
}
assert.equal(reactVersion, manifest.dependencies.react);
assert.ok(createElement(Canvas));
const geometry = new BoxGeometry(1, 2, 3);
geometry.computeBoundingBox();
assert.equal(geometry.boundingBox.max.z - geometry.boundingBox.min.z, 3);
geometry.dispose();
console.log(JSON.stringify({ status: 'passed', node: process.versions.node, react: reactVersion, threeRevision: REVISION, scope: 'installed packages and headless imports; no browser or WebGL test' }, null, 2));
