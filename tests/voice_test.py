# Browser tests (needs: pip install playwright && playwright install chromium). Run: python3 tests/voice_test.py
import os as _o
ROOT=_o.path.dirname(_o.path.dirname(_o.path.abspath(__file__)))
import subprocess,time,os
from playwright.sync_api import sync_playwright
env=dict(os.environ,PORT='8798',OLMA_DATA='/tmp/olma-voice-data',OLLAMA_URL='http://127.0.0.1:9')
srv=subprocess.Popen(['node','server/server.js'],cwd=ROOT,env=env,stdout=subprocess.DEVNULL); time.sleep(1)
STUB="""
window.__n=0;
window.SpeechRecognition=window.webkitSpeechRecognition=class{start(){const n=++window.__n;setTimeout(()=>{ if(n==1){this.onresult({results:[Object.assign([{transcript:'hello olma'}],{isFinal:true})]});} setTimeout(()=>this.onend&&this.onend(),150)},400)}stop(){this.onend&&this.onend()}};
window.SpeechSynthesisUtterance=window.SpeechSynthesisUtterance||function(){};
const sp={cancel(){},speak(u){setTimeout(()=>u.onend&&u.onend(),600)}};
Object.defineProperty(window,'speechSynthesis',{value:sp});
"""
res=[]
def chk(n,c): res.append(c); print(('PASS ' if c else 'FAIL ')+n)
with sync_playwright() as p:
    b=p.chromium.launch(); pg=b.new_page(viewport={'width':1100,'height':700}); errs=[]; pg.on('pageerror',lambda e:errs.append(str(e)))
    pg.add_init_script(STUB); pg.goto('http://127.0.0.1:8798'); pg.wait_for_selector('#greet')
    pg.evaluate("window.__st=[];new MutationObserver(()=>{const c=document.querySelector('#voice').className;const l=window.__st;if(l[l.length-1]!==c)l.push(c)}).observe(document.querySelector('#voice'),{attributes:true,attributeFilter:['class']})")
    pg.click('#go'); chk('overlay opens', pg.is_visible('#voice'))
    pg.screenshot(path='/tmp/s5_voice.png')
    pg.wait_for_function("window.__st.includes('speaking')",timeout=10000)
    st=pg.evaluate("window.__st"); print(st)
    chk('state sequence listening->thinking->speaking', st.index('listening')<st.index('thinking')<st.index('speaking'))
    pg.wait_for_function("window.__st.lastIndexOf('listening')>window.__st.indexOf('speaking')",timeout=10000); chk('loops back to listening (hands-free)', True)
    pg.click('#vmute'); pg.wait_for_function("document.querySelector('#voice').className===''",timeout=3000); chk('mute pauses listening', True)
    pg.click('#vclose'); chk('close button works', not pg.is_visible('#voice'))
    txt=pg.evaluate("[...document.querySelectorAll('.m')].map(m=>m.innerText).join('|')"); chk('conversation saved in chat', 'hello olma' in txt and 'demo mode' in txt)
    chk('no JS errors', not errs); print(errs); b.close()
srv.terminate(); raise SystemExit(0 if all(res) else 1)
