const chatEl = document.getElementById('chat');
const inputEl = document.getElementById('input');
const sendBtn = document.getElementById('send');
const quickEl = document.getElementById('quick');
const typingEl = document.getElementById('typing');
const successEl = document.getElementById('success');
const btnReset = document.getElementById('btn-reset');

let sessionId = localStorage.getItem('abramenko_session');
if (!sessionId) {
  sessionId = (crypto.randomUUID && crypto.randomUUID()) || String(Date.now()) + Math.random().toString(36).slice(2);
  localStorage.setItem('abramenko_session', sessionId);
}
let isSending = false;
let isDone = false;

function escapeText(s){
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}
function timeNow(){
  return new Date().toLocaleTimeString('ru-RU',{hour:'2-digit', minute:'2-digit'});
}
function addBubble(text, who){
  const div = document.createElement('div');
  div.className = `bubble ${who}`;
  // безопасно: экранируем, но сохраняем переносы
  const safe = escapeText(text).replace(/\n/g,'<br>');
  div.innerHTML = `<div>${safe}</div><div class="meta">${timeNow()} ${who==='user' ? '✓✓' : ''}</div>`;
  chatEl.appendChild(div);
  chatEl.scrollTop = chatEl.scrollHeight;
}
function showTyping(v){ typingEl.hidden = !v; if(v) chatEl.scrollTop = chatEl.scrollHeight; }
function renderButtons(btns){
  quickEl.innerHTML = '';
  (btns||[]).forEach(label=>{
    const b = document.createElement('button');
    b.textContent = label;
    b.addEventListener('click', ()=> send(label));
    quickEl.appendChild(b);
  });
}
function setDoneUI(done){
  isDone = done;
  if(done){
    successEl.hidden = false;
    renderButtons([]);
    inputEl.disabled = true;
    sendBtn.disabled = true;
  } else {
    successEl.hidden = true;
    inputEl.disabled = false;
    sendBtn.disabled = false;
    inputEl.focus();
  }
}
async function apiChat(message){
  const r = await fetch('/api/chat', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({session_id: sessionId, message})
  });
  if(!r.ok) throw new Error('api '+r.status);
  return r.json();
}
async function apiReset(){
  const r = await fetch('/api/reset', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({session_id: sessionId})
  });
  return r.json();
}
async function send(text){
  const msg = (text ?? inputEl.value).trim();
  if(!msg || isSending) return;
  if(isDone) return;
  isSending = true;
  inputEl.value='';
  sendBtn.disabled = true;
  quickEl.innerHTML='';
  addBubble(msg, 'user');
  showTyping(true);
  try{
    const data = await apiChat(msg);
    showTyping(false);
    addBubble(data.message, 'bot');
    renderButtons(data.buttons);
    setDoneUI(!!data.done);
  }catch(e){
    showTyping(false);
    addBubble('Не удалось отправить. Проверьте соединение и попробуйте ещё раз.', 'bot');
    sendBtn.disabled = false;
  }finally{
    isSending = false;
    if(!isDone) { sendBtn.disabled=false; inputEl.focus(); }
  }
}

// init
sendBtn.addEventListener('click', ()=> send());
inputEl.addEventListener('keydown', e=>{
  if(e.key==='Enter' && !e.shiftKey){ e.preventDefault(); send(); }
});
btnReset.addEventListener('click', async ()=>{
  chatEl.innerHTML='';
  setDoneUI(false);
  quickEl.innerHTML='';
  try{
    const data = await apiReset();
    addBubble(data.message, 'bot');
    renderButtons(data.buttons);
    setDoneUI(!!data.done);
  }catch{
    addBubble('Здравствуйте! 👋 Я помогу подобрать услугу и записаться в студию. Чем могу помочь?', 'bot');
    renderButtons(["Хочу записаться","Сколько стоит балаяж?","Где вы находитесь?"]);
  }
});

// старт: приветствие из бота
(async()=>{
  try {
    const h = await fetch('/api/health');
    if (!h.ok) document.getElementById('wa-status').textContent = 'offline • попробуйте позже';
  } catch { document.getElementById('wa-status').textContent = 'offline • попробуйте позже'; }
  showTyping(true);
  try{
    const data = await apiChat('');
    showTyping(false);
    addBubble(data.message, 'bot');
    renderButtons(data.buttons);
    setDoneUI(!!data.done);
  }catch{
    showTyping(false);
    addBubble('Здравствуйте! 👋 Я помогу подобрать услугу и записаться в студию. Чем могу помочь?', 'bot');
    renderButtons(["Хочу записаться","Сколько стоит балаяж?","Где вы находитесь?"]);
  }
})();
