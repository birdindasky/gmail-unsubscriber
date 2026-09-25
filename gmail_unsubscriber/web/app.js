const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const token = $('meta[name="session-token"]').content;
const state = {data: null, view: 'subscriptions', filter: 'all', search: '', category: 'all', selected: new Set(), plan: null, executing: false, previewing: false, loading: false, pollTimer: null, connecting: false, detailId: null};
const labels = {verified: '已验证', unverifiable: '无法验证', waiting: '尚未开始', sending: '发送中', cancelled: '已停止', verifying: '核验中',ready: '可提交请求', manual: '需人工处理', blocked: '保护已阻止', accepted: '请求已接受', failed: '提交失败', uncertain: '结果待确认', pending: '处理中', new: '待审阅'};
const verificationLabels = {pending: '待核验', verifying: '核验中', verified: '已验证', unverifiable: '无法验证', none: '无自动方式'};
const methodLabels = {one_click: '一键退订', manual: '需人工处理', none: '未找到退订入口'};
const number = value => new Intl.NumberFormat('zh-CN').format(Number(value) || 0);
const el = (tag, className, text) => {const node = document.createElement(tag); if (className) node.className = className; if (text !== undefined) node.textContent = String(text); return node;};
const setText = (selector, value) => {$(selector).textContent = String(value ?? '');};
const show = (selector, visible = true) => {$(selector).hidden = !visible;};
const dateValue = value => {if (!value) return null; const date = new Date(typeof value === 'number' && value < 1e12 ? value * 1000 : value); return Number.isNaN(date.getTime()) ? null : date;};
const dateLabel = (value, full = false) => {const date = dateValue(value); if (!date) return '暂无记录'; return new Intl.DateTimeFormat('zh-CN', full ? {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'} : {month: 'short', day: 'numeric'}).format(date);};
const isReview = item => !item.protected && item.recommendation === 'review' && !['accepted', 'uncertain', 'pending'].includes(item.status);
const accountMode = () => state.data?.account?.mode || 'live';
const subs = () => state.data?.subscriptions || [];

async function api(path, body) {
  const response = await fetch(path, {method: body === undefined ? 'GET' : 'POST', headers: {'X-Session-Token': token, ...(body === undefined ? {} : {'Content-Type': 'application/json'})}, ...(body === undefined ? {} : {body: JSON.stringify(body)}), credentials: 'same-origin'});
  let data;
  try {data = await response.json();} catch {throw new Error('本机服务返回了无法读取的结果，请刷新页面重试。');}
  if (!response.ok) throw new Error(data?.error?.message || `操作未完成（${response.status}），请稍后再试。`);
  return data;
}

function toast(message, error = false) {
  const node = el('div', `toast${error ? ' error' : ''}`, message);
  $('#toast-region').append(node);
  setTimeout(() => node.remove(), error ? 8000 : 5000);
}

function openDialog(id) {
  const dialog = $(`#${id}`);
  if (!dialog.open) dialog.showModal();
}
function closeDialog(id) {
  // Closing only hides the view; it never cancels or resubmits a job.
  $(`#${id}`).close();
}
function emptyState(title, description, symbol = '↗') {
  const node = el('div', 'empty-state');
  node.append(el('span', 'empty-symbol', symbol), el('strong', '', title), el('p', '', description));
  return node;
}
function loading(message = '正在加载…') {
  const node = el('div', 'loading-state'); node.append(el('span', 'spinner'), el('span', '', message)); return node;
}
function makeButton(text, className, onClick) {
  const button = el('button', className, text); button.type = 'button'; button.addEventListener('click', onClick); return button;
}
function badgeFor(item) {
  if (item.protected) return {text: '受保护', className: 'protected', detail: '保留重要往来'};
  if (item.status === 'accepted') return {text: '请求已接受', className: 'accepted', detail: '等待发件方生效'};
  if (item.status === 'uncertain' || item.status === 'pending') return {text: '结果待确认', className: 'failed', detail: '请勿重复提交'};
  if (item.status === 'failed') return {text: '提交失败', className: 'failed', detail: '查看处理记录'};
  if (item.recommendation === 'keep') return {text: '建议保留', className: 'protected', detail: '可能含重要信息'};
  if (['pending', 'verifying'].includes(item.verification_status)) return {text: verificationLabels[item.verification_status], className: 'review', detail: '审阅时验证签名'};
  if (item.verification_status === 'unverifiable') return {text: '无法验证', className: 'manual', detail: '请人工核对'};
  if (item.method !== 'one_click' || item.recommendation === 'manual') return {text: '需人工处理', className: 'manual', detail: methodLabels[item.method] || '查看原始邮件'};
  return {text: '可以审阅', className: 'review', detail: '已验证 · 支持一键退订'};
}
function avatar(item) {
  const title = item.title || item.sender_email || '?';
  const hash = [...title].reduce((sum, char) => sum + char.codePointAt(0), 0) % 5;
  const node = el('span', `sender-avatar color-${hash}`, [...title][0].toUpperCase()); node.setAttribute('aria-hidden', 'true'); return node;
}
function filteredSubs() {
  return subs().filter(item => {
    if (state.filter === 'review' && !isReview(item)) return false;
    if (state.filter === 'protected' && !item.protected) return false;
    if (state.filter === 'accepted' && item.status !== 'accepted') return false;
    if (state.category !== 'all' && item.category !== state.category) return false;
    return !state.search || `${item.title || ''} ${item.sender_email || ''} ${item.domain || ''} ${(item.sample_subjects || []).join(' ')}`.toLocaleLowerCase().includes(state.search);
  });
}

function renderSubscriptions() {
  const items = filteredSubs();
  const list = $('#subscription-list');
  list.replaceChildren();
  if (!items.length) {
    const hasFilter = state.search || state.category !== 'all' || state.filter !== 'all';
    const empty = emptyState(hasFilter ? '没有符合条件的订阅' : '收件箱的留白，从这里开始', hasFilter ? '试试其他关键词，或清除筛选条件。' : state.data?.account?.connected ? '点击“扫描邮件”，发现值得整理的订阅。' : '连接 Gmail 后，扫描邮件即可看到订阅清单。', hasFilter ? '⌕' : '✳');
    if (hasFilter) empty.append(makeButton('清除筛选', 'button small', clearFilters));
    list.append(empty);
  }
  for (const item of items) {
    const row = el('div', `subscription-row${state.selected.has(item.id) ? ' selected' : ''}`);
    row.dataset.id = item.id;
    const checkboxLabel = el('label', 'check-label');
    const checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.checked = state.selected.has(item.id); checkbox.setAttribute('aria-label', `选择 ${item.title || item.sender_email}`);
    checkbox.addEventListener('change', () => {if (checkbox.checked) {checkbox.checked = selectItem(item.id);} else state.selected.delete(item.id); row.classList.toggle('selected', checkbox.checked); renderSelection();});
    checkboxLabel.append(checkbox);
    const sender = makeButton('', 'sender-button', () => openDetail(item.id));
    sender.setAttribute('aria-label', `查看 ${item.title || item.sender_email} 的订阅详情`);
    const senderText = el('span', 'sender-text'); senderText.append(el('span', 'sender-title', item.title || item.sender_email), el('span', 'sender-email', item.sender_email || item.domain));
    sender.append(avatar(item), senderText);
    const category = el('div', 'category-label'); category.append(el('span', 'category-dot'), el('span', '', item.category || '其他'));
    const volume = el('div', 'volume'); volume.append(el('strong', '', `${number(item.count)} 封`), el('span', '', dateLabel(item.last_seen)));
    const status = badgeFor(item); const statusCell = el('div', 'status-cell'); statusCell.append(el('span', `badge ${status.className}`, status.text), el('span', 'status-method', status.detail));
    const more = makeButton('›', 'row-detail', () => openDetail(item.id)); more.setAttribute('aria-label', `查看 ${item.title || item.sender_email} 详情`);
    row.append(checkboxLabel, sender, category, volume, statusCell, more); list.append(row);
  }
  setText('#subscription-count', number(subs().length));
  setText('#filter-all-count', number(subs().length));
  setText('#filter-review-count', number(subs().filter(isReview).length));
  setText('#list-footer-count', `显示 ${number(items.length)} / ${number(subs().length)} 个订阅`);
  renderSelection();
}
function selectItem(id) {
  if (!state.selected.has(id) && state.selected.size >= 20) {toast('每批最多选择 20 个订阅，请分批审阅。', true); return false;}
  state.selected.add(id); return true;
}
function renderSelection() {
  const visible = filteredSubs();
  const all = $('#select-all');
  const selectedVisible = visible.filter(item => state.selected.has(item.id)).length;
  all.checked = visible.length > 0 && selectedVisible === visible.length;
  all.indeterminate = selectedVisible > 0 && selectedVisible < visible.length;
  all.disabled = !visible.length;
  setText('#selected-count', `已选 ${number(state.selected.size)} / 20`);
  show('#selection-bar', state.view === 'subscriptions' && state.selected.size > 0);
  $('#preview-selection').disabled = state.previewing || state.data?.job?.running || !state.selected.size;
}
function clearFilters() {
  state.filter = 'all'; state.search = ''; state.category = 'all'; $('#search').value = ''; $('#category-filter').value = 'all'; updateFilterButtons(); renderSubscriptions();
}
function updateFilterButtons() {
  $$('[data-filter]').forEach(button => {const active = button.dataset.filter === state.filter; button.classList.toggle('active', active); button.setAttribute('aria-pressed', String(active));});
}
function renderProtections() {
  const container = $('#protected-list'); container.replaceChildren();
  const protections = state.data?.protections || [];
  if (!protections.length) {container.append(emptyState('还没有自定义保护域名', '可以添加工作、银行或其他重要邮件的发件域名。', '✓')); return;}
  for (const protection of protections) {
    const domain = typeof protection === 'string' ? protection : protection.domain;
    const row = el('div', 'protected-row');
    const content = el('div'); content.append(el('h3', '', domain), el('p', '', protection.source === 'default' ? '默认保护 · 覆盖该域名及子域名' : '自定义保护 · 覆盖该域名及子域名'));
    const remove = makeButton('移出保护', 'button small', async () => {await toggleProtection(domain, false, remove);});
    row.append(el('span', 'protection-icon', '✓'), content, remove); container.append(row);
  }
}
function renderActivity() {
  const container = $('#activity-list'); container.replaceChildren();
  const activity = state.data?.activity || [];
  if (!activity.length) {container.append(emptyState('还没有操作记录', '扫描、保护和退订的处理结果会显示在这里。', '↺')); return;}
  for (const item of activity) {
    const row = el('article', 'activity-row');
    const content = el('div', 'activity-content'); const heading = el('h3', '', item.title || '邮件整理');
    if (item.status) heading.append(el('span', `badge ${item.status === 'accepted' ? 'accepted' : ['failed', 'uncertain'].includes(item.status) ? 'failed' : ''}`, labels[item.status] || ({completed: '已完成', protected: '已保护', unprotected: '已移出保护', partial: '部分完成', cancelled: '已停止', ingested: '已保存', success: '已完成'}[item.status] || '已记录')));
    content.append(heading, el('p', '', item.detail || '操作已记录。'));
    const time = el('time', '', dateLabel(item.created_at, true)); const parsedDate = dateValue(item.created_at); if (parsedDate) time.dateTime = parsedDate.toISOString();
    row.append(el('span', 'activity-mark', ['failed', 'uncertain'].includes(item.status) ? '!' : item.kind?.includes('protect') ? '✓' : '↗'), content, time); container.append(row);
  }
}
function renderAccount() {
  const account = state.data.account || {}; const demo = account.mode === 'demo';
  show('#demo-banner', demo); show('#reset-demo', demo);
  const info = $('#account-info'); info.replaceChildren(el('span', `status-dot${account.connected || demo ? '' : ' neutral'}`));
  info.append(el('span', '', account.email || (demo ? '演示邮箱' : account.connected ? 'Gmail 已连接' : '尚未连接 Gmail')));
  if (demo) info.append(el('span', 'account-badge', 'DEMO'));
  show('#connect-state', !account.connected && !demo);
  const setup = state.data.setup || {};
  setText('#credentials-state', `${setup.credentials_path || '启动时指定的客户端文件'} · ${setup.exists ? '文件存在' : '待准备文件'} · ${setup.validity === 'valid' ? '格式已检查' : '凭据尚未通过检查'} · ${account.connected ? '已授权连接' : '尚未授权连接'}`);
  const connectError = state.data.job?.kind === 'connecting' && state.data.job?.phase === 'failed';
  show('#connect-error', connectError);
  setText('#connect-error', connectError ? state.data.job.message : '');
  $('#connect-account').disabled = state.connecting;
  setText('#connect-account', state.connecting ? '等待 Gmail 授权…' : '连接 Gmail');
  $('#open-scan').disabled = Boolean(state.data.job?.running) || (!account.connected && !demo);
  setText('#scan-notice-text', demo ? '当前为演示模式：只扫描合成邮件，不会访问你的真实邮箱。' : '可以随时停止扫描，已发现的订阅会保留。');
}
function scanResultMessage() {
  const job = state.data.job || {}; const scan = state.data.scan || {};
  if (job.kind === 'scanning' && ['failed', 'error'].includes(job.phase)) return job.message || '本次扫描未完成，已有结果已保留。';
  if (scan.message) return scan.message;
  if (job.kind === 'scanning' && job.message) return job.message;
  const phase = job.kind === 'scanning' ? job.phase : scan.status;
  if (phase === 'cancelled') return '扫描已取消，已保留取得的结果。';
  return job.partial || scan.partial ? '已保留部分扫描结果，尚未完整扫描。' : '扫描完成，订阅清单已更新。';
}
function renderJob() {
  const job = state.data.job || {}; const running = Boolean(job.running);
  const connecting = job.kind === 'connecting' || job.phase === 'connecting';
  const currentScan = state.data.scan || {};
  show('#scan-progress', running);
  setText('#scan-progress-title', ({connecting:'等待 Gmail 连接', verifying:'正在核验订阅', executing:'正在提交请求'}[job.kind] || '正在扫描邮件'));
  setText('#cancel-scan', job.phase === 'stopping' ? '正在停止…' : '停止任务');
  $('#cancel-scan').disabled = job.phase === 'stopping';
  show('#reopen-job', ['verifying', 'executing'].includes(job.kind));
  setText('#scan-progress-message', `${job.message || (connecting ? '等待完成 Gmail 授权…' : '正在整理扫描结果…')}${!connecting && job.processed ? ` · 已处理 ${number(job.processed)} 项` : ''}`);
  show('#partial-banner', !connecting && !running && Boolean((job.kind === 'scanning' && job.partial) || currentScan.partial));
  setText('#partial-banner', scanResultMessage());
  const scanDate = currentScan.completed_at || currentScan.finished_at || currentScan.updated_at;
  setText('#list-description', scanDate ? `最近扫描于 ${dateLabel(scanDate, true)} · 按独立订阅归拢` : '按订阅归拢，便于逐个判断。');
  $('#cancel-scan').hidden = connecting;
  const range = currentScan.scope === 'all' ? '所有邮件' : '促销邮件';
  setText('#scan-summary', currentScan.status && currentScan.status !== 'idle' ? `${scanResultMessage()} ${currentScan.started_at ? dateLabel(currentScan.started_at, true) + ' · ' : ''}最近 ${currentScan.days ?? 30} 天 · ${range} · 上限 ${currentScan.limit ?? 100} 封。读取 ${number(currentScan.fetched)} / 已保存 ${number(currentScan.saved ?? currentScan.imported)} / 新增 ${number(currentScan.imported)} / 跳过 ${number(currentScan.skipped)} / 读取失败 ${number(currentScan.failed)} / 重复 ${number(currentScan.duplicates)}。` : '首次扫描默认最近 30 天促销邮件，最多 100 封。零结果不会自动扩大范围。');
  renderActionJob(job);
}
function render() {
  if (!state.data) return;
  const stats = state.data.stats || {};
  setText('#stat-review', number(stats.review)); setText('#stat-messages', number(stats.messages)); setText('#stat-subscriptions', number(stats.subscriptions)); setText('#stat-protected', number(stats.protected)); setText('#stat-accepted', number(stats.accepted)); setText('#nav-count', number(stats.subscriptions));
  const currentIds = new Set(subs().map(item => item.id));
  state.selected = new Set([...state.selected].filter(id => currentIds.has(id)));
  renderAccount(); renderJob(); renderSubscriptions(); renderProtections(); renderActivity();
  if ($('#detail-dialog').open && state.detailId) renderDetail(state.detailId);
}
async function refresh({silent = false} = {}) {
  if (state.loading) return;
  state.loading = true;
  try {
    const previousJob = state.data?.job || {};
    const wasRunning = previousJob.running;
    const wasConnected = state.data?.account?.connected;
    state.data = await api('/api/state');
    const job = state.data.job || {};
    const kind = job.kind || previousJob.kind || (job.phase === 'connecting' || previousJob.phase === 'connecting' || state.connecting ? 'connecting' : 'scanning');
    const connectionFailed = kind === 'connecting' && !job.running && ['failed', 'error', 'cancelled'].includes(job.phase);
    const notifyConnectionFailure = connectionFailed && (state.connecting || wasRunning);
    if (state.data.account?.connected || connectionFailed) state.connecting = false;
    else if (kind === 'connecting' && job.running) state.connecting = true;
    show('#global-error', false); render();
    if (wasRunning && !job.running && kind === 'scanning') toast(scanResultMessage(), ['failed', 'error'].includes(job.phase));
    if (notifyConnectionFailure) toast(job.message || '连接未完成，请重试。', true);
    if (!wasConnected && state.data.account?.connected && accountMode() !== 'demo') toast('Gmail 已连接，可以开始扫描。');
  } catch (error) {
    if (!silent || !state.data) {setText('#global-error-message', error.message); show('#global-error');}
    if (!state.data) $('#subscription-list').replaceChildren(emptyState('暂时无法连接本机服务', '请确认工作台仍在运行，然后点击“重新加载”。', '!'));
  } finally {
    state.loading = false;
    clearTimeout(state.pollTimer);
    if (state.data?.job?.running || state.connecting) state.pollTimer = setTimeout(() => refresh(), 500);
  }
}
function setView(view) {
  if (!['subscriptions', 'protections', 'activity'].includes(view)) view = 'subscriptions';
  state.view = view;
  const titles = {subscriptions: ['订阅整理', '让有用的邮件留下。', '看清订阅，选好去留。每一次操作都由你确认。', 'A LITTLE LESS, A LITTLE LIGHTER'], protections: ['保护名单', '值得保留的，安心留下。', '为重要的往来留一盏绿灯。域名保护在每次执行前都会检查。', 'KEEP WHAT MATTERS'], activity: ['操作记录', '整理过的，都有迹可循。', '查看每项请求的真实结果，分清已接受、未完成与待确认。', 'EVERY STEP, IN SIGHT']};
  const [name, title, description, eyebrow] = titles[view];
  setText('#breadcrumb-current', name); setText('#page-title', title); setText('#page-description', description); setText('#page-eyebrow', eyebrow);
  ['subscriptions', 'protections', 'activity'].forEach(key => show(`#${key}-view`, key === view));
  $$('[data-view]').forEach(button => {const active = button.dataset.view === view; button.classList.toggle('active', active); if (active) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current');});
  renderSelection();
  if (location.hash !== `#${view}`) history.replaceState(null, '', `#${view}`);
}
function renderDetail(id) {
  const item = subs().find(subscription => subscription.id === id);
  if (!item) {closeDialog('detail-dialog'); return;}
  const focusedAction = $('#detail-body').contains(document.activeElement) ? document.activeElement.dataset.action : null;
  const body = $('#detail-body'); body.replaceChildren();
  const hero = el('div', 'detail-hero'); const title = el('h2', '', item.title || item.sender_email); title.id = 'detail-title';
  const badges = el('div', 'detail-badges'); const status = badgeFor(item); badges.append(el('span', `badge ${status.className}`, status.text), el('span', 'badge', item.category || '其他'));
  hero.append(avatar(item), title, el('p', 'detail-email', item.sender_email), badges);
  const facts = el('dl', 'detail-facts');
  for (const [label, value] of [['发现邮件', `${number(item.count)} 封`], ['最近收到', dateLabel(item.last_seen, true)], ['核验状态', verificationLabels[item.verification_status] || '待核验'], ['处理方式', methodLabels[item.method] || '需要人工检查'], ['退订目标站点', item.url_host || '未提供自动退订目标']]) {const pair = el('div'); pair.append(el('dt', '', label), el('dd', '', value)); facts.append(pair);}
  const reason = el('section', 'detail-section'); reason.append(el('h3', '', '为什么这样建议'), el('p', '', item.reason || '请结合邮件内容，决定是否继续接收这个订阅。'));
  const samples = el('section', 'detail-section'); samples.append(el('h3', '', '最近的邮件样本')); const subjects = el('ul'); for (const subject of item.sample_subjects || []) subjects.append(el('li', '', subject)); if (!subjects.children.length) subjects.append(el('li', '', '暂无主题样本')); samples.append(subjects);
  const identity = el('section', 'detail-section'); identity.append(el('h3', '', '订阅识别'), el('p', '', `发件域名：${item.domain || '未知'}`)); if (item.list_id) identity.append(el('p', '', `邮件列表：${item.list_id}`));
  const actions = el('div', 'detail-actions');
  const protect = makeButton(item.protected ? '管理域名保护' : '保护这个域名', 'button', async () => {
    if (item.protected) {closeDialog('detail-dialog'); setView('protections'); $('#protection-domain').focus(); return;}
    await toggleProtection(item.domain, true, protect);
  });
  protect.dataset.action = 'protection';
  actions.append(protect);
  if (!item.protected && !['accepted', 'uncertain', 'pending'].includes(item.status)) {
    const select = makeButton(state.selected.has(item.id) ? '取消选择' : '加入待审阅', 'button primary', () => {if (state.selected.has(item.id)) state.selected.delete(item.id); else selectItem(item.id); renderSubscriptions(); renderDetail(item.id);}); select.dataset.action = 'selection'; actions.append(select);
  }
  actions.append(makeButton(item.method !== 'one_click' && !item.protected ? '在 Gmail 中手动处理 ↗' : '在 Gmail 中查看原邮件 ↗', 'button full-width', () => openManual(item.id)));
  body.append(hero, facts, reason, samples, identity, actions, el('p', 'detail-note', '域名保护会同时覆盖该域名的其他订阅。加入待审阅后，仍需在退订计划中再次确认才会提交。'));
  if (focusedAction) $$('[data-action]', body).find(button => button.dataset.action === focusedAction)?.focus({preventScroll: true});
}
function openDetail(id) {state.detailId = id; renderDetail(id); openDialog('detail-dialog');}
async function toggleProtection(domain, enabled, button) {
  if (button) button.disabled = true;
  try {await api('/api/protections', {domain, enabled}); state.plan = null; await refresh(); toast(enabled ? `${domain} 已加入保护名单。` : `${domain} 已移出保护名单。`); return true;}
  catch (error) {toast(error.message, true); return false;}
  finally {if (button?.isConnected) button.disabled = false;}
}
function summaryItem(value, label, className = '') {const item = el('div', 'review-stat'); item.append(el('strong', className, number(value)), el('span', '', label)); return item;}
function renderReviewItems(items, results = false) {
  const container = $('#review-items'); container.replaceChildren();
  for (const item of items) {
    const row = el('div', 'review-item'); const status = item.status;
    const content = el('div'); content.append(el('h3', '', item.title || item.sender_email || '未命名订阅'));
    if (!results && item.sender_email) content.append(el('p', '', item.sender_email));
    content.append(el('p', '', item.detail || item.reason || (status === 'ready' ? '将向发件方提交一次退订请求。' : '请检查订阅详情。')));
    if (!results && item.url_host) content.append(el('p', '', `目标站点：${item.url_host}`));
    if (status === 'manual') content.append(makeButton('在 Gmail 中查看原邮件 ↗', 'text-button', () => openManual(item.id)));
    row.append(el('span', `review-item-symbol ${status}`, ['ready', 'accepted'].includes(status) ? '✓' : status === 'manual' ? '↗' : status === 'blocked' ? '—' : '!'), content, el('span', `badge ${status === 'ready' ? 'review' : status === 'blocked' ? 'protected' : status === 'uncertain' ? 'failed' : status}`, labels[status] || '待确认')); container.append(row);
  }
}
function renderPlan(plan) {
  setText('#review-back', '返回调整');
  state.plan = plan;
  const summary = plan.summary || {};
  $('#review-summary').replaceChildren(summaryItem(summary.selected, '已选订阅'), summaryItem(summary.ready, '可提交请求', 'accent'), summaryItem(summary.manual, '需人工处理'), summaryItem(summary.blocked, '保护已阻止', 'teal'));
  setText('#review-title', '最后看一眼，再决定。');
  setText('#review-description', accountMode() === 'demo' ? '当前为演示流程，不会发送真实退订请求。' : '只有实际验签通过且未受保护的请求才能提交。');
  setText('#review-footnote', '计划 5 分钟内有效。提交后无法撤回已发出的请求。');
  renderReviewItems(plan.items || []); show('#execute-plan'); $('#execute-plan').disabled = !summary.ready;
  setText('#execute-plan', `确认提交 ${number(summary.ready)} 个请求`);
}
function renderActionJob(job) {
  if (!['verifying', 'executing'].includes(job.kind)) return;
  state.previewing = job.running && job.kind === 'verifying'; state.executing = job.running && job.kind === 'executing';
  show('#stop-action', job.running); $('#stop-action').disabled = job.phase === 'stopping';
  setText('#stop-action', job.phase === 'stopping' ? '正在停止…' : '停止未开始项');
  show('#review-error', Boolean(job.error)); setText('#review-error', job.message || '操作未完成，请重试。');
  if (job.running) {
    state.plan = null; show('#execute-plan', false);
    setText('#review-title', job.kind === 'verifying' ? '正在逐项核验…' : '正在逐项提交…');
    setText('#review-description', job.message || '任务正在处理，刷新页面仅查询进度。');
    setText('#review-footnote', job.kind === 'executing' ? '停止只阻止未开始项；已发送的请求无法撤回。在途结果未知时不会重发。' : '停止后等待当前读取结束或超时，不会生成未完成的执行计划。');
    $('#review-summary').replaceChildren();
    renderReviewItems((job.items || []).map(item => ({...item, detail: item.detail || ({waiting:'尚未开始', sending:'发送中，尚无回执', verifying:'核验中', receipt:'已有回执'}[item.phase] || '尚未开始'), status: item.phase === 'waiting' ? 'waiting' : item.phase === 'sending' ? 'sending' : item.status})), true);
  } else if (job.plan) {renderPlan(job.plan);}
  else if (job.result) {
    state.plan = null; state.selected.clear(); show('#execute-plan', false);
    setText('#review-title', '处理结果，逐项看清。');
    setText('#review-description', accountMode() === 'demo' ? '以下为演示处理结果，未访问外部退订服务。' : '请求已接受不代表已经永久停信。');
    renderReviewItems(job.result.items || [], true); setText('#review-back', '完成');
    setText('#review-footnote', '结果已保存。结果待确认的请求不会自动重试。');
  } else {state.plan = null; show('#execute-plan', false); setText('#review-description', job.message || '任务已停止，未生成执行计划。');}
}
async function previewSelection() {
  if (state.previewing || state.data?.job?.running || !state.selected.size) return;
  state.previewing = true; state.plan = null; renderSelection();
  show('#review-error', false); show('#execute-plan', false); $('#review-items').replaceChildren(loading('正在准备核验任务…')); openDialog('review-dialog');
  try {await api('/api/preview', {ids: [...state.selected]}); await refresh();}
  catch (error) {setText('#review-error', error.message); show('#review-error'); state.previewing = false; renderSelection();}
}
async function executePlan() {
  if (!state.plan || state.executing) return;
  state.executing = true; $('#execute-plan').disabled = true;
  const planId = state.plan.id; state.plan = null;
  try {await api('/api/execute', {plan_id: planId, confirmed: true}); await refresh();}
  catch (error) {setText('#review-error', `${error.message} 请查询任务或操作记录，不会自动重试。`); show('#review-error'); state.executing = false; await refresh();}
}
async function stopJob() {
  try {await api('/api/jobs/cancel', {}); toast('已请求停止；当前在途操作需等待结束或超时，已发送请求无法撤回。'); await refresh();}
  catch (error) {toast(error.message, true);}
}
async function openManual(id) {
  const content = $('#manual-content'); content.replaceChildren(loading('正在获取原邮件位置…')); openDialog('manual-dialog');
  try {
    const result = await api(`/api/manual?id=${encodeURIComponent(id)}`);
    const url = new URL(result.url);
    if (url.origin !== 'https://mail.google.com' || !url.pathname.startsWith('/mail/')) throw new Error('原邮件地址不符合安全要求，无法打开。');
    content.replaceChildren();
    if (accountMode() === 'demo') {content.append(el('p', 'manual-content-note', '这是合成演示邮件，在真实 Gmail 中不存在。演示模式下不会跳转。')); return;}
    const link = el('a', 'button primary manual-link', '打开 Gmail 原邮件 ↗'); link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer'; content.append(link, el('p', 'manual-content-note', '将在新标签页打开 Gmail。请在原邮件中核对发件方和退订入口。'));
  } catch (error) {content.replaceChildren(el('div', 'alert error', error.message));}
}

$$('[data-view]').forEach(button => button.addEventListener('click', () => setView(button.dataset.view)));
window.addEventListener('hashchange', () => setView(location.hash.slice(1)));
$$('[data-close]').forEach(button => button.addEventListener('click', () => closeDialog(button.dataset.close)));
$$('dialog').forEach(dialog => {
  dialog.addEventListener('click', event => {if (event.target === dialog) {const rect = dialog.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) closeDialog(dialog.id);}});
  dialog.addEventListener('close', () => {if (dialog.id === 'detail-dialog') state.detailId = null;});
});
$('#stop-action').addEventListener('click', stopJob);
$('#reopen-job').addEventListener('click', () => openDialog('review-dialog'));
$$('[data-filter]').forEach(button => button.addEventListener('click', () => {state.filter = button.dataset.filter; updateFilterButtons(); renderSubscriptions();}));
$('#search').addEventListener('input', event => {state.search = event.target.value.trim().toLocaleLowerCase(); renderSubscriptions();});
$('#category-filter').addEventListener('change', event => {state.category = event.target.value; renderSubscriptions();});
$('#select-all').addEventListener('change', event => {
  const visible = filteredSubs();
  if (event.target.checked && new Set([...state.selected, ...visible.map(item => item.id)]).size > 20) {toast('当前筛选超过每批 20 个的上限，请缩小筛选或逐项选择；未自动截断。', true); renderSelection(); return;}
  for (const item of visible) {if (event.target.checked) selectItem(item.id); else state.selected.delete(item.id);} renderSubscriptions();
});
$('#clear-selection').addEventListener('click', () => {state.selected.clear(); renderSubscriptions();});
$('#preview-selection').addEventListener('click', previewSelection);
$('#execute-plan').addEventListener('click', executePlan);
$('#retry-state').addEventListener('click', () => refresh());
$('#open-scan').addEventListener('click', () => {show('#scan-error', false); openDialog('scan-dialog');});
$('#scan-form').addEventListener('submit', async event => {
  event.preventDefault(); const button = $('#start-scan'); if (button.disabled) return; button.disabled = true; setText('#start-scan', '正在开始…'); show('#scan-error', false);
  try {await api('/api/scan', {days: Number($('#scan-days').value), limit: Number($('#scan-limit').value), scope: $('#scan-scope').value}); closeDialog('scan-dialog'); await refresh();}
  catch (error) {setText('#scan-error', error.message); show('#scan-error');}
  finally {button.disabled = false; setText('#start-scan', '开始扫描 →');}
});
$('#cancel-scan').addEventListener('click', stopJob);
$('#protection-form').addEventListener('submit', async event => {
  event.preventDefault(); const input = $('#protection-domain'); const domain = input.value.trim().toLowerCase(); const button = $('button', event.currentTarget);
  if (!domain) return;
  if (await toggleProtection(domain, true, button)) input.value = '';
});
$('#reset-demo').addEventListener('click', async event => {
  const button = event.currentTarget; button.disabled = true;
  try {await api('/api/demo/reset', {}); state.selected.clear(); state.plan = null; clearFilters(); await refresh(); toast('演示数据已重置，可以重新体验。');}
  catch (error) {toast(error.message, true);} finally {button.disabled = false;}
});
$('#connect-account').addEventListener('click', async () => {
  if (accountMode() === 'demo') {toast('请使用真实邮箱模式启动工作台，再连接 Gmail。'); return;}
  state.connecting = true; renderAccount();
  try {await api('/api/connect', {}); toast('请在 Gmail 授权页面完成连接。'); await refresh();}
  catch (error) {state.connecting = false; toast(error.message, true); renderAccount();}
});
document.addEventListener('visibilitychange', () => {if (!document.hidden && state.data) refresh({silent: true});});
setView(location.hash.slice(1) || 'subscriptions');
refresh();
