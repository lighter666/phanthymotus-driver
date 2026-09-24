const $ = (id) => document.getElementById(id);
let selected = localStorage.getItem('meeting-id') || '';
let current = null;
const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

async function api(action, fields = {}) {
  const response = await fetch('/api/action', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({action,...fields})});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '操作失败');
  return data;
}
function flash(message, error = false) {
  $('flash').textContent = message;
  $('flash').className = error ? 'error' : '';
  setTimeout(() => { if ($('flash').textContent === message) $('flash').textContent = ''; }, 5500);
}
async function perform(action, fields = {}) {
  try { const result = await api(action, {meeting_id:selected,...fields}); await refresh(); return result; }
  catch (error) { flash(error.message, true); return null; }
}
function peopleOptions(people) { return people.map(p => `<option value="${escapeHtml(p.name)}">${escapeHtml(p.name)}</option>`).join(''); }
function render(meeting, tasks, audioStatus) {
  current = meeting;
  $('empty').hidden = true; $('detail').hidden = false;
  $('meeting-id').textContent = `会议 ${meeting.id.slice(0,8)}`;
  $('meeting-title').textContent = meeting.title;
  const statusNames = {planned:'会前准备',active:'会议进行中',ended:'会议已结束'};
  $('meeting-status').textContent = statusNames[meeting.status];
  $('meeting-status').className = `badge ${meeting.status === 'active' ? 'ok' : ''}`;
  $('preflight-status').textContent = meeting.preflight_ready ? '人员和设备均已确认' : '尚有人员或设备未确认；不能标记为已就绪';
  $('preflight-status').className = meeting.preflight_ready ? 'tag ok' : 'tag warn';
  $('attendees').innerHTML = meeting.attendees.map(p => `<div class="row"><span>${escapeHtml(p.name)} <span class="tag ${p.confirmed?'ok':'warn'}">${p.confirmed?'已确认':'未确认'}</span></span><button data-check="person" data-name="${escapeHtml(p.name)}" data-value="${!p.confirmed}" ${meeting.status==='ended'?'disabled':''}>${p.confirmed?'撤销':'确认'}</button></div>`).join('');
  $('equipment').innerHTML = meeting.equipment.map(e => `<div class="row"><span class="row-main">${escapeHtml(e.name)} <span class="tag ${e.confirmed?'ok':'warn'}">${e.confirmed?'已确认':'未确认'}</span>${e.report ? `<small>${escapeHtml(e.report.summary || e.report.status)}</small>`:''}</span>${e.source==='manual'?`<button data-check="equipment" data-name="${escapeHtml(e.name)}" data-value="${!e.confirmed}" ${meeting.status==='ended'?'disabled':''}>${e.confirmed?'撤销':'确认'}</button>`:''}</div>`).join('');
  $('check-robot').disabled = meeting.status === 'ended';
  $('begin-meeting').disabled = meeting.status !== 'planned';
  $('end-meeting').disabled = meeting.status !== 'active';
  $('timer').textContent = meeting.remaining_seconds === null ? '--:--' : `${String(Math.floor(meeting.remaining_seconds/60)).padStart(2,'0')}:${String(meeting.remaining_seconds%60).padStart(2,'0')}`;
  $('agenda').innerHTML = meeting.agenda.map((a,i) => `<div class="row ${meeting.status==='active'&&i===meeting.agenda_index?'current':''}"><span>${i+1}. ${escapeHtml(a.title)}</span><span>${a.minutes} 分钟</span></div>`).join('');
  $('next-agenda').disabled = meeting.status !== 'active' || meeting.agenda_index >= meeting.agenda.length-1;
  $('audio-status').textContent = `Bumi 播报：${audioStatus}`;
  $('decisions').innerHTML = meeting.decisions.map(d => `<div class="row">${escapeHtml(d.text)}</div>`).join('') || '<p class="muted">尚无决策</p>';
  $('drafts').innerHTML = meeting.drafts.map(d => `<div class="row"><span>${escapeHtml(d.text)}</span><span class="tag ${d.task_id?'ok':'warn'}">${d.task_id?'已派发':'待确认'}</span></div>`).join('') || '<p class="muted">尚无草稿</p>';
  const pending = meeting.drafts.filter(d => !d.task_id);
  const taskForm = $('task-form').elements;
  const selection = {draft_id:taskForm.draft_id.value,owner:taskForm.owner.value,reviewer:taskForm.reviewer.value};
  taskForm.draft_id.innerHTML = pending.map(d => `<option value="${d.id}">${escapeHtml(d.text)}</option>`).join('');
  taskForm.owner.innerHTML = peopleOptions(meeting.attendees);
  taskForm.reviewer.innerHTML = peopleOptions(meeting.attendees);
  for (const [field,value] of Object.entries(selection)) {
    if ([...taskForm[field].options].some(option => option.value === value)) taskForm[field].value = value;
  }
  $('task-form').querySelector('button').disabled = pending.length === 0;
  $('decision-form').querySelector('button').disabled = meeting.status !== 'active';
  $('draft-form').querySelector('button').disabled = meeting.status !== 'active';
  $('task-count').textContent = `${tasks.length} 项正式任务`;
  $('tasks').innerHTML = tasks.map(t => `<article class="task"><div class="heading"><strong>${escapeHtml(t.title)}</strong><span class="tag ${t.status==='accepted'?'ok':t.attention==='逾期'?'bad':'warn'}">${escapeHtml(t.attention || ({open:'进行中',submitted:'待验收',returned:'已退回',accepted:'已通过'}[t.status]))}</span></div><p>负责人：${escapeHtml(t.owner)}　截止：${escapeHtml(new Date(t.deadline).toLocaleString('zh-CN'))}　验收人：${escapeHtml(t.reviewer)}</p><p>交付物：${escapeHtml(t.deliverable)}<br>验收标准：${escapeHtml(t.acceptance)}</p>${t.evidence?`<p>完成说明/证据：${escapeHtml(t.evidence)}</p>`:''}${t.review_note?`<p>退回原因：${escapeHtml(t.review_note)}</p>`:''}<div class="actions">${['open','returned'].includes(t.status)?`<button data-task="submit" data-id="${t.id}" data-actor="${escapeHtml(t.owner)}">提交完成</button>`:''}${t.status==='submitted'?`<button data-task="approve" data-id="${t.id}" data-actor="${escapeHtml(t.reviewer)}">验收通过</button><button class="secondary" data-task="return" data-id="${t.id}" data-actor="${escapeHtml(t.reviewer)}">退回</button>`:''}</div></article>`).join('') || '<p class="muted">尚无正式任务。行动项草稿经主持人确认后会出现在这里。</p>';
}
async function refresh() {
  try {
    const meetings = await (await fetch('/api/meetings')).json();
    $('meetings').innerHTML = meetings.map(m => `<button class="meeting-link ${m.id===selected?'active':''}" data-meeting="${m.id}">${escapeHtml(m.title)}<small>${m.status==='active'?'进行中':m.status==='ended'?'已结束':'会前准备'}</small></button>`).join('') || '<p class="muted">暂无会议</p>';
    if (!selected && meetings.length) selected = meetings[0].id;
    if (selected) {
      const response = await fetch(`/api/meetings/${encodeURIComponent(selected)}`);
      if (response.ok) { const data = await response.json(); render(data.meeting,data.tasks,data.audio_status); }
    }
  } catch (error) { flash(`无法读取任务板：${error.message}`, true); }
}
document.addEventListener('click', async event => {
  const meeting = event.target.closest('[data-meeting]');
  if (meeting) {selected=meeting.dataset.meeting;localStorage.setItem('meeting-id',selected);await refresh();return;}
  const check = event.target.closest('[data-check]');
  if (check) {await perform(check.dataset.check==='person'?'check_person':'check_equipment',{name:check.dataset.name,confirmed:check.dataset.value==='true'});return;}
  const task = event.target.closest('[data-task]');
  if (task) {
    const actor = prompt('请填写操作人姓名（演示版不做账号认证）：',task.dataset.actor);
    if (!actor) return;
    if (task.dataset.task==='submit') {const evidence=prompt('完成说明或证据链接：');if(evidence) await perform('submit_task',{task_id:task.dataset.id,actor,evidence});}
    else if (task.dataset.task==='approve') await perform('review_task',{task_id:task.dataset.id,actor,approved:true});
    else {const note=prompt('请输入退回原因：');if(note) await perform('review_task',{task_id:task.dataset.id,actor,approved:false,note});}
  }
});
$('create-form').addEventListener('submit', async event => {
  event.preventDefault();const form=new FormData(event.target);
  const lines = name => String(form.get(name)||'').split('\n').map(x=>x.trim()).filter(Boolean);
  try {
    const agenda=lines('agenda').map(x=>{const pos=x.lastIndexOf(',');return {title:x.slice(0,pos).trim(),minutes:Number(x.slice(pos+1).trim())}});
    const meeting=await api('create',{title:form.get('title'),attendees:lines('attendees'),agenda,equipment:lines('equipment')});
    selected=meeting.id;localStorage.setItem('meeting-id',selected);event.target.reset();flash('会议已创建');await refresh();
  } catch(error) {flash(error.message,true);}
});
$('decision-form').addEventListener('submit', async event => {event.preventDefault();const text=event.target.elements.text.value;if(await perform('record_decision',{text}))event.target.reset();});
$('draft-form').addEventListener('submit', async event => {event.preventDefault();const text=event.target.elements.text.value;if(await perform('record_draft',{text}))event.target.reset();});
$('task-form').addEventListener('submit', async event => {
  event.preventDefault();const form=event.target.elements;
  if (!confirm('确认将这项任务正式派发，并使用填写的负责人、截止时间和验收标准？')) return;
  const fields={draft_id:form.draft_id.value,owner:form.owner.value,deadline:new Date(form.deadline.value).toISOString(),deliverable:form.deliverable.value,reviewer:form.reviewer.value,acceptance:form.acceptance.value,confirmed:true};
  if(await perform('confirm_task',fields)) {flash('正式任务已创建');event.target.reset();}
});
$('check-robot').onclick=async()=>{const result=await perform('check_robot');if(result)flash(result.equipment.find(e=>e.name==='Bumi').report.summary || 'Bumi 健康检查完成');};
$('begin-meeting').onclick=()=>perform('begin_meeting');
$('end-meeting').onclick=()=>perform('end_meeting');
$('next-agenda').onclick=()=>perform('next_agenda');
refresh();setInterval(refresh,1000);
