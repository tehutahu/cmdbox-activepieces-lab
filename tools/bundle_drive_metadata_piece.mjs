// Build only. Never installs/publishes into AP or creates OAuth resources.
import {createRequire, isBuiltin} from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const [source, dependencies, output] = process.argv.slice(2).map(p => path.resolve(p));
if (!source || !dependencies || !output || fs.existsSync(output)) throw new Error('Fresh output directory required');
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(path.join(dependencies, 'package.json'));
const esbuild = require('esbuild');
fs.mkdirSync(path.join(output, 'src'), {recursive: true});
const alias = {
  '@activepieces/pieces-framework': path.join(source, 'packages/pieces/framework/src/index.ts'),
  '@activepieces/core-utils': path.join(source, 'packages/core/utils/src/index.ts'),
  '@activepieces/core-piece-types': path.join(source, 'packages/core/piece-types/src/index.ts'),
};
const options = {bundle: true, platform: 'node', format: 'cjs', target: 'node20', keepNames: true,
  nodePaths: [path.join(dependencies, 'node_modules')], alias, metafile: true, logLevel: 'warning'};
const built = await esbuild.build({...options, entryPoints: [path.join(root, 'pieces/drive-metadata-search/src/index.mjs')],
  outfile: path.join(output, 'src/index.js')});
// Run the pinned extraction function too: constructor.name is a real engine contract.
await esbuild.build({...options, entryPoints: [path.join(source, 'packages/core/shared/src/lib/automation/pieces/utils.ts')],
  outfile: path.join(output, 'pinned-extractor.cjs')});
const metadata = JSON.parse(fs.readFileSync(path.join(root, 'pieces/drive-metadata-search/package.json')));
fs.writeFileSync(path.join(output, 'package.json'), JSON.stringify(metadata, null, 2) + '\n');
const imports = Object.values(built.metafile.outputs).flatMap(o => o.imports);
if (imports.some(i => i.external && !isBuiltin(i.path)))
  throw new Error('Unexpected external runtime dependency');
fs.writeFileSync(path.join(output, 'build-metafile.json'), JSON.stringify(built.metafile));
let notices = fs.readFileSync(path.join(source, 'LICENSE'), 'utf8');
for (const [name, pkg] of Object.entries(require('./package-lock.json').packages)) {
  if (!name || pkg.optional) continue;
  const directory = path.join(dependencies, name);
  if (!fs.existsSync(directory)) continue;
  const licenses = fs.readdirSync(directory).filter(n => /^(license|licence|copying)(\.|$)/i.test(n));
  for (const license of licenses) notices += `\n\n--- ${name} ${pkg.version}: ${license} ---\n` + fs.readFileSync(path.join(directory, license), 'utf8');
}
fs.writeFileSync(path.join(output, 'THIRD-PARTY-NOTICES.txt'), notices);
const extractor = require(path.join(output, 'pinned-extractor.cjs'));
const piece = extractor.extractPieceFromModule({module: require(path.join(output, 'src/index.js')),
  pieceName: metadata.name, pieceVersion: metadata.version});
const m = piece.metadata();
if (piece.constructor.name !== 'Piece' || Object.keys(m.actions).join(',') !== 'search_folder_metadata' ||
  Object.keys(m.triggers).length || m.auth.scope.join(',') !== 'https://www.googleapis.com/auth/drive.metadata.readonly' ||
  m.minimumSupportedRelease !== '0.92.2' || m.maximumSupportedRelease !== '0.92.2' || m.contextInfo.version !== '2')
  throw new Error('Pinned extraction/metadata mismatch');
console.log(JSON.stringify({status: 'pass', package: metadata.name, version: metadata.version,
  framework: '0.40.0-source', context: m.contextInfo.version, sources: Object.keys(built.metafile.inputs).length,
  externalRuntimeDependencies: imports.filter(i => i.external).map(i => i.path)}));
