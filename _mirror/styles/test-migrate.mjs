import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { migrateStyles } from './migrate.mjs';

const header = '---\npermalink: /style.css\n---\n';
function fixture(t) {
  const parent = fs.realpathSync(os.tmpdir());
  const root = fs.mkdtempSync(path.join(parent, 'mirror-sass-'));
  t.after(() => {
    assert.equal(path.dirname(fs.realpathSync(root)), parent);
    assert.ok(path.basename(root).startsWith('mirror-sass-'));
    fs.rmSync(root, { recursive: true });
  });
  const write = (file, text) => {
    fs.mkdirSync(path.dirname(path.join(root, file)), { recursive: true });
    fs.writeFileSync(path.join(root, file), text);
  };
  write('_sass/_palette.scss', '$colors: (accent: #c43);\n$accent: map-get($colors, accent);\n');
  write('_sass/_variables.scss', '$text: $accent;\n@mixin mobile { @media (max-width: 600px) { @content; } }\n');
  write('_sass/_late.scss', 'body { color: $accent; }\n.card { @include mobile { color: $text; } }\n');
  write('assets/style.scss', header + '@import "palette";\n@import "variables";\nbody { color: blue; }\n@import "late";\n');
  return { root, write, read: file => fs.readFileSync(path.join(root, file), 'utf8') };
}

test('migrates shared variables, map functions and late imports without changing the cascade', t => {
  const { root, read } = fixture(t);
  const report = migrateStyles(root);
  assert.ok(report.resolvedDeprecations >= 4);
  assert.equal(report.remainingDeprecations, 0);
  assert.match(read('_sass/_palette.scss'), /map\.get\(/);
  assert.match(read('assets/style.scss'), /@use /);
  assert.ok(read('assets/style.scss').startsWith(header));
  const again = migrateStyles(root);
  assert.equal(again.resolvedDeprecations, 0);
  assert.equal(again.migratedFiles, 0);
  assert.deepEqual(again.stylesheets, report.stylesheets);
});

test('new upstream partials are migrated too, instead of freezing an old theme copy', t => {
  const { root, write, read } = fixture(t);
  write('_sass/_new-theme.scss', '$theme: (gap: 24px);\n.new { gap: map-get($theme, gap); }\n');
  write('assets/style.scss', read('assets/style.scss') + '@import "new-theme";\n');
  const report = migrateStyles(root);
  assert.equal(report.remainingDeprecations, 0);
  assert.match(read('_sass/_new-theme.scss'), /map\.get\(/);
});

test('publishes the verified CSS with its Jekyll permalink and no second Sass compilation', t => {
  const { root, read } = fixture(t);
  const report = migrateStyles(root, { emitCss: true });
  assert.equal(fs.existsSync(path.join(root, 'assets/style.scss')), false);
  const css = read('assets/style.css');
  assert.ok(css.startsWith(header));
  assert.equal(createHash('sha256').update(css.slice(header.length)).digest('hex'), report.stylesheets[0].cssSha256);
  assert.match(css, /body\{color:blue\}body\{color:#c43\}/);
});

test('a failed source build restores front matter and leaves the candidate unpublished', t => {
  const { root, write, read } = fixture(t);
  const bad = read('assets/style.scss') + '.bad { color: $does-not-exist; }\n';
  write('assets/style.scss', bad);
  assert.throws(() => migrateStyles(root, { emitCss: true }), /Undefined variable/);
  assert.equal(read('assets/style.scss'), bad);
  assert.match(read('_sass/_palette.scss'), /map-get\(/);
  assert.equal(fs.existsSync(path.join(root, 'assets/style.css')), false);
});

test('a pre-existing CSS file is never overwritten', t => {
  const { root, write, read } = fixture(t);
  write('assets/style.css', '/* personal CSS */');
  assert.throws(() => migrateStyles(root, { emitCss: true }), /refusing to overwrite/);
  assert.equal(read('assets/style.css'), '/* personal CSS */');
  assert.ok(read('assets/style.scss').startsWith(header));
});

test('an upstream switch to plain CSS requires no Sass migration', t => {
  const { root, write, read } = fixture(t);
  fs.unlinkSync(path.join(root, 'assets/style.scss'));
  write('assets/style.css', header + 'body { color: blue; }');
  assert.equal(migrateStyles(root, { emitCss: true }).stylesheets.length, 0);
  assert.equal(read('assets/style.css'), header + 'body { color: blue; }');
});
