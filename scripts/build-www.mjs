/**
 * build-www.mjs — 把 H5 源文件按白名单复制到 www/（Capacitor webDir）。
 * 幂等：每次运行先清空 www/ 再复制。不修改任何源文件。
 * 顺手对账版本号：发版要动的几处（package.json / config.js / build.gradle）不一致就停手，
 * 免得又留下「界面上写 0.5、实际是 0.5.1、文档说 0.4.0」这种三方各说各话。
 * 用法：npm run build-www
 */
import { rm, mkdir, cp, access, readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(root, '..');
const wwwDir = path.join(projectRoot, 'www');

// 白名单：只复制这些，其余一律不动
const files = [
  'index.html',
  'styles.css',
  'config.js',
  'engine.js',
  'api.js',
  'state.js',
  'ui.js',
  'card.js',
  // 长图拆成三份：card.js 74KB 顶到了 test:pkg 的单文件 64KB 上限（MAX_FILE_KB）。
  // 拆分理由与加载顺序见 index.html 末尾那几行注释。
  'card-year.js',
  'card-long.js',
  'yi.js',
  'wei.js',
  'yan.js',
  'me.js',
  'app.js',
  'theme.js',
  'wardrobe.js',
  'cookbook.js',
  'market.js',
  'remind.js',
  'stats.js',
  'achievements.js',
  'settings.js',
  'wire.js',
  'share.js',
  'today.js',
  'styles-v06.css',
  'styles-yi.css',
  'styles-wei.css',
  'styles-yan.css',
  'styles-stats.css',
  'styles-me.css',
  'manifest.json',
];
const dirs = ['icons/'];
const optionalFiles = ['sw.js']; // 存在才复制

async function exists(p) {
  try {
    await access(p);
    return true;
  } catch {
    return false;
  }
}

/** 版本号对账。gradle 缺失（只跑 H5 不打包）时只比 npm 与 config 两处。 */
async function checkVersions() {
  const seen = {};
  const pkg = JSON.parse(await readFile(path.join(projectRoot, 'package.json'), 'utf8'));
  seen['package.json'] = pkg.version;

  const cfgSrc = await readFile(path.join(projectRoot, 'config.js'), 'utf8');
  const cfg = cfgSrc.match(/version:\s*"([^"]+)"/);
  if (!cfg) {
    console.error('[build-www] config.js 里找不到 version，界面页脚会显示 undefined');
    process.exit(1);
  }
  seen['config.js'] = cfg[1];

  const gradlePath = path.join(projectRoot, 'android/app/build.gradle');
  if (await exists(gradlePath)) {
    const g = (await readFile(gradlePath, 'utf8')).match(/versionName\s+"([^"]+)"/);
    if (g) seen['build.gradle versionName'] = g[1];
  }

  // 离线缓存的名字带版本号：sw.js 里的 VERSION 落后一版，老用户就永远拿不到新壳
  const swPath = path.join(projectRoot, 'sw.js');
  if (await exists(swPath)) {
    const s = (await readFile(swPath, 'utf8')).match(/const VERSION = "([^"]+)"/);
    if (!s) {
      console.error('[build-www] sw.js 里找不到 const VERSION，缓存名没法和版本一起换');
      process.exit(1);
    }
    seen['sw.js VERSION'] = s[1];
  }

  const values = Object.entries(seen);
  const bad = values.filter(([, v]) => v !== seen['config.js']);
  if (bad.length) {
    console.error('[build-www] 版本号不一致，先对齐再出包：');
    for (const [where, v] of values) console.error(`  ${where.padEnd(22)} ${v}`);
    console.error('  界面上的版本号取 config.js 那一处。');
    process.exit(1);
  }
  console.log(`[build-www] 版本号一致：${seen['config.js']}（${values.length} 处已对账）`);
}

async function main() {
  await checkVersions();

  // 先清空 www/
  if (await exists(wwwDir)) {
    await rm(wwwDir, { recursive: true, force: true });
  }
  await mkdir(wwwDir, { recursive: true });

  const copied = [];
  const skipped = [];

  for (const f of files) {
    const src = path.join(projectRoot, f);
    if (!(await exists(src))) {
      skipped.push(f + ' (缺失)');
      continue;
    }
    await cp(src, path.join(wwwDir, f));
    copied.push(f);
  }

  for (const d of dirs) {
    const src = path.join(projectRoot, d);
    if (!(await exists(src))) {
      skipped.push(d + ' (缺失)');
      continue;
    }
    await cp(src, path.join(wwwDir, d), { recursive: true });
    copied.push(d);
  }

  for (const f of optionalFiles) {
    const src = path.join(projectRoot, f);
    if (await exists(src)) {
      await cp(src, path.join(wwwDir, f));
      copied.push(f);
    } else {
      skipped.push(f + ' (不存在，跳过)');
    }
  }

  console.log('[build-www] 已复制到 www/:');
  for (const c of copied) console.log('  + ' + c);
  if (skipped.length) {
    console.log('[build-www] 跳过:');
    for (const s of skipped) console.log('  - ' + s);
  }
  console.log('[build-www] 完成: ' + wwwDir);
}

main().catch((err) => {
  console.error('[build-www] 失败:', err);
  process.exit(1);
});
