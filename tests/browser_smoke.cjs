const { chromium } = require("playwright");
const assert = require("node:assert/strict");
(async () => {
  const browser = await chromium.launch({headless:true,channel:process.env.ARTFLOW_BROWSER_CHANNEL});
  const page = await browser.newPage({viewport:{width:1440,height:1000}});
  const errors=[];
  page.on("pageerror", error=>errors.push(error.message));
  await page.goto(process.argv[2] || "http://127.0.0.1:4180");
  await page.waitForFunction(()=>document.querySelector("#assetTitle").textContent==="Campfire");
  for (const [label,id] of [["Campfire","campfire"],["Crystal","crystal"]]) {
    await page.getByRole("button",{name:label,exact:true}).click();
    await page.waitForFunction(label=>document.querySelector("#assetTitle").textContent===label,label);
    assert.equal(await page.locator("#actionLabel").innerText(),"Build and verify");
    await page.locator("#runActionButton").click();
    await page.locator("#planDialog").waitFor({state:"visible"});
    await page.locator("#confirmation").fill(id);
    await page.locator("#submitPlan").click();
    await page.waitForFunction(()=>document.querySelector("#publishedState").textContent.includes("已验证"),{},{timeout:15000});
    assert(await page.locator("#previewImage").evaluate(img=>img.complete&&img.naturalWidth>0));
    assert(await page.locator(".step-output-card img").isVisible());
  }
  await page.getByRole("button",{name:"Campfire",exact:true}).click();
  await page.waitForFunction(()=>document.querySelector("#assetTitle").textContent==="Campfire");
  await page.getByRole("button",{name:"黑",exact:true}).click();
  assert.equal(await page.locator("#previewViewport").getAttribute("data-background"),"black");
  await page.getByRole("button",{name:"放大",exact:true}).click();
  const transform=await page.locator("#previewStage").evaluate(el=>el.style.transform);
  assert(transform.includes("1.25"));
  await page.getByRole("button",{name:"适配视图",exact:true}).click();
  await page.getByRole("button",{name:"白",exact:true}).click();
  await page.screenshot({path:process.argv[3]+"/desktop.png",fullPage:true});
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:process.argv[3]+"/mobile.png",fullPage:true});
  const overflow=await page.evaluate(()=>({body:document.body.scrollWidth,window:innerWidth}));
  assert(overflow.body<=overflow.window,JSON.stringify(overflow));
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({assets:2,production:"passed",preview:"passed",mobile:overflow,pageErrors:errors}));
  await browser.close();
})().catch(error=>{console.error(error);process.exit(1)});
