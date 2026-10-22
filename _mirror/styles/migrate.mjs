// Migrate the disposable build copy, so new upstream styles keep flowing in.
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import * as sass from 'sass';

const directory = path.dirname(fileURLToPath(import.meta.url));
const migrator = path.join(directory, 'node_modules/sass-migrator/sass-migrator.js');
const frontMatter = /^\uFEFF?---\r?\n[\s\S]*?\r?\n---(?:\r?\n|$)/;

function sourcesIn(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    if (entry.name.startsWith('.') || ['node_modules', 'vendor', '_site'].includes(entry.name)) return [];
    const target = path.join(directory, entry.name);
    if (entry.isSymbolicLink()) throw new Error(`Style source must not be a symlink: ${target}`);
    if (entry.isDirectory()) return sourcesIn(target);
    return /\.(scss|sass)$/.test(entry.name) ? [target] : [];
  }).sort();
}

function compile(entry, loadPaths, warnings) {
  return sass.compile(entry, {
    loadPaths,
    style: 'compressed',
    sourceMap: false,
    verbose: true,
    logger: {
      // The legacy compilation is a comparison baseline, never the published CSS.
      warn(message, options) {
        warnings.push({ message, deprecation: options.deprecation, id: options.deprecationType?.id });
      },
      debug() {},
    },
  }).css;
}

function localizeImports(file, root) {
  // Jekyll's _sass folder is first-party source. Relative imports let the
  // official migrator follow it instead of treating it as a third-party load path.
  const exists = base => [base, `${base}.scss`, `${base}.sass`,
    path.join(path.dirname(base), '_' + path.basename(base) + '.scss'),
    path.join(path.dirname(base), '_' + path.basename(base) + '.sass')]
    .some(candidate => fs.existsSync(candidate) && fs.statSync(candidate).isFile());
  const text = fs.readFileSync(file, 'utf8').replace(
    /(^[\t ]*@import\s+)(["'])([^"']+)\2(?=\s*;)/gm,
    (match, prefix, quote, name) => {
      if (exists(path.resolve(path.dirname(file), name))) return match;
      const target = path.resolve(root, '_sass', name);
      if (!exists(target)) return match;
      const relative = path.relative(path.dirname(file), target).split(path.sep).join('/');
      return prefix + quote + relative + quote;
    });
  fs.writeFileSync(file, text);
}

export function migrateStyles(build, { emitCss = false } = {}) {
  const root = fs.realpathSync(build);
  const files = sourcesIn(root);
  const originals = new Map(files.map(file => [file, fs.readFileSync(file, 'utf8')]));
  const headers = new Map([...originals].flatMap(([file, text]) => {
    const match = text.match(frontMatter);
    return match ? [[file, match[0]]] : [];
  }));
  const entries = [...headers.keys()];
  if (!entries.length) {
    console.log('No Jekyll Sass entrypoints; existing CSS will be checked by publication validation.');
    return { migratedFiles: 0, resolvedDeprecations: 0, remainingDeprecations: 0, stylesheets: [] };
  }
  const loadPaths = [path.join(root, '_sass')];
  const outputs = entries.map(entry => entry.replace(/\.(scss|sass)$/, '.css'));
  const written = [];
  if (emitCss && (new Set(outputs).size !== outputs.length || outputs.some(output => fs.existsSync(output)))) {
    throw new Error('A generated CSS path already exists; refusing to overwrite an upstream or personal file.');
  }
  try {
    // Sass does not parse Jekyll YAML. Restore these exact headers after migration.
    for (const [file, header] of headers) fs.writeFileSync(file, originals.get(file).slice(header.length));
    const beforeWarnings = [];
    const before = entries.map(entry => compile(entry, loadPaths, beforeWarnings));
    for (const file of files) localizeImports(file, root);
    const relative = file => path.relative(root, file).split(path.sep).join('/');
    const result = spawnSync(process.execPath, [migrator, 'module', '--migrate-deps',
      '--load-path', '_sass', ...entries.map(relative)],
    { cwd: root, encoding: 'utf8', timeout: 120000 });
    if (result.error || result.status !== 0) {
      throw new Error(`Sass module migration failed: ${result.error?.message || result.stderr || result.stdout}`);
    }
    const afterWarnings = [];
    const after = entries.map(entry => compile(entry, loadPaths, afterWarnings));
    for (let i = 0; i < entries.length; i++) {
      if (before[i] !== after[i]) {
        throw new Error(`Migration changed compiled CSS: ${path.relative(root, entries[i])}; refusing publication.`);
      }
    }
    const remaining = afterWarnings.filter(warning => warning.deprecation);
    if (remaining.length) {
      throw new Error(`Sass deprecations remain after migration: ${remaining.map(w => `${w.id}: ${w.message}`).join('\n')}`);
    }
    for (const warning of afterWarnings) console.warn(warning.message);
    for (const [file, header] of headers) fs.writeFileSync(file, header + fs.readFileSync(file, 'utf8'));
    const report = {
      compiler: sass.info.split('\n')[0],
      migratedFiles: files.filter(file => fs.readFileSync(file, 'utf8') !== originals.get(file)).length,
      resolvedDeprecations: beforeWarnings.filter(warning => warning.deprecation).length,
      remainingDeprecations: remaining.length,
      stylesheets: entries.map((entry, i) => ({
        path: path.relative(root, entry).split(path.sep).join('/'),
        cssSha256: createHash('sha256').update(after[i]).digest('hex'),
      })),
    };
    if (emitCss) {
      // Publish CSS with the original Jekyll front matter/permalink. This uses
      // the locked, verified compiler instead of recompiling with a floating Ruby gem.
      for (let i = 0; i < entries.length; i++) {
        fs.writeFileSync(outputs[i], headers.get(entries[i]) + after[i]);
        written.push(outputs[i]);
      }
      for (const entry of entries) fs.unlinkSync(entry);
    }
    console.log(`Sass migration verified: ${report.migratedFiles} files modernized, ` +
      `${report.resolvedDeprecations} deprecations resolved, zero remaining; ` +
      `${entries.length} compiled stylesheets are byte-for-byte unchanged.`);
    return report;
  } catch (error) {
    // Failed checks leave the candidate sources intact for diagnosis/retry.
    for (const output of written) fs.unlinkSync(output);
    for (const [file, original] of originals) fs.writeFileSync(file, original);
    throw error;
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const build = path.resolve(directory, '../build');
  const report = migrateStyles(build, { emitCss: true });
  fs.writeFileSync(path.join(build, '.sass-migration-report.json'), JSON.stringify(report, null, 2) + '\n');
}
