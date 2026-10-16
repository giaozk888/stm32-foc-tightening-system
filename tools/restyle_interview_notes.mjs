import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

// Only work on the backed-up interview-note set. The style reference is read-only.
const backup = process.argv[2];
if (!backup) throw new Error('Pass the backup directory.');
const manifest = JSON.parse(fs.readFileSync(path.join(backup, 'manifest.json'), 'utf8').replace(/^\uFEFF/, ''));
const original = path.join(backup, 'workspace-original', '嵌入式实习面试笔记');
const vaultOriginal = path.join(backup, 'vault-original', '嵌入式实习面试笔记');
const stage = path.join(backup, 'revised');
const overrideText = readOverrides();
function readOverrides() {
  const text = fs.readFileSync(new URL('./interview_style_overrides.md', import.meta.url), 'utf8').replace(/\r\n/g, '\n');
  const sections = [...text.matchAll(/^## (Q\d{3})\n/gm)];
  return new Map(sections.map((m, n) => [m[1], text.slice(m.index + m[0].length, sections[n + 1]?.index ?? text.length).trim()]));
}
fs.mkdirSync(stage, { recursive: true });
const read = p => fs.readFileSync(p, 'utf8').replace(/^\uFEFF/, '').replace(/\r\n/g, '\n');
const hash = p => crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex').toUpperCase();
const questionRE = /^## (Q\d{3})【P[01]】[^\n]*$/gm;
const audit = [];

function typography(text) {
  let fence = false;
  let yaml = text.startsWith('---\n');
  return text.split('\n').map((line, index) => {
    if (yaml) {
      if (index > 0 && line === '---') yaml = false;
      return line;
    }
    if (/^\s*```/.test(line)) { fence = !fence; return line; }
    if (fence || /^\s*\|/.test(line) || /^## Q\d{3}/.test(line)) return line;
    return line.split(/(`[^`]*`|\[\[[\s\S]*?\]\]|\[[^\]]*\]\([^)]*\))/g).map((part, n) => {
      if (n % 2) return part;
      return part.replace(/你的项目/g, '我的项目').replace(/你的 /g, '我的 ').replace(/你的(?=[\u3400-\u9fff])/g, '我的')
        .replace(/([\u3400-\u9fff])([A-Za-z][A-Za-z0-9_]*)/g, '$1 $2')
        .replace(/([A-Za-z0-9_])([\u3400-\u9fff])/g, '$1 $2');
    }).join('');
  }).join('\n');
}

function frontmatter(text) {
  return text.replace(/^---\n([\s\S]*?)\n---/, (_, body) => {
    body = body.replace(/^updated:.*\n?/m, '').replace(/^edition:.*\n?/m, '');
    return `---\n${body.trimEnd()}\nupdated: 2026-10-06\nedition: 直接问答与项目实战版\n---`;
  });
}

function followup(paragraph) {
  const s = paragraph.replace(/^\*\*追问：\*\*\s*/, '');
  const m = s.match(/^([^？\n]{2,100}？)\s*([\s\S]+)$/);
  return m ? `**追问：${m[1]}**\n\n${m[2]}` : `**追问与回答**\n\n${s}`;
}

function restyleQuestion(chunk) {
  const heading = chunk.match(/^## [^\n]+/)[0];
  const qid = heading.match(/Q\d{3}/)[0];
  if (overrideText.has(qid)) {
    audit.push({ qid, manuallyRewritten: true });
    return `${heading}\n\n${overrideText.get(qid)}`;
  }
  const plain = chunk.match(/\*\*先用白话理解：\*\*\s*([\s\S]*?)(?=\n\n\*\*例子 \/ 项目联系：)/)?.[1]?.trim();
  const example = chunk.match(/\*\*例子 \/ 项目联系：\*\*\s*([\s\S]*?)(?=\n\n\*\*面试时可以这样说：)/)?.[1]?.trim();
  const oral = chunk.match(/\*\*面试时可以这样说：\*\*\s*\n\n([\s\S]*?)(?=\n\n> \[!note\]-)/)?.[1]?.replace(/^> ?/gm, '').trim();
  const marker = chunk.match(/^> \[!note\]- 深入细节与追问[^\n]*\n/m);
  if (!plain || !example || !oral || !marker) throw new Error(`Unexpected question structure: ${qid}`);
  const start = marker.index + marker[0].length;
  const detail = chunk.slice(start).replace(/^> ?/gm, '').trim();
  // Preserve all original technical paragraphs, except a duplicated short answer.
  const paragraphs = detail.split(/\n\s*\n/).filter(Boolean);
  const principles = [], projects = [], questions = [], extras = [];
  for (const p of paragraphs) {
    if (/^\*\*(?:面试短答|短答)：\*\*/.test(p)) { extras.push(p); continue; }
    if (/^\*\*项目(?:联系|回答)：\*\*/.test(p)) projects.push(p.replace(/^\*\*项目(?:联系|回答)：\*\*\s*/, ''));
    else if (/^\*\*追问：\*\*/.test(p)) questions.push(followup(p));
    else principles.push(p.replace(/^\*\*深入：\*\*\s*/, ''));
  }
  // A user annotation in Q001 shared the short-answer paragraph: retain it.
  for (const p of extras) {
    const lines = p.split('\n').slice(1);
    if (lines.length) principles.unshift(lines.join('\n'));
  }
  const beforePlain = chunk.slice(heading.length, chunk.indexOf('**先用白话理解：**')).trim();
  const notice = beforePlain ? beforePlain.replace(/^> \[!\w+\][^\n]*\n?/gm, '').replace(/^> ?/gm, '').trim() : '';
  const body = [heading, '**参考回答**', plain, '**例子**', example];
  if (principles.length) {
    body.push('**关键原理**');
    // Separate dense paragraphs into distinct points, without changing code or tables.
    principles.forEach((p, i) => body.push(principles.length > 1 && !/```|^\|/m.test(p) ? `${i + 1}. ${p.replace(/\n/g, '\n   ')}` : p));
  }
  body.push('**项目回答**', oral);
  projects.forEach(p => { if (p !== oral) body.push(p); });
  body.push(...questions);
  if (notice) body.push('**阶段记录**', notice);
  audit.push({ qid, technicalParagraphs: paragraphs.length, retainedParagraphs: principles.length + projects.length + questions.length, duplicateShortAnswersRemoved: extras.length });
  return typography(body.join('\n\n').trim());
}

for (const name of fs.readdirSync(original).filter(n => /^\d{2}_.*\.md$/.test(n)).sort()) {
  let text = read(path.join(original, name));
  const headings = [...text.matchAll(questionRE)];
  if (/^0[1-8]_/.test(name)) {
    if (headings.length !== 15) throw new Error(`${name}: expected 15 questions, got ${headings.length}`);
    let prefix = text.slice(0, headings[0].index);
    // Old chronology belongs in evidence records, not repeated before each answer.
    prefix = prefix.split('\n').filter(l => !l.startsWith('>')).join('\n').replace(/\n{3,}/g, '\n\n').trim();
    prefix += '\n\n> **阅读方法：**先自己回答题目，再看参考回答；用例子理解，用项目细节佐证。P0 先掌握，P1 用于深入追问。\n> 项目结论按对应日期的验收记录理解，不把主机测试、隔离测试和带载运行混为一谈。查术语见 [[10_术语白话速查]]，证据入口见 [[00_总览与项目证据]]。';
    const sections = [];
    let suffix = '';
    for (let i = 0; i < headings.length; i++) {
      let chunk = text.slice(headings[i].index, i + 1 < headings.length ? headings[i + 1].index : text.length);
      if (i === headings.length - 1) {
        const tail = chunk.slice(chunk.indexOf('\n') + 1).match(/^## (?!Q\d{3})/m);
        if (tail) {
          const at = chunk.indexOf('\n') + 1 + tail.index;
          suffix = chunk.slice(at).trim();
          chunk = chunk.slice(0, at);
        }
      }
      sections.push(restyleQuestion(chunk));
    }
    text = `${prefix}\n\n${sections.join('\n\n')}\n\n${suffix}\n`;
    if (name.startsWith('02_')) {
      const manual = read(path.join(vaultOriginal, name)).match(/## Q023[^\n]*\n([\s\S]*?)(?=\*\*先用白话理解：)/)?.[1]?.trimEnd();
      if (!manual || !manual.includes('新Task继续运行')) throw new Error('Missing user scheduling diagram');
      text = text.replace(/(## Q023[^\n]*\n\n)/, `$1**任务切换流程（保留原补充）**\n\n\`\`\`text\n${manual}\n\`\`\`\n\n`);
    }
  } else {
    // Reports retain dated results and numeric measurements; only introductory wording changes.
    text = typography(text);
    if (/^(13|15|18)_/.test(name)) {
      text = text.replace(/(^# [^\n]+\n)/m, '$1\n> **记录口径：**本文保留对应日期的实机结果、失败和限制；“当前”“本次”指那次验收，不是今天重新操作。最新综合记录见 [[20_真实网络Transfer与FOC并发_面试回答]]。\n');
    }
  }
  // Source-note relative file links are not valid after installation in the vault.
  text = text.replace(/\]\((\.\.\/[^)]+)\)/g, (whole, relative) => {
    const target = path.resolve(manifest.source, relative).replace(/\\/g, '/');
    return fs.existsSync(target) ? `](<${target}>)` : whole;
  });
  text = frontmatter(text).replace(/\n{3,}/g, '\n\n').trimEnd() + '\n';
  const actual = [...text.matchAll(questionRE)].map(m => m[0]);
  if (JSON.stringify(actual) !== JSON.stringify(headings.map(m => m[0]))) throw new Error(`Heading changed: ${name}`);
  fs.writeFileSync(path.join(stage, name), text, 'utf8');
}
if (audit.length !== 120) throw new Error(`Expected 120 questions, got ${audit.length}`);
fs.writeFileSync(path.join(backup, 'rewrite-audit.json'), JSON.stringify({stage, audit, referenceUnchanged: hash(manifest.reference) === manifest.referenceHash}, null, 2));
console.log(JSON.stringify({stage, files: fs.readdirSync(stage).length, questions: audit.length, manuallyRewritten: audit.filter(a => a.manuallyRewritten).length, referenceUnchanged: hash(manifest.reference) === manifest.referenceHash}, null, 2));
