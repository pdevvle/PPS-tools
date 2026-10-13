// MeshData (typed arrays from the worker) → three.js BufferGeometry.
import * as THREE from 'three';
import type { MeshData } from '../mesh/builder';

export function toGeometry(md: MeshData, withBid = false): THREE.BufferGeometry {
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(md.position, 3));
  g.setAttribute('normal', new THREE.BufferAttribute(md.normal, 3));
  g.setAttribute('aCol', new THREE.BufferAttribute(md.col, 3));
  g.setAttribute('aMat', new THREE.BufferAttribute(md.mat, 1));
  g.setAttribute('aUv', new THREE.BufferAttribute(md.uv, 2));
  g.setAttribute('aSeed', new THREE.BufferAttribute(md.seed, 1));
  g.setAttribute('aSnow', new THREE.BufferAttribute(md.snow, 1));
  g.setAttribute('aAo', new THREE.BufferAttribute(md.ao, 1));
  g.setAttribute('aAux', new THREE.BufferAttribute(md.aux, 2));
  if (withBid) g.setAttribute('aBid', new THREE.BufferAttribute(md.bid, 1));
  g.computeBoundingSphere();
  return g;
}
