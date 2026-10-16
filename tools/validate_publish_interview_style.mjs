import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

const backup = path.resolve(process.argv[2] ?? '');
const publish = process.argv.includes('--publish');
const manifest = JSON.parse(fs.readFileSync(path.join(backup, 'manifest.json'), 'utf8').replace(/^\uFEFF/, ''));
const stage = path.join(backup, 'revised');
const original = path.join(backup, 'workspace-original', '嵌入式实习面试笔记');
const vaultOriginal = path.join(backup, 'vault-original', '嵌入式实习面试笔记');
const read = p => fs.readFileSync(p, 'utf8').replace(/^\uFEFF/, '').replace(/\r\n/g, '\n');
const hash = p => crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex').toUpperCase();
const files = fs.readdirSync(stage).filter(n => /^\d{2}_.*\.md$/.test(n)).sort();
const known = new Map(files.map(n => [path.basename(n, '.md'), n]));
const fail = message => { throw new Error(message); };
const headings = text => [...text.matchAll(/^## Q\d{3}【P[01]】[^\n]*$/gm)].map(m => m[0]);
const checks = {files: files.length, questions: 0, p0: 0, p1: 0, indexTasksPreserved: false, manualNotesPreserved: false, referenceUnchanged: false, noteLinksChecked: 0, historicalNumericTokensPreserved: true};
if (files.length !== 21) fail('Expected 21 note files.');

// Metadata, list spacing and prose formatting must not mutate aliases or code.
for (const name of files) {
  const target = path.join(stage, name);
  let text = read(target);
  if (fs.existsSync(path.join(original, name))) {
    const before = read(path.join(original, name));
    for (const field of ['aliases', 'tags', 'date', 'implementation_date']) {
      const value = before.match(new RegExp(`^${field}:.*$`, 'm'))?.[0];
      if (value) text = text.replace(new RegExp(`^${field}:.*$`, 'm'), value);
    }
  }
  let fence = false;
  const lines = text.split('\n');
  const output = [];
  for (const line of lines) {
    if (/^\s*```/.test(line)) fence = !fence;
    const last = output.at(-1);
    const isList = /^(?:- |\d+\. )/.test(line);
    const followsList = /^(?:- |\d+\. | {2,}\S)/.test(last ?? '');
    if (!fence && last && (/^#{1,6} /.test(line) || (isList && !followsList))) output.push('');
    output.push(line);
  }
  text = output.join('\n').replace(/\n{3,}/g, '\n\n').trimEnd() + '\n';
  fs.writeFileSync(target, text, 'utf8');
  if (fence) fail(`Unbalanced code fences: ${name}`);
  if (/深入细节与追问（|先用白话理解：|例子 \/ 项目联系：/.test(text)) fail(`Old answer scaffold remains: ${name}`);
  if (/^0[1-8]_/.test(name)) {
    const current = headings(text);
    const prior = headings(read(path.join(original, name)));
    if (JSON.stringify(current) !== JSON.stringify(prior)) fail(`Changed question anchors: ${name}`);
    checks.questions += current.length;
    checks.p0 += current.filter(h => h.includes('【P0】')).length;
    checks.p1 += current.filter(h => h.includes('【P1】')).length;
    const chunks = text.split(/(?=^## Q\d{3})/m).slice(1);
    for (const c of chunks) {
      if (!c.includes('**参考回答')) fail(`No direct answer: ${c.slice(0, 50)}`);
      if (!/追问|追加追问/.test(c)) fail(`No follow-up: ${c.slice(0, 50)}`);
    }
  }
  // Historical acceptance reports retain every numeric token and its order.
  if (/^(13|15|18)_/.test(name)) {
    const before = read(path.join(original, name)).replace(/^---\n[\s\S]*?\n---\n/, '');
    const after = text.replace(/^---\n[\s\S]*?\n---\n/, '').replace(/^> \*\*记录口径：[\s\S]*?\n/m, '');
    const nums = s => s.match(/\d+(?:\.\d+)?/g);
    if (JSON.stringify(nums(before)) !== JSON.stringify(nums(after))) fail(`Historical numbers changed: ${name}`);
  }
  for (const m of text.matchAll(/\[\[([^\]|]+)(?:\|[^\]]*)?\]\]/g)) {
    const [stem, anchor] = m[1].split('#');
    if (!known.has(stem)) {
      if (/^\d{2}_/.test(stem)) fail(`Unresolved current note: ${m[1]} in ${name}`);
      continue; // Existing legacy vault links are outside this note-set rewrite.
    }
    checks.noteLinksChecked++;
    if (anchor?.startsWith('Q')) {
      const linked = read(path.join(stage, known.get(stem)));
      if (!headings(linked).some(h => h.slice(3) === anchor)) fail(`Unresolved question: ${m[1]}`);
    }
  }
}
if (checks.questions !== 120 || checks.p0 !== 99 || checks.p1 !== 21) fail('Question totals changed.');
const indexName = '09_问题索引与复习记录.md';
const taskLines = text => text.split('\n').filter(l => /^- \[[ xX]\]/.test(l));
checks.indexTasksPreserved = JSON.stringify(taskLines(read(path.join(vaultOriginal, indexName)))) === JSON.stringify(taskLines(read(path.join(stage, indexName))));
if (!checks.indexTasksPreserved) fail('Review checkboxes changed.');
const diagramBefore = read(path.join(vaultOriginal, '02_CortexM_FreeRTOS_并发与实时性.md')).match(/## Q023[^\n]*\n([\s\S]*?)(?=\*\*先用白话理解：)/)[1].trimEnd();
const diagramAfter = read(path.join(stage, '02_CortexM_FreeRTOS_并发与实时性.md'));
checks.manualNotesPreserved = diagramAfter.includes(diagramBefore) && read(path.join(stage, '01_C与Cpp_编译链接_工程化.md')).includes('数组指针就是保存每一行的起始地址，如果是二维数组的话就每次指针加一就跳一行');
if (!checks.manualNotesPreserved) fail('User additions were lost.');
checks.referenceUnchanged = hash(manifest.reference) === manifest.referenceHash;
if (!checks.referenceUnchanged) fail('Style reference changed.');

const stagedHashes = Object.fromEntries(files.map(name => [name, hash(path.join(stage, name))]));
fs.writeFileSync(path.join(backup, 'validation.json'), JSON.stringify({checks, stagedHashes}, null, 2));
if (publish) {
  for (const [name, expected] of Object.entries(manifest.sourceHashes)) {
    if (hash(path.join(manifest.source, name)) !== expected) fail(`Workspace changed since backup: ${name}`);
  }
  for (const [name, expected] of Object.entries(manifest.vaultHashes)) {
    if (hash(path.join(manifest.vault, name)) !== expected) fail(`Vault changed since backup: ${name}`);
  }
  for (const name of files) {
    if (!(name in manifest.sourceHashes) && fs.existsSync(path.join(manifest.source, name))) fail(`New workspace note already exists: ${name}`);
    if (!(name in manifest.vaultHashes) && fs.existsSync(path.join(manifest.vault, name))) fail(`New vault note already exists: ${name}`);
  }
  for (const name of files) {
    fs.copyFileSync(path.join(stage, name), path.join(manifest.source, name));
    fs.copyFileSync(path.join(stage, name), path.join(manifest.vault, name));
  }
  for (const name of files) {
    if (hash(path.join(manifest.source, name)) !== stagedHashes[name] || hash(path.join(manifest.vault, name)) !== stagedHashes[name]) fail(`Post-install mismatch: ${name}`);
  }
  if (hash(manifest.reference) !== manifest.referenceHash) fail('Reference changed during install.');
  fs.writeFileSync(path.join(backup, 'installation.json'), JSON.stringify({source: manifest.source, vault: manifest.vault, files, hashes: stagedHashes, checks}, null, 2));
}
console.log(JSON.stringify({publish, backup, ...checks}, null, 2));
