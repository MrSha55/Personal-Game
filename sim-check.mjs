// 格斗模拟层自检：把 meme-fight.html 里"模拟层"那段原样抠出来在 Node 里跑，不需要浏览器。
// 用法: node sim-check.mjs     （改了招式数据/判定后跑一下，全部 ok 才算没改坏）
import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';

const html = readFileSync(new URL('./meme-fight.html', import.meta.url), 'utf8');
const src = html.slice(html.indexOf('// ============ 模拟层'), html.indexOf('// ============ 输入层'));
const sim = new Function('faceDemon', 'faceCat', 'faceDoge', `${src}; return { L, R, U, D, A, B, CHARS, MOVES, METER, newMatch, step, moveOf };`)();
const { L, R, U, D, A, B, CHARS, METER, newMatch, step } = sim;

// 开打：跳过 ready，两人摆到指定位置（1P 在左朝右）
function fight(c0, c1, dist) {
  const s = newMatch([c0, c1]);
  s.phase = 'fight';
  s.f[0].x = -dist / 2; s.f[1].x = dist / 2;
  return s;
}
// 跑 n 帧，每帧输入由函数给出；收集特效事件
function run(s, n, in0 = () => 0, in1 = () => 0) {
  const fx = [];
  for (let i = 0; i < n; i++) { step(s, [in0(i), in1(i)]); fx.push(...s.fx.map(e => e.t)); }
  return fx;
}
const tap = (k, at = 0) => i => (i === at ? k : 0);
const ok = (name, cond) => { assert.ok(cond, name); console.log('ok -', name); };

// 1. 出手距离往外延：轻拳 1.55、重脚 1.95 远都能打到（以前分别只有 1.33 / 1.58）
ok('轻拳够得到 1.55', run(fight(0, 0, 1.55), 20, tap(A)).includes('hit'));
ok('重脚够得到 1.95', run(fight(0, 0, 1.95), 30, tap(B)).includes('hit'));

// 2. 下段踢：站防挡不住，蹲防挡得住
ok('下段踢打穿站防', run(fight(0, 0, 1.3), 30, i => i < 2 ? D : D | B, () => R).includes('hit'));
ok('下段踢被蹲防挡住', run(fight(0, 0, 1.3), 30, i => i < 20 ? D : D | B, () => R | D).includes('block'));

// 3. 完美格挡：快打到时才按后 = parry；一直按着后 = 普通格挡
ok('完美格挡', run(fight(0, 0, 1.6), 30, tap(B), i => (i >= 4 ? R : 0)).includes('parry'));
{
  const s = fight(0, 0, 1.6); s.f[0].x = 4.9; s.f[1].x = 6.5; // 2P 贴墙，按着后退走不动
  const fx = run(s, 60, tap(B, 30), () => R);
  ok('一直按着后只是普通格挡', fx.includes('block') && !fx.includes('parry'));
}
{ // 弹开后对手硬直，自己马上能动
  const s = fight(0, 0, 1.6);
  run(s, 32, tap(B), i => (i >= 4 && i < 12 ? R : 0)); // 定格 14 帧后：对手还在硬直，自己已经回到待机
  ok('完美格挡后对手被弹开', s.f[0].act === 'hit' && s.f[1].act !== 'block');
}

// 4. 空中拳/脚
{
  const s = fight(0, 0, 1.6);
  run(s, 6, i => (i === 0 ? U : i === 3 ? A : 0));
  ok('空中拳', s.f[0].act === 'attack' && s.f[0].move === 'ap');
  const t = fight(0, 0, 1.6);
  run(t, 6, i => (i === 0 ? U : i === 3 ? B : 0));
  ok('空中踢', t.f[0].act === 'attack' && t.f[0].move === 'ak');
}

// 5. 必杀技和大招（每个角色都能放出来）
const QCF_J = [D, D, D | R, R, R | A], BF_K = [L, L, R, R | B];
for (let c = 0; c < CHARS.length; c++) {
  const a = fight(c, 0, 6); run(a, QCF_J.length, i => QCF_J[i]);
  const b = fight(c, 0, 6); run(b, BF_K.length, i => BF_K[i]);
  const s = fight(c, 0, 6); s.f[0].meter = METER;
  const fx = run(s, 2, tap(A | B));
  ok(`${CHARS[c].name}：必杀1 / 必杀2 / 大招`, a.f[0].move === 's1' && b.f[0].move === 's2' && s.f[0].move === 'su' && fx.includes('super') && s.f[0].meter === 0);
}
{
  const s = fight(0, 0, 3); s.f[0].meter = 50;
  run(s, 2, tap(A | B));
  ok('气不够放不出大招', s.f[0].move === 'lp');
}
{ // J 和 K 差 2 帧按也算同时按
  const s = fight(0, 0, 3); s.f[0].meter = METER;
  run(s, 4, i => (i === 0 ? A : i === 2 ? A | B : 0));
  ok('J、K 没按齐也能出大招', s.f[0].move === 'su');
}

// 6. 连段：轻拳打中接重脚
{
  const s = fight(0, 0, 1.4);
  const fx = run(s, 40, i => (i === 0 ? A : i === 6 ? B : 0));
  ok('轻拳接重脚两下都中', fx.filter(t => t === 'hit').length === 2 && s.f[1].combo === 2);
}

// 7. 移动优先：重脚收招后半段按方向直接能走
{
  const s = fight(0, 0, 5);
  run(s, 24, i => (i === 0 ? B : i > 16 ? L : 0)); // 重脚整套 29 帧，第 23 帧就走了
  ok('收招后半段可以直接走开', s.f[0].act === 'walk');
}

// 8. 乱按压力测试：所有角色两两对打，数值不出 NaN、血量不越界、不抛异常
let seed = 1;
const rnd = () => (seed = seed * 16807 % 2147483647) / 2147483647;
for (let a = 0; a < CHARS.length; a++) for (let b = 0; b < CHARS.length; b++) {
  const s = newMatch([a, b]);
  for (let i = 0; i < 6000 && s.phase !== 'over'; i++) {
    step(s, [rnd() * 64 | 0, rnd() * 64 | 0]);
    for (const f of s.f) assert.ok(Number.isFinite(f.x + f.y + f.vx + f.vy) && f.hp >= 0 && f.hp <= 100 && f.meter >= 0 && f.meter <= METER, `${a}v${b} 第 ${i} 帧数值异常`);
  }
}
ok('乱按压力测试', true);
