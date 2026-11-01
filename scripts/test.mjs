/**
 * test.mjs — 一把跑完该跑的守门。
 *
 *   npm test            快速三道（引擎 / 两端一致性 / 网关 HTTP），无浏览器、无额外依赖
 *   npm run test:gate   守门自检：三百多条「只改一处」的注入，要求每次都必须炸
 *                       （赶时间可以 `python test/gate_selfcheck.py --only 关键词` 只跑新加的那几条）
 *   npm run test:e2e    六道浏览器全流程（e2e / e2e_gateway / contrast / offline / perf /
 *                       dead_controls，要本机 Edge）
 *   npm run test:v06    0.6.0 新增的八道浏览器门（smoke / light_audit / 六条 lane）——
 *                       比 test:e2e 快得多，改完任何一个模块先跑这个
 *   npm run test:pkg    只验构建产物：www / 安卓资产 / sw 清单 / 载荷重量 / APK 与 AAB 里是哪版前端
 *   npm run audit       差分 fuzz 深扫，1400 例，要求漂移归零；
 *                       菜单词池从菜库现读，造完输入会自证 63 道每道都被抽到过（抽不到直接 FAIL gen）
 *   npm run check       以上全部 + 三处产物漂移（www / 安卓资产 / sw 预缓存清单）+ 载荷重量（发版前跑这个）
 *
 * 为什么需要它：这里一共十几套测试，之前只能一条条手敲，漏跑一条就等于没跑。
 */
import { spawnSync, execFileSync } from 'node:child_process';
import { readFileSync, existsSync, readdirSync, statSync, mkdirSync, writeFileSync } from 'node:fs';
import zlib from 'node:zlib';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));

// Windows 控制台是 GBK，Python 打印中文能直接 UnicodeEncodeError——在这里统一兜掉，
// 省得每次都要记得手敲 PYTHONIOENCODING=utf-8
const env = { ...process.env, PYTHONIOENCODING: 'utf-8' };

const PY = ['python', 'python3']
  .find((c) => { try { execFileSync(c, ['--version'], { env, stdio: 'ignore' }); return true; } catch { return false; } });

/** [标签, 命令, 参数] */
const FAST = [
  // 守门自检自己的前置：锚点飘了 = 那条守门根本没在跑，而整套要 60 多分钟才发现。
  // 这一秒长的检查放在最前面，每次跑。
  ['anchors', PY, ['test/gate_selfcheck.py', '--preflight']],
  ['engine.test', 'node', ['test/engine.test.mjs']],
  ['hardening', 'node', ['test/hardening.test.mjs']],
  ['consistency', PY, ['test/consistency.py']],
  ['gateway_http', PY, ['test/gateway_http.py']],
  // 跨产物的一道门：清单里的 allowBackup 与商店材料里的隐私政策得同真同假
  ['backup_claim', PY, ['test/backup_claim.py']],
  // 同一类，范围大得多：商店页上每一句可核实的话（版本号、权限、像素数、举了菜名的例子）
  // 都回头对一遍代码。描述与行为不符在 Play 那边是可以直接下架的。
  // 新克隆尚无 APK 时先核静态承诺；已有发布产物时才核真实包名、权限和 targetSdk。
  ['store_claims', PY, ['test/store_claims.py', ...(existsSync(path.join(root, 'android/app/build/outputs/apk/release/app-release.apk')) ? [] : ['--source-only'])]],
  // 设备侧那五套脚本的「只准动自己那台模拟器」：打桩判定 + 静态查接线，全程不碰真设备。
  ['device_guards', PY, ['test/device_guards.py']],
];
const GATE = [['gate_selfcheck', PY, ['test/gate_selfcheck.py']]];
// 政策的第三个副本（GitHub 上**已发布**的那一份）只能联网量，所以不进 fast：
// 在没装 gh / 没登录的机器上它该红得有意义，而不是把整组快速守门拖成一次网络投票。
// 两件事分成两步：先比字节（publish-privacy --check），再把公开那一页真的渲染出来量
// （360 宽不横向出血、落款滚得到、印章不变形、控制台一句报错都没有）。
const SHIP = [
  ['privacy_ship', PY, ['scripts/publish-privacy.py', '--check']],
  ['privacy_page', PY, ['test/privacy_page.playwright.py']],
];
const E2E = [
  ['e2e', PY, ['test/e2e.playwright.py']],
  ['e2e_gateway', PY, ['test/e2e_gateway.playwright.py']],
  ['contrast', PY, ['test/contrast.playwright.py']],
  ['offline', PY, ['test/offline.playwright.py']],
  ['perf', PY, ['test/perf.playwright.py']],
  // 「按下去静默什么都不说」是整片扫出来的结构不变量，和第 47 轮键盘、第 39 轮触摸尺寸同一家族
  ['dead_controls', PY, ['test/dead_controls.playwright.py']],
];
// 0.6.0 这一版的八道门：一次装完、全是 Playwright、没有一道依赖网络或真机。
// 为什么单列一档而不塞进 E2E：E2E 那六道老的加起来要 20 多分钟（e2e 一套就 400KB 断言），
// 而这一档全程不到三分钟——改完一个模块想立刻知道有没有砸掉东西，跑这个才对。
// 顺序有讲究：smoke 与 light_audit 是「全屏扫」的粗网，先跑；六条 lane 是细网，后跑。
const V06 = [
  ['smoke', PY, ['test/smoke.py']],
  // 深色模式漏到底这类问题只有肉眼看得见，单元测试与 DOM 断言都抓不住：
  // 这支把 10 屏在白天/夜里各跑一遍，断言纸真的翻了、夜里确实更暗、白天仍是原纸色。
  ['light_audit', PY, ['test/light_audit.playwright.py']],
  ['yi_v06', PY, ['test/yi_v06.playwright.py']],
  ['wei_v06', PY, ['test/wei_v06.playwright.py']],
  ['yan_v06', PY, ['test/yan_v06.playwright.py']],
  ['pu_v06', PY, ['test/stats_v06.playwright.py']],
  // 长图 lane：四张 1080×1920 的纸（单品 / 搭配 / 摘录 / 年度）画不画得出来，
  // 以及**夜里存出来还是白天的纸**——那一条只有真的画一遍、量一次像素才验得到。
  ['card_v06', PY, ['test/card_v06.playwright.py']],
  ['me_v06', PY, ['test/me_v06.playwright.py']],
  // 无障碍门：24 个屏/页签状态的 9 条结构不变量（名字 / 图注 / 标题层级 / Tab 顺序 /
  // 键盘激活 / 对比度 / 触摸目标 / 减少动态 / 选中态）。放在最后：它最慢，
  // 而且它量的东西横跨前面每一条 lane——前面红了先修前面，别在这儿对症状。
  ['a11y_v06', PY, ['test/a11y_v06.playwright.py']],
];
// fuzz 的四步有先后依赖：造输入 → 两端各跑一遍 → 对答案
const AUDIT_STEPS = [
  ['gen', PY, ['test/_audit/gen.py']],
  ['run_js', 'node', ['test/_audit/run_js.mjs']],
  ['run_py', PY, ['test/_audit/run_py.py']],
];

function run([label, cmd, args]) {
  if (!cmd) {
    console.log(` SKIP  ${label.padEnd(15)}（PATH 里没有 python，这个 .py 跑不了；ship 那一档会因此直接判失败）`);
    return null;
  }
  const t0 = Date.now();
  const r = spawnSync(cmd, args, { cwd: root, env, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 });
  const ms = Date.now() - t0;
  const out = (r.stdout || '') + (r.stderr || '');
  if (r.status === 0) {
    const line = out.split(/\r?\n/).filter((l) => /通过|漂移|一致|拦截/.test(l)).pop() || 'ok';
    console.log(`  ok   ${label.padEnd(15)} ${String(ms).padStart(6)} ms   ${line.trim()}`);
    return true;
  }
  console.log(` FAIL  ${label.padEnd(15)} ${String(ms).padStart(6)} ms`);
  // 完整输出落盘。以前只打前 20 行匹配行：gate_selfcheck 跑 12 分钟只告诉我们「有一条没抓到」，
  // 到底是哪一条得再跑 12 分钟——排查成本全花在自己人身上。
  const dump = path.join(root, 'test', '_audit', `fail-${label}.log`);
  try { mkdirSync(path.dirname(dump), { recursive: true }); writeFileSync(dump, out); } catch (_) { }
  const why = out.split(/\r?\n/).filter((l) => /FAIL|Error|漂移|不一致|异常|没人守/.test(l));
  console.log(why.slice(-20).map((l) => '          ' + l.trim()).join('\n'));
  console.log(`          （完整输出：${path.relative(root, dump).replace(/\\/g, '/')}）`);
  return false;
}

/** www/ 是 build-www 的产物，手改过根目录就会漂——之前是发版前手动 cmp 一遍。
 *  文件清单直接从 build-www.mjs 的白名单里读，免得两处各维护一份、漏一个就查不出来。 */
function wwwFiles() {
  const src = readFileSync(path.join(root, 'scripts', 'build-www.mjs'), 'utf8');
  const block = src.match(/const files = \[([\s\S]*?)\];/);
  if (!block) return null;
  const files = [...block[1].matchAll(/'([^']+)'/g)].map((m) => m[1]);
  // optionalFiles 是「存在才复制」——写了就得一起对账，别让它成为唯一没被比过的产物
  const opt = src.match(/const optionalFiles = \[([^\]]*)\]/);
  if (opt) for (const m of opt[1].matchAll(/'([^']+)'/g)) {
    if (existsSync(path.join(root, m[1]))) files.push(m[1]);
  }
  return files;
}

/** sw.js 的预缓存清单必须盖住整份白名单：少一个文件，断网时就少一块屏。 */
function checkSw(files) {
  const swPath = path.join(root, 'sw.js');
  if (!existsSync(swPath)) { console.log('  --  sw 清单        没有 sw.js，跳过'); return true; }
  const src = readFileSync(swPath, 'utf8');
  const block = src.match(/const SHELL = \[([\s\S]*?)\];/);
  if (!block) { console.log(' FAIL  sw 清单        读不到 sw.js 里的 SHELL'); return false; }
  const shell = new Set([...block[1].matchAll(/["']([^"']+)["']/g)].map((m) => m[1].replace(/^\.\//, '')));
  // sw.js 永远不该预缓存自己，否则一旦缓存住就再也更新不动了
  const missing = files.filter((f) => f !== 'sw.js' && !shell.has(f));
  if (missing.length) {
    console.log(` FAIL  sw 清单        预缓存漏了：${missing.join('、')} → 断网时这些拿不到`);
    return false;
  }
  console.log(`  ok   sw 清单        预缓存盖住白名单 ${files.length} 个文件`);
  return true;
}

/** 桌面长按的快捷方式跨三种语言：res/xml/shortcuts.xml 里的地址、清单里的注册、
 *  前端 screenOf() 认得的屏名。任何一处单独改了都不报错——表现是长按出来的图标点了没反应。
 *  这里把三头对上，尤其是「快捷方式指向的屏在 index.html 里还存不存在」。 */
function checkShortcuts() {
  const res = path.join(root, 'android', 'app', 'src', 'main', 'res');
  const sc = path.join(res, 'xml', 'shortcuts.xml');
  const man = path.join(root, 'android', 'app', 'src', 'main', 'AndroidManifest.xml');
  if (!existsSync(sc)) {
    console.log(' FAIL  快捷方式        缺 res/xml/shortcuts.xml（桌面长按图标没有快捷方式）');
    return false;
  }
  const xml = readFileSync(sc, 'utf8');
  const manifest = readFileSync(man, 'utf8');
  const html = readFileSync(path.join(root, 'index.html'), 'utf8');
  const ui = readFileSync(path.join(root, 'ui.js'), 'utf8');
  const bad = [];
  if (!/android:name="android\.app\.shortcuts"[\s\S]{0,80}@xml\/shortcuts/.test(manifest)) {
    bad.push('清单没把 @xml/shortcuts 挂到 Activity 的 meta-data 上');
  }
  if (!/<data android:scheme="jian"/.test(manifest)) bad.push('清单没注册 jian: 协议');
  // 要的是那条交替式 (yi|wei|yan|me)，不是函数自己的参数表：只写 `\(([\w|]+)\)` 会先撞上 (url)
  const alt = (ui.match(/function screenOf[\s\S]*?\(([a-z]{2,6}\|[a-z|]+)\)/) || [])[1] || '';
  const ids = [...xml.matchAll(/jian:\/\/screen\/([\w-]+)/g)].map((m) => m[1]);
  if (!ids.length) bad.push('shortcuts.xml 里一条 jian://screen/ 都没有');
  for (const id of ids) {
    if (!new RegExp(`class="screen"[^>]*id="${id}"`).test(html)) bad.push(`${id} 在 index.html 里没有对应的屏`);
    if (!alt.split('|').includes(id)) bad.push(`${id} 不在 screenOf() 认得的名字里`);
  }
  if (bad.length) {
    console.log(` FAIL  快捷方式        ${[...new Set(bad)].join('；')}`);
    return false;
  }
  console.log(`  ok   快捷方式        ${ids.length} 枚（${ids.join('、')}）三头对得上`);
  return true;
}

function checkWww() {
  const files = wwwFiles();
  if (!files) {
    console.log(' FAIL  www 漂移        读不到 build-www.mjs 的白名单');
    return false;
  }
  const drift = files.filter((f) => {
    const b = path.join(root, 'www', f);
    return !existsSync(b) || readFileSync(path.join(root, f)).compare(readFileSync(b)) !== 0;
  });
  if (drift.length) {
    console.log(` FAIL  www 漂移        与根目录不一致：${drift.join('、')} → 跑 npm run build-www`);
    return false;
  }
  console.log(`  ok   www 无漂移       ${files.length} 个文件与根目录逐字节一致`);
  return true;
}

/** 安卓工程里的 assets 是 `npx cap sync` 从 www/ 拷过去的。
 *  npm run android/release 都会先 sync，但直接在 android/ 里敲 gradlew 的人不会——
 *  那样打出来的包跑的是上一版前端，测试全绿也白绿（拆文件之后这里就还停在 0.5.1 的单包 app.js）。 */
function checkAndroid() {
  const files = wwwFiles();
  const pub = path.join(root, 'android', 'app', 'src', 'main', 'assets', 'public');
  if (!files || !existsSync(pub)) {
    console.log('  --  android 资产     还没跑过 cap sync，跳过');
    return true;
  }
  const drift = files.filter((f) => {
    const b = path.join(pub, f);
    return !existsSync(b) || readFileSync(path.join(root, 'www', f)).compare(readFileSync(b)) !== 0;
  });
  if (drift.length) {
    console.log(` FAIL  android 资产    与 www/ 不一致：${drift.join('、')} → 跑 npm run cap:sync`);
    return false;
  }
  console.log(`  ok   android 无漂移   ${files.length} 个文件与 www/ 逐字节一致`);
  return true;
}

/** capacitor.config.json 有两份：仓库根这一份是人写的，
 *  android/app/src/main/assets/ 那一份是 cap:sync 拷进去的、APK 真正读的是后者。
 *  只改前者不 sync，构建照样成功、装出来还是旧配置——本轮就被这一步骗过一次：
 *  关了 allowMixedContent 去测，测的其实还是包里那份旧的，差点据此得出反结论。
 *  所以产物对账不能只对 www，配置的这份拷贝也得对。 */
function checkCapConfig() {
  const packed = path.join(root, 'android', 'app', 'src', 'main', 'assets', 'capacitor.config.json');
  const src = path.join(root, 'capacitor.config.json');
  if (!existsSync(packed)) {
    console.log('  --  cap 配置副本     还没跑过 cap sync，跳过');
    return true;
  }
  let a, b;
  try {
    a = JSON.parse(readFileSync(src, 'utf8'));
    b = JSON.parse(readFileSync(packed, 'utf8'));
  } catch (e) {
    console.log(` FAIL  cap 配置副本     有一份不是 JSON：${e.message}`);
    return false;
  }
  if (JSON.stringify(a) !== JSON.stringify(b)) {
    const diff = Object.keys({ ...a, ...b }).filter((k) => JSON.stringify(a[k]) !== JSON.stringify(b[k]));
    console.log(` FAIL  cap 配置副本     APK 里那份和仓库这份不一致（差在 ${diff.join('、')}）`
      + ' → 跑 npm run cap:sync，否则 APK 读的还是旧配置');
    return false;
  }
  console.log('  ok   cap 配置一致     APK 内那份 capacitor.config.json 就是仓库这份');
  return true;
}

/** 同一支颜色写在两个产物里：纸色与印章红既是 CSS 变量，也是安卓 res 里的颜色
 *  （启动图底色、原生弹层的强调色）。改一边不改另一边，实测就是「灰屏 → 纸屏」跳一下，
 *  或者一张纸上冒出 Material 默认青绿的日期选择器。这两处此前没有任何门对着查。 */
function checkInkColors() {
  const css = readFileSync(path.join(root, 'styles.css'), 'utf8');
  const colorFile = path.join(root, 'android', 'app', 'src', 'main', 'res', 'values', 'colors.xml');
  const styleFile = path.join(root, 'android', 'app', 'src', 'main', 'res', 'values', 'styles.xml');
  if (!existsSync(colorFile) || !existsSync(styleFile)) {
    console.log('  --  墨色对账        还没生成 res/values，跳过');
    return true;
  }
  const res = readFileSync(colorFile, 'utf8');
  const theme = readFileSync(styleFile, 'utf8');
  const pick = (re) => (css.match(re) || [])[1];
  const hex = (name) => (res.match(new RegExp(`<color name="${name}">(#[0-9a-fA-F]{6})</color>`)) || [])[1];
  const paper = pick(/--paper:\s*(#[0-9a-fA-F]{6})/);
  const seal = pick(/--seal:\s*(#[0-9a-fA-F]{6})/);
  const splash = hex('splash_background');
  const sealRed = hex('seal_red');
  const runtime = (theme.match(/<style name="AppTheme\.NoActionBar"[\s\S]*?<\/style>/) || [''])[0];
  const bad = [];
  if (!splash || splash.toLowerCase() !== (paper || '').toLowerCase()) bad.push(`启动图底色 ${splash} ≠ 纸色 ${paper}`);
  if (!sealRed) bad.push('res 里没有 seal_red（原生弹层会退回 Material 默认青绿）');
  else if (sealRed.toLowerCase() !== (seal || '').toLowerCase()) bad.push(`seal_red ${sealRed} ≠ --seal ${seal}`);
  if (!/name="colorAccent">@color\/seal_red/.test(runtime)) bad.push('AppTheme.NoActionBar 没把 colorAccent 指到 @color/seal_red');
  // 顺手把 res/values 下每个 XML 都扫一遍「注释里写了两连字符」——那是 XML 的非法记号，
  // aapt2 只回一句 not well-formed，而要等 90 秒的构建才看得见（真事：注释里引了个 CSS 变量名）。
  for (const f of readdirSync(path.join(root, 'android', 'app', 'src', 'main', 'res', 'values'))) {
    if (!f.endsWith('.xml')) continue;
    const p = path.join(root, 'android', 'app', 'src', 'main', 'res', 'values', f);
    for (const c of (readFileSync(p, 'utf8').match(/<!--[\s\S]*?-->/g) || [])) {
      if (/--/.test(c.slice(4, -3))) bad.push(`${f} 的注释里有两个连字符（XML 非法，构建会炸）`);
    }
  }
  if (bad.length) {
    console.log(' FAIL  墨色对账        ' + [...new Set(bad)].join('；'));
    return false;
  }
  console.log(`  ok   墨色对账        纸色 ${paper} / 印章红 ${sealRed} 两边同值，原生弹层跟着这张纸`);
  return true;
}

/** 载荷重量。白名单只逐字节对账「内容对不对」，没人管「背了多重的东西」——
 *  于是 res/ 里躺着 11 张一模一样的 2732×2732 启动位图（2.9MB 资源、解码 29MB 位图），
 *  icons/ 里那张 272KB 的出图源图被整目录拷进 www 一起发给用户，两套测试全绿。
 *  重量也得有门。 */
const MAX_FILE_KB = 64;   // 单个文件超过这个数，就该问一句「非不可吗」

function walk(dir) {
  if (!existsSync(dir)) return [];
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = path.join(dir, e.name);
    return e.isDirectory() ? walk(p) : [p];
  });
}

function checkPayload() {
  let ok = true;
  const res = path.join(root, 'android', 'app', 'src', 'main', 'res');
  for (const [label, dir] of [['www 载荷', path.join(root, 'www')],
                              ['安卓 assets', path.join(root, 'android', 'app', 'src', 'main', 'assets', 'public')],
                              ['安卓 res', res]]) {
    const files = walk(dir);
    if (!files.length) { console.log(`  --  ${label.padEnd(14)}还没构建，跳过`); continue; }
    const fat = files.filter((f) => statSync(f).size > MAX_FILE_KB * 1024)
      .map((f) => `${path.relative(dir, f).replace(/\\/g, '/')} ${Math.round(statSync(f).size / 1024)}KB`);
    const total = Math.round(files.reduce((s, f) => s + statSync(f).size, 0) / 1024);
    if (fat.length) {
      ok = false;
      console.log(` FAIL  ${label.padEnd(14)}有超过 ${MAX_FILE_KB}KB 的文件：${fat.join('、')}`);
    } else {
      console.log(`  ok   ${label.padEnd(14)}${files.length} 个文件共 ${total}KB，最胖的不到 ${MAX_FILE_KB}KB`);
    }
  }
  // 启动图必须是 drawable/splash.xml 那张层叠图。整屏位图一回来就是那 2.9MB 的事故，
  // 而它最容易从 `npm run assets`（@capacitor/assets 按整屏铺图）里悄悄回来。
  const bitmaps = walk(res).filter((f) => /splash\.png$/.test(f));
  if (bitmaps.length) {
    ok = false;
    console.log(` FAIL  启动图          又出现 ${bitmaps.length} 张整屏 splash.png → 启动图是 drawable/splash.xml，别跑 npm run assets 生成它`);
  }
  return ok;
}

/** 上架产物里到底装的是哪一版前端。
 *  这套工程最容易出的事故不是编不过，而是「测试全绿、包却是旧的」：
 *  直接在 android/ 里敲 gradlew 不会先跑 cap sync，打出来的包跑的是上一版前端。
 *  所以这里把 release APK 和 AAB 真的解开，逐个文件和 www/ 比字节。
 *  （AAB 就是 Play 会分发给用户的那份；bundletool 的可执行 jar 这台机器上取不到，
 *   但「包里的前端对不对」这件事不需要拆包工具也能钉死。） */
function checkArtifacts() {
  const files = wwwFiles();
  const out = path.join(root, 'android', 'app', 'build', 'outputs');
  const targets = [
    ['release APK', path.join(out, 'apk/release/app-release.apk')],
    ['AAB', path.join(out, 'bundle/release/app-release.aab')],
  ];
  let ok = true;
  for (const [what, p] of targets) {
    if (!existsSync(p)) {
      console.log(`  --  ${(what + ' 内容').padEnd(16)}还没出包，跳过（gradlew assembleRelease bundleRelease）`);
      continue;
    }
    if (!files) { console.log(` FAIL  ${(what + ' 内容').padEnd(16)}读不到 build-www.mjs 的白名单`); ok = false; continue; }
    const entries = readZipEntries(p);
    const base = what === 'AAB' ? 'base/' : '';
    const drift = [];
    for (const f of files) {
      const want = readFileSync(path.join(root, 'www', f));
      const got = entries.get(`${base}assets/public/${f}`);
      if (!got) drift.push(f + ' (不在包里)');
      else if (Buffer.compare(want, got) !== 0) drift.push(f + ' (字节不同)');
    }
    const icons = [...entries.keys()].filter((k) => k.includes('assets/public/icons/'));
    const stale = icons.filter((k) => !existsSync(path.join(root, k.slice((base + 'assets/public/').length))));
    if (drift.length || stale.length) {
      ok = false;
      console.log(` FAIL  ${(what + ' 内容').padEnd(16)}漂移：${[...drift, ...stale.map((s) => s.split('/').pop() + ' (多余的旧文件)')].join('、')} → 跑 npm run cap:sync 再出包`);
    } else {
      console.log(`  ok   ${(what + ' 内容').padEnd(16)}${files.length} 个文件与 www/ 逐字节一致（含 ${icons.length} 个图标）`);
    }
  }
  return ok;
}

/** 只读 zip 的 store/deflate 条目，不引第三方库。 */
function readZipEntries(p) {
  const buf = readFileSync(p);
  const map = new Map();
  // 从尾部找 EOCD（0x06054b50），拿到中央目录的偏移与条数
  let eocd = -1;
  for (let i = buf.length - 22; i >= 0 && i > buf.length - 65557; i--) {
    if (buf.readUInt32LE(i) === 0x06054b50) { eocd = i; break; }
  }
  if (eocd < 0) return map;
  const count = buf.readUInt16LE(eocd + 10);
  let off = buf.readUInt32LE(eocd + 16);
  for (let n = 0; n < count; n++) {
    if (buf.readUInt32LE(off) !== 0x02014b50) break;
    const method = buf.readUInt16LE(off + 10);
    const compSize = buf.readUInt32LE(off + 20);
    const nameLen = buf.readUInt16LE(off + 28);
    const extraLen = buf.readUInt16LE(off + 30);
    const commentLen = buf.readUInt16LE(off + 32);
    const localOff = buf.readUInt32LE(off + 42);
    const name = buf.slice(off + 46, off + 46 + nameLen).toString('utf8');
    off += 46 + nameLen + extraLen + commentLen;
    if (name.endsWith('/')) continue;
    const lNameLen = buf.readUInt16LE(localOff + 26);
    const lExtraLen = buf.readUInt16LE(localOff + 28);
    const dataStart = localOff + 30 + lNameLen + lExtraLen;
    const raw = buf.slice(dataStart, dataStart + compSize);
    try {
      map.set(name, method === 0 ? raw : zlib.inflateRawSync(raw));
    } catch (_) { /* 个别条目解不开就跳过，比对会把它算成「不在包里」 */ }
  }
  return map;
}

function group(title, suites) {
  console.log(`\n=== ${title} ===`);
  return suites.map(run);
}

function audit() {
  console.log('\n=== 差分 fuzz 深扫（1400 例）===');
  const steps = AUDIT_STEPS.map(run);
  if (steps.some((s) => s === false)) return steps;
  const out = spawnSync('node', ['test/_audit/diff.mjs'], { cwd: root, env, encoding: 'utf8' }).stdout || '';
  const m = out.match(/漂移 (\d+) 条/);
  const zero = !!m && m[1] === '0';
  console.log(`  ${zero ? 'ok  ' : 'FAIL'} ${'fuzz-drift'.padEnd(15)} ${m ? m[1] : '?'} 条（期望 0）`);
  if (!zero) console.log(out.split(/\r?\n/).slice(0, 14).map((l) => '          ' + l).join('\n'));
  return steps.concat([zero]);
}

function main() {
  const which = process.argv[2] || 'fast';
  // sw 是单独一档：改完白名单只想验预缓存清单时，不必等十分钟全套
  const known = { fast: 1, gate: 1, e2e: 1, v06: 1, audit: 1, all: 1, sw: 1, pkg: 1, ship: 1 };
  if (!known[which]) { console.error('未知分组：' + which + '（可用 fast/gate/e2e/v06/audit/all/sw/pkg/ship）'); process.exit(2); }
  if (!PY) console.log('注意：PATH 里找不到 python，所有 .py 那几道门都跑不了（fast 会记成跳过，ship 会直接判失败）。');

  // 出完包只想确认「产物对不对」时跑 pkg，不用等 gate 那十几分钟
  const buildChecks = () => {
    console.log('\n=== 构建产物 ===');
    return [checkWww(), checkAndroid(), checkCapConfig(), checkInkColors(), checkSw(wwwFiles() || []), checkPayload(), checkArtifacts(), checkShortcuts()];
  };

  let results = [];
  if (which === 'sw') { console.log('\n=== sw 预缓存清单 ==='); results = [checkSw(wwwFiles() || [])]; }
  if (which === 'pkg') results = buildChecks();
  // 出包之后、按提交之前那一趟：量「网上那一页 == 仓库里那一页」，顺带实抓一次公开 URL。
  // 商店材料引用的是那个 URL，改了源忘了发布就等于把旧的那句话留在网上继续对所有人可见。
  if (which === 'ship') results = group('上架前：已发布的政策页 == 本地源（要联网、要 gh 登录）', SHIP);
  if (which === 'fast' || which === 'all') results = results.concat(group('快速守门', FAST));
  if (which === 'v06' || which === 'all') results = results.concat(group('0.6.0 浏览器门（要本机 Edge）', V06));
  // v06 那八道也进 all：只跑 fast+e2e 会漏掉这一版新加的全部界面断言
  if (which === 'gate' || which === 'all') results = results.concat(group('守门自检（只改一处必须炸）', GATE));
  if (which === 'e2e' || which === 'all') results = results.concat(group('端到端（要本机 Edge）', E2E));
  if (which === 'audit' || which === 'all') results = results.concat(audit());
  if (which === 'all') results = results.concat(buildChecks());

  // 上架这一档**不许有跳过**：它只在提交前跑一次，「没 python / 没 gh 登录」在别处只是
  // 一条 SKIP，在这里就是「合计 0 通过 / 0 失败」然后退 0 —— 一道会悄悄消失的门，
  // 比没有门更危险（第 60 轮复核点的 P0）。
  if (which === 'ship' && (!results.length || results.some((r) => r === null))) {
    console.log(' FAIL 上架前那一档一步都没验成——0 通过 / 0 失败 就是没有门，不是过了门');
    process.exit(1);
  }

  const skipped = results.filter((r) => r === null).length;
  const bad = results.filter((r) => r === false).length;
  console.log(`\n合计 ${results.length - bad - skipped} 通过 / ${bad} 失败` + (skipped ? ` / ${skipped} 跳过` : ''));

  /* 「一道都没跑成」不许退 0。
   *
   *  以前这里只看 bad：机器上没装 python 时，fast 的七道全记成跳过，
   *  `npm run check` 于是印出「合计 0 通过 / 0 失败」然后**退出码 0**——
   *  谁在 CI 或钩子里拿它当门，看到的就是「全绿」。这一条比某一道门漏跑更坏：
   *  它让整趟检查看起来跑过了。
   *
   *  判据与上面上架那一档同源（那里第 60 轮就踩过同一个坑）：**有跳过可以，
   *  但一道都没跑成就是「没有门」，不是「过了门」。**
   */
  if (!results.length || results.length === skipped) {
    console.log(' FAIL 这一档一步都没验成——0 通过 / 0 失败 就是没有门，不是过了门');
    process.exit(1);
  }
  // 跳过不判失败（没装 python 的机器上 .py 那几道本来就该跳），但如果全部都在跳，
  // 上面那一条已经拦住了。部分跳过只在输出里留一行，让人知道「这一趟少了什么」。
  if (skipped) console.log(`  --  有 ${skipped} 道没跑成（见上面每行末尾的跳过原因），它们的结论这一趟没有`);
  process.exit(bad ? 1 : 0);
}

main();
