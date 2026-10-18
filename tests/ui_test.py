# Browser tests (needs: pip install playwright && playwright install chromium). Run: python3 tests/ui_test.py
import os as _o
ROOT=_o.path.dirname(_o.path.dirname(_o.path.abspath(__file__)))
import subprocess, time, os, sys
from playwright.sync_api import sync_playwright
env=dict(os.environ, PORT='8795', OLMA_DATA='/tmp/olma-ui-data', OLLAMA_URL='http://127.0.0.1:9')
srv=subprocess.Popen(['node','server/server.js'],cwd=ROOT,env=env); time.sleep(1.2)
errs=[]; ok=[]
def check(name,cond):
    ok.append((name,bool(cond))); print(('PASS ' if cond else 'FAIL ')+name)
try:
  with sync_playwright() as p:
    b=p.chromium.launch(); pg=b.new_page(viewport={'width':1280,'height':760})
    pg.on('pageerror',lambda e:errs.append(str(e))); pg.on('console',lambda m: errs.append(m.text) if m.type=='error' else None)
    pg.on('dialog',lambda d:(errs.append('dialog:'+d.message),d.dismiss()))
    pg.goto('http://127.0.0.1:8795'); pg.wait_for_selector('#greet')
    check('home visible, msgs hidden', pg.is_visible('#home') and not pg.is_visible('#msgs'))
    g=pg.inner_text('#greet'); check('greeting text', 'ABHIJEET' in g or 'mind' in g)
    check('composer inside home', pg.evaluate("document.querySelector('#homeComposer #comp')!==null"))
    check('go button shows voice icon when empty', pg.evaluate("document.querySelector('#go svg rect')!==null"))
    pg.screenshot(path='/tmp/s1_home.png')
    pg.click('#plus'); check('plus menu opens with 9 items', pg.locator('#menu2 button').count()==9 and pg.is_visible('#menu2'))
    pg.screenshot(path='/tmp/s2_menu.png')
    pg.click('#menu2 [data-act=image]'); check('image chip shown', pg.is_visible('#chip'))
    pg.fill('#input','a red fox in a forest'); check('go shows send arrow after typing', pg.evaluate("document.querySelector('#go svg path')!==null"))
    pg.keyboard.press('Enter'); pg.wait_for_selector('img.gen',timeout=8000)
    check('image generated (demo svg)', pg.locator('img.gen').count()==1)
    check('layout switched: composer docked', pg.evaluate("document.querySelector('#dock #comp')!==null") and not pg.is_visible('#home'))
    pg.fill('#input','please debug this python code'); pg.keyboard.press('Enter')
    pg.wait_for_function("document.querySelectorAll('.m.assistant').length>=2 && document.querySelectorAll('.acts').length>=2",timeout=8000)
    t=pg.locator('.m.assistant').nth(1).inner_text(); check('streamed reply + agent tag', 'Code Engineer' in t and 'demo mode' in t)
    pg.fill('#input','/calc 6*7'); pg.keyboard.press('Enter'); pg.wait_for_function("document.body.innerText.includes('= 42')",timeout=5000); check('slash tool in UI', True)
    pg.screenshot(path='/tmp/s3_chat.png')
    # file attach (text + image)
    open('/tmp/n.txt','w').write('hello file')
    pg.set_input_files('#file',['/tmp/n.txt']); check('text attachment chip', pg.locator('.att').count()==1)
    pg.fill('#input','summarize'); pg.keyboard.press('Enter'); pg.wait_for_function("document.querySelectorAll('.acts').length>=4",timeout=8000)
    check('attachment shown in user bubble', 'n.txt' in pg.locator('.m.user').last.inner_text())
    # think toggle, new chat, search mode offline fallback
    pg.click('#newChat'); check('new chat returns to home', pg.is_visible('#home'))
    pg.click('#sugg [data-mode=search]'); check('suggestion sets search chip', 'Web search' in pg.inner_text('#chip'))
    pg.fill('#input','latest news'); pg.keyboard.press('Enter'); pg.wait_for_function("document.querySelectorAll('.m.assistant').length>=1 && document.querySelector('.m.assistant').innerText.includes('Olma General')",timeout=15000)
    check('search offline falls back gracefully', 'unavailable' in pg.locator('.m.assistant').first.inner_text() or 'demo' in pg.locator('.m.assistant').first.inner_text())
    pg.click('#newChat')  # voice mode is covered by tests/voice_test.py (needs a speech stub in headless)
    # modals
    for sel,name in [('#bMem','memory'),('#bSet','settings')]:
        pg.click(sel); check(name+' modal opens', pg.is_visible('#modal')); pg.click('#mclose')
    pg.click('#plus'); pg.click('#menu2 [data-act=sketch]'); check('sketch canvas opens', pg.is_visible('#cv'))
    box=pg.locator('#cv').bounding_box(); pg.mouse.move(box['x']+50,box['y']+50); pg.mouse.down(); pg.mouse.move(box['x']+200,box['y']+150); pg.mouse.up()
    pg.click('#ca'); check('sketch attached', pg.locator('.att').count()==1)
    pg.click('#plus'); pg.click('#menu2 [data-act=project]'); pg.fill('#pn','Study'); pg.fill('#pi','Answer like a teacher'); pg.click('#pc'); pg.click('#mclose')
    check('project chip active', pg.is_visible('#projChip'))
    pg.click('#plus'); pg.click('#menu2 [data-act=build]'); pg.select_option('#bt','presentation'); pg.fill('#bp','my startup pitch'); pg.click('#bg'); pg.wait_for_selector('#bo iframe',timeout=8000); check('build panel + preview', pg.is_visible('#bo a.dl')); pg.click('#mclose')
    # language switch to Hindi + RTL for Arabic
    pg.select_option('#lang','hi'); check('hindi UI', 'Olma से पूछें' == pg.get_attribute('#input','placeholder'))
    pg.select_option('#lang','ar'); check('arabic RTL', pg.evaluate("document.documentElement.dir")=='rtl')
    pg.select_option('#lang','en')
    # reload persistence
    pg.reload(); pg.wait_for_selector('#chats .chat'); check('chats persist after reload', pg.locator('#chats .chat').count()>=2)
    pg.set_viewport_size({'width':390,'height':760}); pg.screenshot(path='/tmp/s4_mobile.png'); check('mobile menu button visible', pg.is_visible('#menu'))
    b.close()
finally:
    srv.terminate()
real=[e for e in errs if not e.startswith('dialog')]
print('JS errors:',real)
bad=[n for n,c in ok if not c]; print('FAILED:',bad); sys.exit(1 if bad or real else 0)
