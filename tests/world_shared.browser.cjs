// All API responses are mocked. No GitHub posting occurs.
const {chromium}=require('playwright');
const {execFileSync}=require('node:child_process');
const assert=require('node:assert/strict');
(async()=>{
 const html=execFileSync(process.env.PYTHON || 'python3',['-c',`import web_ui as u
v=u.example_data('world');v['board']['shared_issue']='myon-bioinformatics/web-ui/123'
print(u.world_document(v))`],{encoding:'utf8'});
 const browser=await chromium.launch({headless:true});
 try{
 for(const width of [390,1280]){
 const page=await browser.newPage({viewport:{width,height:844}});
 let calls=0,fail=false;const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('https://api.github.com/**',async route=>{
  calls++;assert.equal(route.request().method(),'GET');assert.equal(route.request().headers()['authorization'],undefined);
  if(fail)return route.fulfill({status:429,json:{message:'rate limited'},headers:{'retry-after':'300'}});
  await route.fulfill({json:[{body:'<img src=x onerror=alert(1)> 駅で集合',user:{login:'alice'},created_at:'2026-11-03T00:00:00Z'}]});
 });
 await page.route('http://world.test/',r=>r.fulfill({contentType:'text/html',body:html}));
 await page.goto('http://world.test/');assert.equal(calls,0);
 await page.locator('.ui-board-shared summary').click();
 const refresh=page.locator('[data-shared-refresh]');await refresh.click();
 await page.locator('[data-shared-comments] li').waitFor();
 assert.match(await page.locator('[data-shared-comments]').innerText(),/alice.*駅で集合/);
 assert.equal(await page.locator('[data-shared-comments] img').count(),0);
 await refresh.click();assert.equal(calls,1);
 const link=page.locator('.ui-board-shared a');assert.match(await link.getAttribute('href'),/issues\/123#new_comment_field$/);
 assert.equal(await link.getAttribute('target'),'_blank');
 await page.locator('.ui-board-post input').fill('端末だけ');await page.locator('.ui-board-post button').click();
 assert.equal(await page.locator('.ui-board-note').count(),2);
 assert.match(await page.locator('[data-shared-comments]').innerText(),/駅で集合/);
 await page.clock.install();await page.clock.fastForward(121000);fail=true;await refresh.click();
 await page.waitForFunction(()=>document.querySelector('[data-shared-status]').textContent.includes('取得できません'));
 assert.match(await page.locator('[data-shared-comments]').innerText(),/駅で集合/);
 await refresh.click();assert.equal(calls,2);
 assert.equal(await page.evaluate(()=>localStorage.length),0);
 await page.reload();assert.equal(await page.locator('.ui-board-note').count(),0);assert.equal(calls,2);
 assert.deepEqual(errors,[]);await page.close();
 }
 }finally{await browser.close()}
 console.log('shared board Chromium: desktop/mobile passed');
})().catch(e=>{console.error(e);process.exitCode=1});
