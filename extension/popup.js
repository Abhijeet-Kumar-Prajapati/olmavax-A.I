const $ = s => document.querySelector(s);
chrome.storage.local.get(['srv', 'pending'], v => { if (v.srv) $('#srv').value = v.srv; if (v.pending) { $('#q').value = v.pending; chrome.storage.local.remove('pending'); chrome.action.setBadgeText({ text: '' }); } });
async function ask(text) {
  const srv = $('#srv').value.replace(/\/$/, ''); chrome.storage.local.set({ srv }); $('#out').textContent = '\u2026';
  try {
    const r = await fetch(srv + '/api/chat', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ messages: [{ role: 'user', content: text }] }) });
    const rd = r.body.getReader(), dec = new TextDecoder(); let buf = '', out = '';
    for (;;) { const { done, value } = await rd.read(); if (done) break; buf += dec.decode(value, { stream: true }); let i;
      while ((i = buf.indexOf('\n\n')) >= 0) { const l = buf.slice(0, i); buf = buf.slice(i + 2); if (l.startsWith('data:')) { const j = JSON.parse(l.slice(5)); if (j.delta) out += j.delta; if (j.error) out += '\n\u{26A0}\u{FE0F} ' + j.error; $('#out').textContent = out; } } }
  } catch (e) { $('#out').textContent = 'Cannot reach Olmavax server: ' + e.message + '\nStart it with: npm start'; }
}
async function pageText(selOnly) {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const [{ result }] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: so => so ? String(getSelection()) : document.body.innerText.slice(0, 8000), args: [selOnly] });
  return result;
}
$('#ask').onclick = () => ask($('#q').value);
$('#sum').onclick = async () => ask('Summarize this web page in clear bullet points:\n\n' + await pageText(false));
$('#sel').onclick = async () => { $('#q').value = await pageText(true); };