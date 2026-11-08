// Copies the team's pitch deck (../docs/pitch.html, the single source of truth)
// into public/ so it is served at /deck. Runs before `dev` and `build`.
import { copyFileSync, existsSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const source = join(root, '..', 'docs', 'pitch.html');
const target = join(root, 'public', 'deck.html');

if (existsSync(source)) {
  mkdirSync(dirname(target), { recursive: true });
  copyFileSync(source, target);
  console.log('deck: copied docs/pitch.html -> public/deck.html (/deck)');
} else {
  console.warn(`deck: ${source} not found; /deck will 404`);
}
